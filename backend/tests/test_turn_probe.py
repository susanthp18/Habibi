"""Bot turns are read at the LLM→TTS boundary, not at the end of the pipeline.

Regression guard for two defects observed on call VS-6B252E0479 (2026-08-01),
both caused by taking the transcript from ``on_assistant_turn_stopped``:

* Two spoken re-engagement turns were never persisted. ``TTSService`` holds each
  ``LLMFullResponseEndFrame`` until its audio context drains and **clears** the
  pending map on interruption (``tts_service.py:946``), so a turn the caller
  barges in on never closes downstream.
* Bot turns were stamped 10-20s after they were produced, because the assistant
  aggregator sits behind the output transport, while customer turns are stamped
  on the unpaced input side.
"""

from __future__ import annotations

import asyncio

from pipecat.frames.frames import (
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from voice.turn_probe import SpokeThisResponseProbe


class _Recorder:
    def __init__(self) -> None:
        self.turns: list[tuple[str, bool]] = []

    async def __call__(self, text: str, interrupted: bool) -> None:
        self.turns.append((text, interrupted))


def _run(frames, *, handler=None):
    rec = _Recorder()
    probe = SpokeThisResponseProbe(on_bot_turn=handler or rec)
    # push_frame needs a linked downstream; a bare stub keeps the probe a tap.
    probe.push_frame = _noop  # type: ignore[method-assign]

    async def drive():
        for f in frames:
            await probe.process_frame(f, FrameDirection.DOWNSTREAM)

    asyncio.run(drive())
    return rec, probe


async def _noop(frame, direction=None):  # noqa: ANN001
    return None


def test_a_complete_response_is_reported_once() -> None:
    rec, _ = _run(
        [
            LLMFullResponseStartFrame(),
            TextFrame("For travel, you can choose Travel Protect360"),
            TextFrame(" — domestic or international?"),
            LLMFullResponseEndFrame(),
        ]
    )
    assert rec.turns == [
        ("For travel, you can choose Travel Protect360 — domestic or international?", False)
    ]


def test_barge_in_still_reports_the_turn_and_flags_it() -> None:
    """The old path lost this turn entirely — the end frame was discarded."""
    rec, _ = _run(
        [
            LLMFullResponseStartFrame(),
            TextFrame("Thanks, for 5 members you can consider"),
            InterruptionFrame(),
            LLMFullResponseEndFrame(),
        ]
    )
    assert rec.turns == [("Thanks, for 5 members you can consider", True)]


def test_a_response_cut_off_by_the_next_one_is_not_lost() -> None:
    """No end frame ever arrives — the next response's start closes it."""
    rec, _ = _run(
        [
            LLMFullResponseStartFrame(),
            TextFrame("first reply"),
            LLMFullResponseStartFrame(),
            TextFrame("second reply"),
            LLMFullResponseEndFrame(),
        ]
    )
    assert rec.turns == [("first reply", True), ("second reply", False)]


def test_an_empty_response_is_not_recorded() -> None:
    """A bare tool call emits no text; it is not a turn the caller heard."""
    rec, _ = _run([LLMFullResponseStartFrame(), LLMFullResponseEndFrame()])
    assert rec.turns == []


def test_text_outside_a_response_is_ignored() -> None:
    """TTSSpeakFrame-driven fillers have no surrounding response frames."""
    rec, _ = _run([TextFrame("Sure, let me look that up.")])
    assert rec.turns == []


def test_a_failing_handler_never_breaks_the_pipeline() -> None:
    async def boom(text: str, interrupted: bool) -> None:
        raise RuntimeError("crm is down")

    rec, probe = _run(
        [LLMFullResponseStartFrame(), TextFrame("hello"), LLMFullResponseEndFrame()],
        handler=boom,
    )
    assert rec.turns == []  # handler raised, nothing recorded
    assert probe.spoke_this_response is True  # …and the probe kept working


# --------------------------------------------------------- filler interlock


def test_spoke_flag_tracks_the_in_flight_response() -> None:
    """Unchanged contract: the tool-latency filler reads this before speaking."""
    probe = SpokeThisResponseProbe()
    probe.push_frame = _noop  # type: ignore[method-assign]

    async def drive():
        await probe.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
        assert probe.spoke_this_response is False
        await probe.process_frame(TextFrame("Sure, I can set that up."), FrameDirection.DOWNSTREAM)
        assert probe.spoke_this_response is True
        await probe.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
        assert probe.spoke_this_response is False

    asyncio.run(drive())


def test_first_tts_callback_fires_once_on_the_first_text_frame() -> None:
    seen: list[str] = []
    probe = SpokeThisResponseProbe(on_first_tts=seen.append)
    probe.push_frame = _noop  # type: ignore[method-assign]

    async def drive():
        await probe.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
        await probe.process_frame(TextFrame("Sure—I can set that up."), FrameDirection.DOWNSTREAM)
        await probe.process_frame(TextFrame(" Hello."), FrameDirection.DOWNSTREAM)

    asyncio.run(drive())
    assert seen == ["Sure—I can set that up."]
