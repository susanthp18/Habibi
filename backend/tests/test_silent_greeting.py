"""A call that connected and never made a sound.

Session VS-18FE21E37A::

    12:39:41.962  Client connected
    12:39:42.111  Setting node: greet_disclose
    12:39:43.846  Calling function [disclose_recording] with arguments {}
    12:39:44.023  Setting node: discover_intent
    12:41:03.032  Client disconnected

No ``Generating TTS`` line anywhere. The model called the lifecycle tool and
emitted no text with it, so the greeting was never spoken; ``discover_intent``
listens rather than speaks; and the line stayed dead for 77 seconds until the
caller gave up. Two independent defects kept it that way:

* the dead-air watchdog returned 0.0s of silence whenever no audio had *ever*
  been seen, so the worst case was the one case it could not detect;
* ``disclose_recording`` wrote a compliance record asserting the caller had
  been told the call was recorded, when nothing had been said at all.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("pipecat.frames.frames")

from voice.bot_turn_state import BotTurnStateObserver  # noqa: E402


# --- silence before the first sound is still silence ------------------------


def test_a_connected_call_that_says_nothing_is_dead_air() -> None:
    """The regression. Connected, no audio, and it must be visible."""
    obs = BotTurnStateObserver()
    obs.mark_call_started()
    obs._call_started_at -= 30.0
    assert obs.silent_for() == pytest.approx(30.0, abs=0.5)


def test_an_observer_with_no_call_is_not_quiet() -> None:
    """Before a caller connects there is nothing to be silent about."""
    assert BotTurnStateObserver().silent_for() == 0.0


def test_the_first_sound_takes_over_from_the_connect_time() -> None:
    from pipecat.frames.frames import BotStoppedSpeakingFrame

    obs = BotTurnStateObserver()
    obs.mark_call_started()
    obs._call_started_at -= 60.0

    async def _run() -> None:
        await obs.on_push_frame(_Processed(BotStoppedSpeakingFrame()))

    asyncio.run(_run())
    # Measured from the bot's turn ending, not from the connect 60s ago.
    assert obs.silent_for() < 1.0


def test_a_talking_caller_still_beats_the_connect_clock() -> None:
    """The previous fix must survive this one."""
    from pipecat.frames.frames import UserStartedSpeakingFrame

    obs = BotTurnStateObserver()
    obs.mark_call_started()
    obs._call_started_at -= 60.0

    async def _run() -> None:
        await obs.on_push_frame(_Processed(UserStartedSpeakingFrame()))

    asyncio.run(_run())
    obs._last_audio -= 9.0
    assert obs.silent_for() == 0.0


class _Processed:
    def __init__(self, frame) -> None:
        self.frame = frame


# --- and the opening turn must not depend on the model saying anything ------


def test_the_bot_marks_the_call_start_when_the_client_connects() -> None:
    import inspect

    from voice import bot

    assert "bot_turn_state.mark_call_started()" in inspect.getsource(bot)


def test_disclose_recording_speaks_when_the_model_did_not() -> None:
    """A disclosure record must not outrun the disclosure."""
    import inspect

    from voice import tools

    src = inspect.getsource(tools)
    assert "_FALLBACK_GREETING" in src
    assert "spoke_this_response is not None and not spoke_this_response()" in src
    # Spoken through the same handle pause_for_caller uses; FlowManager has no
    # public pipeline task.
    assert 'getattr(flow_manager, "worker", None)' in src


def test_the_fallback_greeting_carries_the_disclosure_and_a_question() -> None:
    """It replaces the whole opening turn, so it has to do the whole job."""
    import re

    from voice import tools

    src = inspect.getsource(tools) if False else __import__("inspect").getsource(tools)
    match = re.search(r"_FALLBACK_GREETING = \(\s*(.*?)\s*\)\n", src, re.S)
    assert match, "fallback greeting not found"
    line = " ".join(re.findall(r'"([^"]*)"', match.group(1)))
    assert "recorded for quality and compliance" in line, "must disclose"
    assert line.rstrip().endswith("?"), "must hand the turn back to the caller"
