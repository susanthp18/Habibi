"""Voice-pipeline usage metering (voice/usage.py + crm_sink.build_observer).

These tests deliberately use the REAL pipecat metrics classes rather than
duck-typed stand-ins. The bug they guard against was precisely a wrong
assumption about those classes' shape: the observer read ``item.tokens`` /
``item.total_tokens`` / ``item.prompt_tokens``, none of which exist on
``LLMUsageMetricsData`` (its fields are ``processor``, ``model`` and
``value: LLMTokenUsage``). Every getattr returned None, so no tokens were ever
recorded and every production voice call went unbilled. A structural fake would
have passed the old code too.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from voice.crm_sink import CrmSink
from voice.session import VoiceSession

pipecat_metrics = pytest.importorskip("pipecat.metrics.metrics")
pipecat_frames = pytest.importorskip("pipecat.frames.frames")

LLMTokenUsage = pipecat_metrics.LLMTokenUsage
LLMUsageMetricsData = pipecat_metrics.LLMUsageMetricsData
TTSUsageMetricsData = pipecat_metrics.TTSUsageMetricsData
TTFBMetricsData = pipecat_metrics.TTFBMetricsData
MetricsFrame = pipecat_frames.MetricsFrame


class _Buffered:
    """Reads the meter's own pending-event buffer.

    Deliberately does not stub ``record_usage``: interaction attribution and
    money quantization both happen *inside* it, so stubbing it would test the
    stub. The buffer is the closest observation point to the INSERT that still
    involves no database.
    """

    def __init__(self, module) -> None:
        self._um = module

    def all(self) -> list[dict]:
        with self._um._buffer_lock:
            events = list(self._um._buffer)
        # meta is serialised on the way into the buffer; parse it back so tests
        # can assert on fields rather than substrings.
        return [{**e, "meta": json.loads(e["meta"])} for e in events]

    def of(self, service_id: str) -> dict:
        matches = [e for e in self.all() if e["service_id"] == service_id]
        assert len(matches) == 1, (
            f"expected exactly one {service_id} event, got {len(matches)}"
        )
        return matches[0]


@pytest.fixture
def events(monkeypatch) -> _Buffered:
    import usage_meter

    with usage_meter._buffer_lock:
        usage_meter._buffer.clear()
    # Keep the background flusher out of it: a real flush would both hit the
    # database and empty the buffer mid-assertion.
    monkeypatch.setattr(usage_meter, "_ensure_flusher", lambda: None)
    yield _Buffered(usage_meter)
    with usage_meter._buffer_lock:
        usage_meter._buffer.clear()


@pytest.fixture
def sink() -> CrmSink:
    return CrmSink(VoiceSession(session_id="VS-USAGE00001", interaction_id="CL-USAGE1"))


def _push(sink: CrmSink, *items) -> None:
    """Drive one MetricsFrame through the observer (repo idiom: asyncio.run)."""
    observer = sink.build_observer()
    assert observer is not None, "observer must build against the installed pipecat"
    asyncio.run(observer.on_push_frame(MetricsFrame(data=list(items))))



def test_llm_usage_metrics_data_has_no_flat_token_attributes() -> None:
    """Pins the shape that made the original code silently no-op.

    If a future pipecat adds flat ``tokens``/``total_tokens`` attributes this
    fails, which is the signal to revisit the observer — not a reason to go back
    to duck-typing.
    """
    item = LLMUsageMetricsData(
        processor="KeepAliveAzureLLMService#0",
        model="gpt-5-mini",
        value=LLMTokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    assert not hasattr(item, "tokens")
    assert not hasattr(item, "total_tokens")
    assert not hasattr(item, "prompt_tokens")
    assert item.value.prompt_tokens == 10


def test_llm_usage_is_metered_with_prompt_completion_split(sink, events) -> None:
    _push(
        sink,
        LLMUsageMetricsData(
            processor="KeepAliveAzureLLMService#0",
            model="gpt-5-mini",
            value=LLMTokenUsage(
                prompt_tokens=1200, completion_tokens=300, total_tokens=1500
            ),
        ),
    )

    event = events.of("llm_chat")
    assert event["meta"]["promptTokens"] == 1200
    assert event["meta"]["completionTokens"] == 300
    # The split must be measured, never the 70/30 fallback — they price ~8x apart.
    assert event["meta"]["splitEstimated"] is False
    assert event["model"] == "gpt-5-mini"
    assert event["interaction_id"] == "CL-USAGE1"
    assert float(event["units"]) == pytest.approx(1.5)

    assert sink.usage.prompt_tokens == 1200
    assert sink.usage.completion_tokens == 300
    assert sink.usage.llm_turns == 1


def test_llm_usage_populates_transcript_tokens(sink, events) -> None:
    """The regression that left interaction_transcript.tokens NULL on every call."""
    assert sink._pending_tokens is None
    _push(
        sink,
        LLMUsageMetricsData(
            processor="KeepAliveAzureLLMService#0",
            model="gpt-5-mini",
            value=LLMTokenUsage(prompt_tokens=800, completion_tokens=120, total_tokens=920),
        ),
    )
    assert sink._pending_tokens == 920


def test_total_tokens_wins_when_it_exceeds_the_split(sink, events) -> None:
    """Audio/reasoning tokens make total larger than prompt+completion."""
    _push(
        sink,
        LLMUsageMetricsData(
            processor="KeepAliveAzureLLMService#0",
            model="gpt-5-mini",
            value=LLMTokenUsage(
                prompt_tokens=100, completion_tokens=50, total_tokens=400
            ),
        ),
    )
    assert sink._pending_tokens == 400
    # Billing still uses the split it can actually price.
    assert events.of("llm_chat")["meta"]["completionTokens"] == 50


def test_tts_characters_are_metered(sink, events) -> None:
    _push(
        sink,
        TTSUsageMetricsData(
            processor="KeepAliveAzureTTSService#0",
            model="en-IN-NeerjaNeural",
            value=812,
        ),
    )
    event = events.of("tts_az")
    assert event["meta"]["chars"] == 812
    assert event["model"] == "en-IN-NeerjaNeural"
    assert event["interaction_id"] == "CL-USAGE1"
    # float() first: units is a Decimal, and approx() cannot subtract one from a
    # float. 0.812 is not exactly representable, unlike the 1.5 above.
    assert float(event["units"]) == pytest.approx(0.812)
    assert sink.usage.tts_chars == 812


def test_configured_voice_fills_in_when_metric_omits_model(sink, events) -> None:
    sink.usage.configure(tts_voice="en-IN-PrabhatNeural")
    _push(
        sink,
        TTSUsageMetricsData(processor="KeepAliveAzureTTSService#0", model=None, value=40),
    )
    assert events.of("tts_az")["model"] == "en-IN-PrabhatNeural"


def test_latency_metrics_do_not_produce_usage_events(sink, events) -> None:
    """TTFB shares the frame with usage data; it must not be billed."""
    _push(
        sink, TTFBMetricsData(processor="KeepAliveAzureLLMService#0", value=1.42)
    )
    assert events.all() == []
    # ...while still being captured as latency (seconds → ms).
    assert sink._pending_ttfb_ms == pytest.approx(1420.0)


def test_zero_token_usage_is_not_billed(sink, events) -> None:
    _push(
        sink,
        LLMUsageMetricsData(
            processor="KeepAliveAzureLLMService#0",
            model="gpt-5-mini",
            value=LLMTokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        ),
    )
    assert events.all() == []


def test_stt_is_derived_from_call_duration(sink, events) -> None:
    sink.usage.configure(stt_language="en-IN")
    sink.usage.finalize_stt(seconds=150.0)

    event = events.of("stt_az")
    assert event["units"] == pytest.approx(2.5)
    assert event["interaction_id"] == "CL-USAGE1"
    assert event["model"] == "en-IN"


def test_stt_finalize_is_idempotent(sink, events) -> None:
    """stop() can run twice; the call must not be billed for its audio twice."""
    sink.usage.finalize_stt(seconds=60.0)
    sink.usage.finalize_stt(seconds=60.0)
    assert len([e for e in events.all() if e["service_id"] == "stt_az"]) == 1


def test_zero_duration_call_is_not_billed_for_stt(sink, events) -> None:
    sink.usage.finalize_stt(seconds=0.0)
    assert events.all() == []


def test_interaction_id_is_read_lazily(events) -> None:
    """bind_session_start assigns it after the pipeline is built, so the meter
    must not capture it at construction time."""
    session = VoiceSession(session_id="VS-LATEBIND01")
    sink = CrmSink(session)
    assert sink.usage._interaction_id is None

    session.interaction_id = "CL-LATE01"
    sink.usage.record_tts(chars=10, model="v")
    assert events.of("tts_az")["interaction_id"] == "CL-LATE01"


def test_ambient_attribution_applies_to_nested_meter_calls(events) -> None:
    """chat_with_tools() is called from deep stacks that cannot pass an id."""
    import usage_meter

    with usage_meter.attribute_to("CL-AMBIENT"):
        usage_meter.record_chat_usage(prompt_tokens=10, completion_tokens=2, model="m")
    assert events.of("llm_chat")["interaction_id"] == "CL-AMBIENT"


def test_explicit_interaction_id_beats_ambient(events) -> None:
    import usage_meter

    with usage_meter.attribute_to("CL-AMBIENT"):
        usage_meter.record_chat_usage(
            prompt_tokens=10, completion_tokens=2, model="m", interaction_id="CL-EXPLICIT"
        )
    assert events.of("llm_chat")["interaction_id"] == "CL-EXPLICIT"


def test_attribution_does_not_leak_past_its_scope(events) -> None:
    """A worker thread handles job after job; misattribution would be silent."""
    import usage_meter

    with usage_meter.attribute_to("CL-JOB1"):
        pass
    assert usage_meter.current_interaction_id() is None
    usage_meter.record_chat_usage(prompt_tokens=10, completion_tokens=2, model="m")
    assert events.of("llm_chat")["interaction_id"] is None


def test_retarget_applies_within_scope_and_still_unwinds(events) -> None:
    """The bot_runtime pattern: open empty, retarget once the job is loaded."""
    import usage_meter

    with usage_meter.attribute_to(None):
        usage_meter.retarget_attribution("CL-LOADED")
        usage_meter.record_chat_usage(prompt_tokens=10, completion_tokens=2, model="m")
    assert events.of("llm_chat")["interaction_id"] == "CL-LOADED"
    assert usage_meter.current_interaction_id() is None


def test_attribution_survives_asyncio_to_thread(events) -> None:
    """The CRM sink does its DB work via to_thread; context must carry over."""
    import usage_meter

    async def _scenario() -> None:
        with usage_meter.attribute_to("CL-THREADED"):
            await asyncio.to_thread(
                usage_meter.record_chat_usage,
                prompt_tokens=10,
                completion_tokens=2,
                model="m",
            )

    asyncio.run(_scenario())
    assert events.of("llm_chat")["interaction_id"] == "CL-THREADED"


def test_metering_failure_never_breaks_the_call(sink, monkeypatch) -> None:
    """Metering sits on the audio path; it may lose an event but not raise."""

    def _boom(**kwargs):
        raise RuntimeError("meter exploded")

    monkeypatch.setattr("usage_meter.record_usage", _boom)
    sink.usage.record_llm(prompt_tokens=10, completion_tokens=1, model="m")
    sink.usage.record_tts(chars=10, model="v")
    sink.usage.finalize_stt(seconds=10.0)
