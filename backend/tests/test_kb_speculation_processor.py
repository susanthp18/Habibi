"""Frame handling of KbSpeculationProcessor (voice/kb_enrich.py).

This processor sits **upstream of the user aggregator**, which is the riskiest
placement in the pipeline: everything the caller says passes through it before
anything else can act. If it drops, reorders, or blocks on a frame, the call
wedges. Hence "push first, inspect after", and hence these tests.
"""

from __future__ import annotations

import asyncio

import pytest
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from voice import config as voice_config
from voice.kb_enrich import KbCache, KbSpeculationProcessor

_POLICY_Q = "how does the grace period work on my loan account"


def _interim(text: str) -> InterimTranscriptionFrame:
    return InterimTranscriptionFrame(text, "user", "2026-07-27T00:00:00Z")


def _final(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text, "user", "2026-07-27T00:00:00Z")


class _Harness:
    """Captures what the processor pushes downstream."""

    def __init__(self, cache: KbCache) -> None:
        self.proc = KbSpeculationProcessor(cache)
        self.pushed: list = []

        async def _push(frame, direction=FrameDirection.DOWNSTREAM):
            self.pushed.append(frame)

        self.proc.push_frame = _push  # type: ignore[method-assign]

    async def send(self, frame) -> None:
        await self.proc.process_frame(frame, FrameDirection.DOWNSTREAM)


@pytest.fixture(autouse=True)
def _fast_debounce(monkeypatch: pytest.MonkeyPatch):
    """Keep the tests quick without disabling the debounce entirely."""
    monkeypatch.setattr(voice_config, "kb_spec_stable_ms", lambda: 30)
    monkeypatch.setattr(voice_config, "kb_spec_min_words", lambda: 4)


def _cache_recording(calls: list) -> KbCache:
    cache = KbCache(kb_snapshot_id="snap")

    async def _retrieve(query, product_keys):
        calls.append(query)
        return [{"snippet": "s", "score": 0.9, "chunkId": "c1"}]

    cache._retrieve = _retrieve  # type: ignore[method-assign]
    return cache


def test_every_frame_is_pushed_unmodified_and_in_order() -> None:
    """This processor must never swallow, reorder, or rewrite a frame.

    StartFrame is excluded because pipecat's own FrameProcessor base class
    requires an initialised TaskManager to handle it — that is framework
    behaviour every processor in the pipeline shares, not anything this class
    does differently.
    """

    async def scenario() -> list:
        h = _Harness(_cache_recording([]))
        frames = [
            VADUserStartedSpeakingFrame(),
            _interim("hello there how are"),
            _final("hello there how are you"),
            EndFrame(),
        ]
        for f in frames:
            await h.send(f)
        return [type(f).__name__ for f in h.pushed]

    pushed = asyncio.run(scenario())
    assert pushed == [
        "VADUserStartedSpeakingFrame",
        "InterimTranscriptionFrame",
        "TranscriptionFrame",
        "EndFrame",
    ]


def test_the_frame_is_pushed_before_any_work_happens() -> None:
    """"Push first, inspect after" — a slow gate must not delay audio.

    Written as an ordering assertion rather than a timing one so it cannot go
    flaky.
    """
    order: list[str] = []

    async def scenario() -> None:
        cache = KbCache(kb_snapshot_id="snap")

        def _slow_gate(_query):
            order.append("gate")
            return "disabled"

        cache.skip_reason = _slow_gate  # type: ignore[method-assign]
        h = _Harness(cache)

        async def _push(frame, direction=FrameDirection.DOWNSTREAM):
            order.append("push")

        h.proc.push_frame = _push  # type: ignore[method-assign]

        await h.send(_interim(_POLICY_Q))
        await asyncio.sleep(0.1)
        await h.proc.cleanup()

    asyncio.run(scenario())
    assert order and order[0] == "push", f"work happened before the push: {order}"


def test_stability_debounce_fires_once_for_a_burst_of_interims() -> None:
    """Azure emits many interims per second; only the last stable one may fire."""
    calls: list[str] = []

    async def scenario() -> None:
        h = _Harness(_cache_recording(calls))
        await h.send(VADUserStartedSpeakingFrame())
        for partial in (
            "how does the grace",
            "how does the grace period",
            "how does the grace period work",
            "how does the grace period work on my loan account",
        ):
            await h.send(_interim(partial))
            await asyncio.sleep(0.005)  # faster than the 30ms debounce
        await asyncio.sleep(0.15)  # let the surviving timer fire
        await h.proc.cleanup()

    asyncio.run(scenario())
    assert len(calls) == 1, f"expected one embed for the burst, got {len(calls)}: {calls}"
    assert calls[0] == "how does the grace period work on my loan account"


def test_a_final_before_the_debounce_cancels_the_speculation() -> None:
    """A fast utterance must not pay for both a speculation and the final."""
    calls: list[str] = []

    async def scenario() -> None:
        h = _Harness(_cache_recording(calls))
        await h.send(VADUserStartedSpeakingFrame())
        await h.send(_interim(_POLICY_Q))
        await h.send(_final(_POLICY_Q))  # arrives before the 30ms debounce
        await asyncio.sleep(0.1)
        await h.proc.cleanup()

    asyncio.run(scenario())
    assert calls == [], "speculated even though the final had already arrived"


def test_short_partials_never_speculate() -> None:
    calls: list[str] = []

    async def scenario() -> None:
        h = _Harness(_cache_recording(calls))
        await h.send(VADUserStartedSpeakingFrame())
        await h.send(_interim("yes ok"))
        await asyncio.sleep(0.1)
        await h.proc.cleanup()

    asyncio.run(scenario())
    assert calls == []


def test_gated_intents_never_speculate() -> None:
    """Spend guard: the full gate runs on the partial too, or we multiply embed
    cost across turns we would never have enriched."""
    calls: list[str] = []

    async def scenario() -> None:
        h = _Harness(_cache_recording(calls))
        await h.send(VADUserStartedSpeakingFrame())
        await h.send(_interim("what is my outstanding balance right now please"))
        await asyncio.sleep(0.1)
        await h.proc.cleanup()

    asyncio.run(scenario())
    assert calls == [], "speculated on a balance_query"


def test_cooldown_suppresses_speculation() -> None:
    calls: list[str] = []

    async def scenario() -> None:
        cache = _cache_recording(calls)
        cache.suppress(30)
        h = _Harness(cache)
        await h.send(VADUserStartedSpeakingFrame())
        await h.send(_interim(_POLICY_Q))
        await asyncio.sleep(0.1)
        await h.proc.cleanup()

    asyncio.run(scenario())
    assert calls == []


def test_end_frame_cancels_in_flight_work() -> None:
    """Teardown must not leave a retrieval pending past the pipeline."""

    async def scenario() -> bool:
        cache = KbCache(kb_snapshot_id="snap")

        async def _slow(query, product_keys):
            await asyncio.sleep(5)
            return []

        cache._retrieve = _slow  # type: ignore[method-assign]
        h = _Harness(cache)
        await h.send(VADUserStartedSpeakingFrame())
        await h.send(_interim(_POLICY_Q))
        await asyncio.sleep(0.1)  # let the debounce fire
        started = list(cache._inflight.values())
        await h.send(EndFrame())
        await asyncio.sleep(0)
        return bool(started) and all(t.cancelled() for t in started)

    assert asyncio.run(scenario()), "in-flight retrieval survived EndFrame"


def test_cancel_frame_is_handled_like_end_frame() -> None:
    async def scenario() -> list:
        h = _Harness(_cache_recording([]))
        await h.send(CancelFrame())
        return [type(f).__name__ for f in h.pushed]

    assert asyncio.run(scenario()) == ["CancelFrame"]


def test_speculation_disabled_makes_the_processor_a_pure_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(voice_config, "kb_spec_enabled", lambda: False)
    calls: list[str] = []

    async def scenario() -> list:
        h = _Harness(_cache_recording(calls))
        await h.send(VADUserStartedSpeakingFrame())
        await h.send(_interim(_POLICY_Q))
        await asyncio.sleep(0.1)
        await h.proc.cleanup()
        return [type(f).__name__ for f in h.pushed]

    pushed = asyncio.run(scenario())
    assert calls == []
    assert pushed == ["VADUserStartedSpeakingFrame", "InterimTranscriptionFrame"]


def test_a_new_turn_resets_the_budget() -> None:
    """Two separate questions in one call must both be able to speculate."""
    calls: list[str] = []

    async def scenario() -> None:
        h = _Harness(_cache_recording(calls))
        for q in (
            "how does the grace period work on my loan account",
            "can you explain the foreclosure charges in detail",
        ):
            await h.send(VADUserStartedSpeakingFrame())
            await h.send(_interim(q))
            await asyncio.sleep(0.1)
        await h.proc.cleanup()

    asyncio.run(scenario())
    assert len(calls) == 2, f"second turn could not speculate: {calls}"
