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


def test_ambient_attribution_applies_to_nested_meter_calls(events) -> None:
    """chat_with_tools() is called from deep stacks that cannot pass an id."""
    import usage_meter

    with usage_meter.attribute_to("CL-AMBIENT"):
        usage_meter.record_chat_usage(prompt_tokens=10, completion_tokens=2, model="m")
    assert events.of("llm_chat")["interaction_id"] == "CL-AMBIENT"


def test_decision_attribution_applies_to_nested_meter_calls(events) -> None:
    import usage_meter

    with usage_meter.attribute_to("CL-AMBIENT", decision_id="TD-AMBIENT"):
        usage_meter.record_chat_usage(prompt_tokens=10, completion_tokens=2, model="m")
    assert events.of("llm_chat")["interaction_id"] == "CL-AMBIENT"
    assert events.of("llm_chat")["decision_id"] == "TD-AMBIENT"
    assert usage_meter.current_decision_id() is None


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
