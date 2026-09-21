"""The turn.e2e measurement spine (Phase 0 of the latency plan).

Five independent reviews each asked for the same missing number: one line per
turn, in the caller's clock, carrying which end-of-turn signal bound and what
each stage cost. Most of the values already existed and were discarded; these
tests pin that they now reach the trace, and that the clock is the right one.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from voice.crm_sink_observer import _cached_input_tokens


class _Session:
    session_id = "VS-TEST"
    interaction_id = "IX-TEST"
    extra: dict = {}


class _Sink:
    """The sink's real trace methods over a real TurnTrace, nothing else."""

    from voice.crm_sink import CrmSink

    record_turn_metric = CrmSink.record_turn_metric
    set_turn_context = CrmSink.set_turn_context
    emit_turn_trace = CrmSink.emit_turn_trace
    _trace = CrmSink._trace

    def __init__(self) -> None:
        from voice.turn_trace import TurnTrace

        self.session = _Session()
        self._turn_trace = TurnTrace(self._trace)
        self._pending_breakdown = {}

    @property
    def _turn_extra(self):
        return self._turn_trace.pending


class _Breakdown:
    user_turn_start_time = 1_700_000_000.0


@pytest.fixture
def trace_lines(caplog):
    caplog.set_level(logging.WARNING, logger="voice.trace")
    return caplog


def _fields(record_msg: str) -> dict[str, str]:
    # "voice.trace turn.e2e a=1 b=2"
    parts = record_msg.split()
    return dict(p.split("=", 1) for p in parts[2:] if "=" in p)


def test_turn_trace_carries_the_caller_clock_not_only_the_pipeline_one(trace_lines):
    """BotStartedSpeakingFrame fires when audio is handed to the transport.
    The output buffer still has to be added before the number is what the
    borrower felt."""
    sink = _Sink()
    sink.set_turn_context(transport="asterisk", sample_hz=16000, out_buffer_ms=40)
    sink._pending_breakdown = {"llm_ttfb_ms": 900, "tts_ttfb_ms": 250}

    sink.emit_turn_trace(_Breakdown(), latency_ms=1800.0)

    line = next(r.getMessage() for r in trace_lines.records if "turn.e2e" in r.getMessage())
    f = _fields(line)
    assert f["pipeline_ms"] == "1800"
    assert f["caller_ms"] == "1840", "the output buffer was not added back"
    assert f["origin"] == "speech_end"
    assert f["transport"] == "asterisk" and f["sample_hz"] == "16000"
    assert f["llm_ttfb_ms"] == "900"


def test_turn_trace_carries_the_values_their_producers_used_to_discard(trace_lines):
    sink = _Sink()
    sink.set_turn_context(out_buffer_ms=40)
    sink.record_turn_metric(
        smart_turn_ms=118,
        smart_turn_prob=0.91,
        smart_turn_complete=1,
        leading_silence_ms=60,
        kb_source="speculative",
        kb_wait_ms=310,
    )

    sink.emit_turn_trace(_Breakdown(), latency_ms=1000.0)

    f = _fields(next(r.getMessage() for r in trace_lines.records if "turn.e2e" in r.getMessage()))
    assert f["smart_turn_ms"] == "118"
    assert f["smart_turn_prob"] == "0.91"
    assert f["leading_silence_ms"] == "60"
    assert f["kb_source"] == "speculative"
    assert f["kb_wait_ms"] == "310"


def test_turn_metrics_do_not_leak_into_the_next_turn(trace_lines):
    """A per-turn value that survives its turn silently reports the wrong one."""
    sink = _Sink()
    sink.set_turn_context(out_buffer_ms=40)
    sink.record_turn_metric(smart_turn_ms=118)
    sink.emit_turn_trace(_Breakdown(), latency_ms=1000.0)
    sink.emit_turn_trace(_Breakdown(), latency_ms=1100.0)

    lines = [r.getMessage() for r in trace_lines.records if "turn.e2e" in r.getMessage()]
    assert "smart_turn_ms=118" in lines[0]
    assert "smart_turn_ms" not in lines[1]
    # Context is per-call, not per-turn, so it must survive.
    assert "out_buffer_ms=40" in lines[1]


def test_context_survives_but_never_overwrites_a_measured_value(trace_lines):
    sink = _Sink()
    sink.set_turn_context(transport="twilio", sample_hz=8000, out_buffer_ms=40)
    sink._pending_breakdown = {"tool_ms": 700}
    sink.record_turn_metric(kb_source="inline")
    sink.emit_turn_trace(_Breakdown(), latency_ms=2500.0)

    f = _fields(next(r.getMessage() for r in trace_lines.records if "turn.e2e" in r.getMessage()))
    assert f["transport"] == "twilio" and f["sample_hz"] == "8000"
    assert f["tool_ms"] == "700" and f["kb_source"] == "inline"
    assert f["caller_ms"] == "2540"


# ------------------------------------------------------ cached-token plumbing


def test_cached_tokens_are_read_from_the_azure_shape():
    """Only the Anthropic spelling was read, against an Azure deployment, so no
    voice call had ever recorded a prompt-cache hit."""

    class _Details:
        cached_tokens = 1536

    class _Usage:
        prompt_tokens_details = _Details()

    assert _cached_input_tokens(_Usage()) == 1536
    assert _cached_input_tokens({"prompt_tokens_details": {"cached_tokens": 64}}) == 64


def test_token_usage_is_its_own_line_not_folded_into_the_turn(trace_lines):
    """LLM usage is pushed when the response finishes, and the bot starts
    speaking while it is still streaming -- so it can arrive after turn.e2e is
    assembled. Folding it in would report the prompt-cache hit rate against the
    following turn, which is exactly the evidence the prompt reorder needs."""
    from pipecat.frames.frames import MetricsFrame
    from pipecat.metrics.metrics import LLMUsageMetricsData
    from pipecat.metrics.metrics import LLMTokenUsage

    from voice import crm_sink_observer

    sink = _Sink()
    sink.usage = type("U", (), {"record_llm": lambda self, **kw: None})()
    sink.record_ttfb_ms = lambda _ms: None
    sink.record_ttfa_ms = lambda _ms: None
    sink.record_tokens = lambda _n: None

    observer = crm_sink_observer.build(sink)
    item = LLMUsageMetricsData(
        processor="llm",
        model="gpt",
        value=LLMTokenUsage(prompt_tokens=900, completion_tokens=40, total_tokens=940),
    )
    frame = MetricsFrame(data=[item])
    asyncio.run(observer.on_push_frame(type("D", (), {"frame": frame})()))

    lines = [r.getMessage() for r in trace_lines.records]
    assert any("llm.turn" in line and "prompt_tokens=900" in line for line in lines), lines
    assert "prompt_tokens" not in sink._turn_extra, (
        "token usage was stashed for turn.e2e and can land on the wrong turn"
    )


def test_turn_metrics_are_cleared_when_a_turn_starts():
    """turn.e2e clears them, but only on BotStartedSpeakingFrame -- a turn the
    bot never answers would carry its measurements into the next one."""
    from voice.crm_sink import CrmSink

    handlers: dict[str, object] = {}

    class _Agg:
        def event_handler(self, name):
            def deco(fn):
                handlers[name] = fn
                return fn

            return deco

    sink = _Sink()
    sink._turn_trace.record(smart_turn_ms=118)
    CrmSink.attach_aggregators(sink, _Agg(), _Agg())

    assert "on_user_turn_started" in handlers, "no turn-start hook is installed"
    asyncio.run(handlers["on_user_turn_started"](None))
    assert sink._turn_extra == {}, "last turn's measurements survived into this one"
