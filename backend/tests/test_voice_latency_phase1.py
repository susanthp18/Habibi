"""Phase-1 latency defects from the five-reviewer audit in ``latency_review/``.

Each test pins one defect that was a real code fault rather than a tuning
choice, so none of them needs a measured baseline to be meaningful.
"""

from __future__ import annotations

import asyncio

import pytest
from pipecat.frames.frames import TranscriptionFrame
from pipecat.turns.types import ProcessFrameResult

from agent_core.tuning import default_tuning
from voice.greeting_hold import (
    build_greeting_replay_turn_start_strategy,
    mark_hold_replay,
)
from voice.tuning_apply import build_user_turn_strategies


def _tuning(**interaction):
    t = default_tuning()
    t["interaction"].update(interaction)
    return t


def _trigger(strategy):
    """Run process_frame and report whether the turn was started."""
    started: list[bool] = []
    strategy.add_event_handler("on_user_turn_started", lambda *a, **k: started.append(True))
    return started


# ------------------------------------------- greeting-hold replay start


def _replay_strategy(barge: str):
    strategies = build_user_turn_strategies(_tuning(barge_in=barge)).start
    replay = next(
        (s for s in strategies if type(s).__name__ == "GreetingReplayUserTurnStartStrategy"),
        None,
    )
    assert replay is not None, f"greeting replay start missing in barge_in={barge!r}"
    return replay


@pytest.mark.parametrize("barge", ["on", "locked", "min_words"])
def test_greeting_replay_opens_a_user_turn(barge):
    """A replayed barge-over-greeting transcript must open a turn.

    GreetingHold used to wrap the replay in synthetic VAD start/stop. Smart
    Turn analysed an empty buffer, returned INCOMPLETE, and the turn waited
    out the 5s aggregator backstop. The marker opens the turn the same way
    the DTMF prefix does; ordinary speech must not.
    """
    replay = _replay_strategy(barge)
    started = _trigger(replay)
    frame = mark_hold_replay(TranscriptionFrame(text="Hello? Who is this?", user_id="", timestamp=""))
    result = asyncio.run(replay.process_frame(frame))
    assert started == [True], f"greeting replay never opened in barge_in={barge!r}"
    assert result == ProcessFrameResult.STOP
    assert replay._enable_interruptions is True


def test_greeting_replay_strategy_ignores_ordinary_speech():
    replay = build_greeting_replay_turn_start_strategy()
    started = _trigger(replay)
    frame = TranscriptionFrame(text="Hello? Who is this?", user_id="", timestamp="")
    result = asyncio.run(replay.process_frame(frame))
    assert started == [], "an unmarked speech transcript must not open a turn"
    assert result == ProcessFrameResult.CONTINUE

# --------------------------------------------------------------- 3.5 DTMF flush


def test_dtmf_aggregator_flushes_after_one_second():
    """Without ``#`` the library default slept 2s after the last digit of a last-4.

    ``#`` still flushes immediately. Longer account strings still use ``#``,
    which the product already asks for. Do not add a blanket transcription
    start strategy — VS-39B35AC484.
    """
    from voice.ivr import build_dtmf_aggregator

    agg = build_dtmf_aggregator()
    if agg is None:
        pytest.skip("DTMFAggregator not available in this Pipecat build")
    assert agg._idle_timeout == 1.0
