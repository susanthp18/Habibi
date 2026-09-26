"""What the caller says over the greeting is held, not dropped."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("pipecat")

from pipecat.frames.frames import (  # noqa: E402
    TranscriptionFrame,
    UserMuteStartedFrame,
    UserMuteStoppedFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection  # noqa: E402

from voice.greeting_hold import (  # noqa: E402
    GreetingHold,
    is_hold_replay,
)


def _drive(frames: list[tuple[object, FrameDirection]], *, timeout_secs: float = 0.0) -> list[object]:
    hold = GreetingHold(timeout_secs=timeout_secs)
    out: list[object] = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        out.append(frame)

    hold.push_frame = capture  # type: ignore[method-assign]

    async def go() -> None:
        for frame, direction in frames:
            await hold.process_frame(frame, direction)

    asyncio.run(go())
    return out


def _t(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text=text, user_id="caller", timestamp="t")


def test_speech_during_the_greeting_is_replayed_as_one_turn() -> None:
    down, up = FrameDirection.DOWNSTREAM, FrameDirection.UPSTREAM
    out = _drive(
        [
            (UserMuteStartedFrame(), up),
            (_t("Hello?"), down),
            (_t("Who is this?"), down),
            (UserMuteStoppedFrame(), up),
        ]
    )
    kinds = [type(f).__name__ for f in out]
    assert kinds == [
        "UserMuteStartedFrame",
        "UserMuteStoppedFrame",
        "TranscriptionFrame",
    ]
    replay = out[2]
    assert replay.text == "Hello? Who is this?"
    assert replay.finalized is True
    assert is_hold_replay(replay)
    assert not any(isinstance(f, (VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame)) for f in out)


def test_only_the_first_mute_window_is_held() -> None:
    down, up = FrameDirection.DOWNSTREAM, FrameDirection.UPSTREAM
    out = _drive(
        [
            (UserMuteStartedFrame(), up),
            (UserMuteStoppedFrame(), up),
            (UserMuteStartedFrame(), up),  # a later function-call mute
            (_t("mid tool"), down),
        ]
    )
    assert isinstance(out[-1], TranscriptionFrame) and out[-1].text == "mid tool"
    assert not is_hold_replay(out[-1])
    assert not any(isinstance(f, (VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame)) for f in out)


def test_interims_during_the_greeting_reach_the_speculator() -> None:
    """The speculator sits between this processor and the muted aggregator.

    Dropping interims here starved retrieval on the one turn that overlaps the
    disclosure. The aggregator still drops them itself while muted; forwarding
    them only lets speculation start during the greeting.
    """
    from pipecat.frames.frames import InterimTranscriptionFrame

    down, up = FrameDirection.DOWNSTREAM, FrameDirection.UPSTREAM
    interim = InterimTranscriptionFrame("Hel", "caller", "t")
    out = _drive(
        [
            (UserMuteStartedFrame(), up),
            (interim, down),
            (_t("Hello?"), down),
            (UserMuteStoppedFrame(), up),
        ]
    )
    texts = [f.text for f in out if isinstance(f, TranscriptionFrame)]
    assert texts == ["Hello?"]
    assert any(type(f).__name__ == "InterimTranscriptionFrame" for f in out)


def test_mute_that_never_ends_releases_on_timeout() -> None:
    hold = GreetingHold(timeout_secs=0.05)
    out: list[object] = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        out.append(frame)

    hold.push_frame = capture  # type: ignore[method-assign]
    down, up = FrameDirection.DOWNSTREAM, FrameDirection.UPSTREAM

    async def go() -> None:
        await hold.process_frame(UserMuteStartedFrame(), up)
        await hold.process_frame(_t("I know my payment is late"), down)
        await asyncio.sleep(0.15)

    asyncio.run(go())
    kinds = [type(f).__name__ for f in out]
    assert "TranscriptionFrame" in kinds
    assert "VADUserStartedSpeakingFrame" not in kinds
    replay = out[[type(f).__name__ for f in out].index("TranscriptionFrame")]
    assert replay.text == "I know my payment is late"
    assert is_hold_replay(replay)


def _run_timed(hold: GreetingHold, steps) -> list[object]:
    """Feed (frame, direction) pairs, or a float meaning sleep that long."""
    out: list[object] = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        out.append(frame)

    hold.push_frame = capture  # type: ignore[method-assign]

    async def go() -> None:
        for step in steps:
            if isinstance(step, float):
                await asyncio.sleep(step)
            else:
                await hold.process_frame(*step)

    asyncio.run(go())
    return out


def test_a_greeting_that_is_still_playing_is_not_released() -> None:
    """VS-8C1B760F1B: 2.4s to first audio, then 9.6s of disclosure.

    The old single 12s deadline ran from mute-start, so a normal opening timed
    out on every outbound call and whatever the caller said between the timeout
    and the real unmute reached a muted aggregator and was dropped. Once the
    bot is audibly speaking, the pre-speech ceiling no longer applies.
    """
    from pipecat.frames.frames import BotStartedSpeakingFrame

    down, up = FrameDirection.DOWNSTREAM, FrameDirection.UPSTREAM
    hold = GreetingHold(timeout_secs=0.05, speech_ceiling_secs=5.0, post_speech_grace_secs=5.0)
    out = _run_timed(
        hold,
        [
            (UserMuteStartedFrame(), up),
            (BotStartedSpeakingFrame(), up),
            0.15,  # three pre-speech ceilings, disclosure still playing
            (_t("Hello? Who is this?"), down),
            (UserMuteStoppedFrame(), up),
        ],
    )
    replays = [f for f in out if isinstance(f, TranscriptionFrame)]
    assert len(replays) == 1 and is_hold_replay(replays[0])
    assert replays[0].text == "Hello? Who is this?"


def test_a_lost_unmute_after_the_greeting_releases_on_the_short_grace() -> None:
    from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame

    down, up = FrameDirection.DOWNSTREAM, FrameDirection.UPSTREAM
    hold = GreetingHold(timeout_secs=5.0, speech_ceiling_secs=5.0, post_speech_grace_secs=0.05)
    out = _run_timed(
        hold,
        [
            (UserMuteStartedFrame(), up),
            (BotStartedSpeakingFrame(), up),
            (_t("I know my payment is late"), down),
            (BotStoppedSpeakingFrame(), up),
            0.15,  # no UserMuteStoppedFrame ever arrives
        ],
    )
    replays = [f for f in out if isinstance(f, TranscriptionFrame)]
    assert len(replays) == 1 and is_hold_replay(replays[0])


def test_speaking_frames_outside_the_hold_pass_straight_through() -> None:
    from pipecat.frames.frames import BotStartedSpeakingFrame

    up = FrameDirection.UPSTREAM
    frame = BotStartedSpeakingFrame()
    out = _drive([(frame, up)])
    assert out == [frame]


def test_an_outbound_pickup_before_the_greeting_is_not_replayed() -> None:
    """VS-58097BA530: the pickup ("No.") replayed after the greeting read as an answer."""
    from pipecat.frames.frames import BotStartedSpeakingFrame

    down, up = FrameDirection.DOWNSTREAM, FrameDirection.UPSTREAM
    hold = GreetingHold(timeout_secs=0.0, drop_before_greeting=True)
    out: list[object] = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        out.append(frame)

    hold.push_frame = capture  # type: ignore[method-assign]

    async def go() -> None:
        for frame, direction in [
            (UserMuteStartedFrame(), up),
            (_t("No."), down),  # the callee answering the phone
            (BotStartedSpeakingFrame(), up),
            (_t("Yes, speaking."), down),  # over the greeting: kept
            (UserMuteStoppedFrame(), up),
        ]:
            await hold.process_frame(frame, direction)

    asyncio.run(go())
    replays = [f for f in out if isinstance(f, TranscriptionFrame) and is_hold_replay(f)]
    assert [f.text for f in replays] == ["Yes, speaking."]
