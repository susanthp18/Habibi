"""The dead-air watchdog interrupted a caller who was mid-sentence.

Session VS-EE7F739E11, first turn of the call::

    12:22:55.251  User STARTED speaking
    12:23:04.199  Dead air - silent=8.9s - no idle timer was armed
    12:23:04.200  User idle - strike=1 - step=nudge
    12:23:04.743  User STOPPED speaking
    12:23:05.093  TTS "Are you still there?"

The caller talked for nine and a half seconds and was asked whether they were
still there, half a second before they finished. ``silent_for()`` measured from
``_last_audio``, which is stamped once when a turn starts and again when it
ends — so for the whole utterance in between it reported growing silence.
Pipecat's own idle controller guards this with a ``_user_turn_in_progress``
flag; this observer had no equivalent.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("pipecat.frames.frames")

from pipecat.frames.frames import (  # noqa: E402
    BotStoppedSpeakingFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)

from voice.bot_turn_state import BotTurnStateObserver  # noqa: E402


class _Processed:
    def __init__(self, frame) -> None:
        self.frame = frame


def _feed(observer: BotTurnStateObserver, *frames) -> None:
    async def _run() -> None:
        for f in frames:
            await observer.on_push_frame(_Processed(f))

    asyncio.run(_run())


def test_a_talking_caller_is_never_silence() -> None:
    """The regression, exactly: mid-utterance must read as 0s of silence."""
    obs = BotTurnStateObserver()
    _feed(obs, BotStoppedSpeakingFrame(), UserStartedSpeakingFrame())

    # Nine seconds into the caller's turn, with no frames in between —
    # which is precisely what the pipeline emits while someone talks.
    obs._last_audio -= 9.0
    assert obs.silent_for() == 0.0


def test_silence_resumes_once_the_caller_stops() -> None:
    obs = BotTurnStateObserver()
    _feed(obs, UserStartedSpeakingFrame(), UserStoppedSpeakingFrame())
    obs._last_audio -= 9.0
    assert obs.silent_for() == pytest.approx(9.0, abs=0.5)


def test_the_bot_finishing_still_starts_the_clock() -> None:
    """The case the watchdog exists for must keep working."""
    obs = BotTurnStateObserver()
    _feed(obs, BotStoppedSpeakingFrame())
    obs._last_audio -= 9.0
    assert obs.silent_for() == pytest.approx(9.0, abs=0.5)


def test_a_barge_in_does_not_latch_silence() -> None:
    """Interruption order is UserStarted -> BotStopped -> UserStopped.

    The BotStoppedSpeakingFrame lands while the caller is still talking; it
    must not re-open the silence clock underneath them.
    """
    obs = BotTurnStateObserver()
    _feed(obs, UserStartedSpeakingFrame(), BotStoppedSpeakingFrame())
    obs._last_audio -= 9.0
    assert obs.silent_for() == 0.0

    _feed(obs, UserStoppedSpeakingFrame())
    obs._last_audio -= 9.0
    assert obs.silent_for() > 0.0


def test_a_stuck_speaking_flag_cannot_disable_the_watchdog() -> None:
    """A dropped UserStoppedSpeakingFrame must not mute the watchdog for good.

    Silencing the thing that catches unbounded silence is the one failure this
    module cannot afford.
    """
    from voice.bot_turn_state import _MAX_USER_TURN_SECONDS

    obs = BotTurnStateObserver()
    _feed(obs, UserStartedSpeakingFrame())
    obs._user_speaking_since -= _MAX_USER_TURN_SECONDS + 5.0
    obs._last_audio -= _MAX_USER_TURN_SECONDS + 5.0
    assert obs.silent_for() > 0.0


def test_a_long_but_real_utterance_is_still_respected() -> None:
    """Someone reading out a reference number is talking, not idle."""
    obs = BotTurnStateObserver()
    _feed(obs, UserStartedSpeakingFrame())
    obs._user_speaking_since -= 30.0
    obs._last_audio -= 30.0
    assert obs.silent_for() == 0.0


def test_a_call_that_has_not_begun_is_not_quiet() -> None:
    assert BotTurnStateObserver().silent_for() == 0.0
