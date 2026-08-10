"""Per-turn latency breakdown mapping (voice/crm_sink.py).

Pipecat's UserBotLatencyObserver reports whichever services happen to be in the
pipeline, identified only by the reporting processor's name — there are no named
slots. These tests pin the name→column mapping and the drain-into-bot_turn
lifecycle, since a mis-mapped column is silent: the row still writes, it just
attributes the latency to the wrong service.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from voice.crm_sink import CrmSink
from voice.session import VoiceSession


@dataclass
class _Ttfb:
    processor: str
    duration_secs: float
    model: str | None = None
    start_time: float = 0.0


@dataclass
class _Aggregation:
    processor: str = "AzureTTSService#0"
    duration_secs: float = 0.0
    start_time: float = 0.0


@dataclass
class _Call:
    function_name: str
    duration_secs: float
    start_time: float = 0.0


@dataclass
class _Breakdown:
    """Structurally identical to pipecat's LatencyBreakdown (duck-typed)."""

    ttfb: list[_Ttfb] = field(default_factory=list)
    text_aggregation: _Aggregation | None = None
    user_turn_start_time: float | None = None
    user_turn_secs: float | None = None
    function_calls: list[_Call] = field(default_factory=list)

    def chronological_events(self) -> list[str]:
        return [f"{t.processor}: TTFB {t.duration_secs:.3f}s" for t in self.ttfb]


@pytest.fixture
def sink() -> CrmSink:
    return CrmSink(VoiceSession(session_id="VS-TESTTEST01"))


def _full_breakdown() -> _Breakdown:
    return _Breakdown(
        ttfb=[
            _Ttfb("AzureSTTService#0", 0.180),
            _Ttfb("KeepAliveAzureLLMService#0", 1.420),
            _Ttfb("KeepAliveAzureTTSService#0", 0.310),
        ],
        text_aggregation=_Aggregation(duration_secs=0.045),
        user_turn_secs=0.760,
        function_calls=[_Call("get_account_position", 0.230)],
    )


def test_breakdown_maps_processors_to_columns(sink: CrmSink) -> None:
    sink.record_latency_breakdown(_full_breakdown())

    assert sink._pending_breakdown == {
        "stt_ttfb_ms": 180,
        "llm_ttfb_ms": 1420,
        "tts_ttfb_ms": 310,
        "user_turn_ms": 760,
        "aggregation_ms": 45,
        "tool_ms": 230,
    }


def test_unrecognised_processor_is_dropped_not_guessed(sink: CrmSink) -> None:
    """A future processor must not be silently filed under an existing column."""
    sink.record_latency_breakdown(
        _Breakdown(ttfb=[_Ttfb("SomeNewVisionService#0", 0.500)])
    )
    assert sink._pending_breakdown == {}


def test_function_call_durations_sum_into_tool_ms(sink: CrmSink) -> None:
    sink.record_latency_breakdown(
        _Breakdown(
            function_calls=[
                _Call("search_knowledge_base", 0.400),
                _Call("get_account_position", 0.150),
            ]
        )
    )
    assert sink._pending_breakdown["tool_ms"] == 550


def test_missing_user_turn_secs_yields_absent_not_zero(sink: CrmSink) -> None:
    """The Twilio path may emit no VADUserStoppedSpeakingFrame at all.

    The column must stay NULL rather than claim a 0ms user turn.
    """
    sink.record_latency_breakdown(_Breakdown(ttfb=[_Ttfb("AzureSTTService#0", 0.2)]))
    assert "user_turn_ms" not in sink._pending_breakdown


def test_zero_duration_metrics_are_ignored(sink: CrmSink) -> None:
    sink.record_latency_breakdown(
        _Breakdown(
            ttfb=[_Ttfb("AzureSTTService#0", 0.0)],
            text_aggregation=_Aggregation(duration_secs=0.0),
            user_turn_secs=0.0,
            function_calls=[_Call("noop", 0.0)],
        )
    )
    assert sink._pending_breakdown == {}


def test_first_report_per_service_wins(sink: CrmSink) -> None:
    """A retried service must not overwrite the measurement that cost the turn."""
    sink.record_latency_breakdown(
        _Breakdown(
            ttfb=[
                _Ttfb("KeepAliveAzureLLMService#0", 1.900),
                _Ttfb("KeepAliveAzureLLMService#1", 0.100),
            ]
        )
    )
    assert sink._pending_breakdown["llm_ttfb_ms"] == 1900


def test_breakdown_lands_on_the_next_bot_turn_job_and_clears(sink: CrmSink) -> None:
    sink.session.interaction_id = "IX-TEST"
    sink.record_latency_breakdown(_full_breakdown())
    sink.record_ttfb_ms(1420.0)

    jobs: list[tuple[str, dict]] = []
    sink.enqueue = lambda kind, **payload: jobs.append((kind, payload))  # type: ignore[method-assign]

    # Drive the same drain the assistant-turn handler performs.
    breakdown = sink._pending_breakdown
    sink._pending_breakdown = {}
    sink.enqueue("bot_turn", turn_index=1, text="hi", **breakdown)

    kind, payload = jobs[0]
    assert kind == "bot_turn"
    assert payload["llm_ttfb_ms"] == 1420
    assert payload["user_turn_ms"] == 760
    assert sink._pending_breakdown == {}, "must not bleed into the following turn"


def test_malformed_breakdown_does_not_raise(sink: CrmSink) -> None:
    """This runs off an observer callback; an exception there kills the handler."""
    sink.record_latency_breakdown(object())
    assert sink._pending_breakdown == {}


def test_payload_is_rtvi_shaped(sink: CrmSink) -> None:
    b = _full_breakdown()
    sink.record_latency_breakdown(b)
    payload = sink.latency_breakdown_payload(b)

    assert payload["llmTtfbMs"] == 1420
    assert payload["userTurnMs"] == 760
    assert payload["toolNames"] == ["get_account_position"]
    assert any("TTFB" in e for e in payload["events"])


def test_user_bot_latency_is_recorded_in_ms(sink: CrmSink) -> None:
    sink.record_user_bot_latency_ms(1234.0)
    sink.record_user_bot_latency_ms(0.0)  # ignored
    assert sink._user_bot_latency_ms == [1234.0]


# --------------------------------------------------------------- pipecat contract
# bot.py registers handlers by event *name*. A rename on a pipecat bump would
# raise inside run_bot at call setup, where the try/except would swallow it and
# latency would silently go missing. Assert the contract here instead.


def test_latency_observer_exposes_the_events_bot_py_registers() -> None:
    from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver

    obs = UserBotLatencyObserver()
    for event in (
        "on_latency_breakdown",
        "on_latency_measured",
        "on_first_bot_speech_latency",
    ):
        # _register_event_handler was called for each in __init__; registering a
        # handler for an unknown event is what raises.
        obs.event_handler(event)(lambda *_a, **_k: None)


def test_startup_timing_observer_exposes_its_events() -> None:
    from pipecat.observers.startup_timing_observer import StartupTimingObserver

    obs = StartupTimingObserver()
    for event in ("on_startup_timing_report", "on_transport_timing_report"):
        obs.event_handler(event)(lambda *_a, **_k: None)


def test_real_latency_breakdown_maps_through_our_code() -> None:
    """Use pipecat's own model, not our duck-typed stand-in.

    The stand-in above could drift from LatencyBreakdown's real field names and
    every test would still pass while production mapped nothing.
    """
    from pipecat.observers.user_bot_latency_observer import (
        LatencyBreakdown,
        TTFBBreakdownMetrics,
    )

    sink = CrmSink(VoiceSession(session_id="VS-REALREAL01"))
    sink.record_latency_breakdown(
        LatencyBreakdown(
            ttfb=[
                TTFBBreakdownMetrics(
                    processor="KeepAliveAzureLLMService#0",
                    start_time=0.0,
                    duration_secs=1.25,
                )
            ],
            user_turn_secs=0.5,
        )
    )
    assert sink._pending_breakdown == {"llm_ttfb_ms": 1250, "user_turn_ms": 500}
