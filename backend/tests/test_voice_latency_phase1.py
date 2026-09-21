"""Phase-1 latency defects from the five-reviewer audit in ``latency_review/``.

Each test pins one defect that was a real code fault rather than a tuning
choice, so none of them needs a measured baseline to be meaningful.
"""

from __future__ import annotations

import asyncio

import pytest
from pipecat.frames.frames import TranscriptionFrame
from pipecat.turns.types import ProcessFrameResult

from agent_core.tuning import default_tuning, normalize_tuning
from voice.greeting_hold import (
    build_greeting_replay_turn_start_strategy,
    mark_hold_replay,
)
from voice.ivr import DTMF_TRANSCRIPT_PREFIX, build_keypad_turn_start_strategy
from voice.natural import build_voice_system_prompt
from voice.tuning_apply import build_user_turn_strategies, user_turn_stop_timeout


def _tuning(**interaction):
    t = default_tuning()
    t["interaction"].update(interaction)
    return t


# --------------------------------------------------------------- L-001 keypad


def _trigger(strategy):
    """Run process_frame and report whether the turn was started."""
    started: list[bool] = []
    strategy.add_event_handler("on_user_turn_started", lambda *a, **k: started.append(True))
    return started


@pytest.mark.parametrize("barge", ["on", "locked", "min_words"])
def test_keypad_transcript_opens_a_user_turn(barge):
    """A digits-only entry must open a turn in every barge mode.

    Without this the caller hears silence until the 12s idle ladder fires: the
    DTMF aggregator pushes a bare TranscriptionFrame, no VAD event exists for a
    keypress, and a VAD-only start strategy never opens the turn.
    """
    strategies = build_user_turn_strategies(_tuning(barge_in=barge))
    keypad = strategies.start[0]
    started = _trigger(keypad)

    frame = TranscriptionFrame(text=f"{DTMF_TRANSCRIPT_PREFIX}1234", user_id="", timestamp="")
    result = asyncio.run(keypad.process_frame(frame))

    assert started == [True], f"keypad turn never opened in barge_in={barge!r}"
    assert result == ProcessFrameResult.STOP


def test_keypad_strategy_ignores_ordinary_speech():
    """The blanket transcription start strategy was removed for a measured
    reason (VS-39B35AC484, three bot cut-offs). Keypad must not reintroduce it."""
    keypad = build_keypad_turn_start_strategy()
    started = _trigger(keypad)

    frame = TranscriptionFrame(text="I already paid on Tuesday", user_id="", timestamp="")
    result = asyncio.run(keypad.process_frame(frame))

    assert started == [], "a speech transcript must not open a turn"
    assert result == ProcessFrameResult.CONTINUE


def test_keypad_does_not_interrupt_in_locked_mode():
    """``locked`` is the compliance preset: the disclosure stays uninterruptible."""
    locked = build_user_turn_strategies(_tuning(barge_in="locked")).start[0]
    on = build_user_turn_strategies(_tuning(barge_in="on")).start[0]
    assert locked._enable_interruptions is False
    assert on._enable_interruptions is True


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


# ------------------------------------------------- L-003 locked-mode analyzer


def test_locked_mode_keeps_its_own_turn_tuning():
    """An omitted ``stop`` list makes Pipecat build a second analyzer at library
    defaults, so the strictest preset silently ignored its card's ``turn`` block
    and paid an extra ONNX build during setup."""
    t = default_tuning()
    t["interaction"]["barge_in"] = "locked"
    t["turn"]["stop_secs"] = 1.5

    strategies = build_user_turn_strategies(t)

    assert strategies.stop, "locked mode must state its stop strategy"
    analyzer = strategies.stop[0]._turn_analyzer
    assert analyzer.params.stop_secs == pytest.approx(1.5), (
        "locked mode is running Pipecat's default analyzer, not the card's"
    )


# ------------------------------------------------- L-014 tunable backstop


def test_stop_timeout_is_read_from_tuning_and_clamped():
    assert user_turn_stop_timeout(default_tuning()) == pytest.approx(5.0)

    t = default_tuning()
    t["turn"]["stop_timeout_secs"] = 3.0
    assert user_turn_stop_timeout(t) == pytest.approx(3.0)

    # Below the Smart Turn ceiling the backstop stops being a backstop.
    t["turn"]["stop_timeout_secs"] = 0.1
    assert normalize_tuning(t)["turn"]["stop_timeout_secs"] == pytest.approx(2.0)


# --------------------------------------------------- prompt prefix stability


def test_system_prompt_prefix_is_stable_across_the_minute_boundary():
    """Everything above the ``## Time`` block must be byte-identical between
    calls, or the provider prefix cache can never match past it."""
    from agent_core import clock

    real = clock.describe_now
    try:
        clock.describe_now = lambda: "Asia/Kolkata, Monday 14:29 (+05:30)"
        first = build_voice_system_prompt("Collect the overdue EMI.")
        clock.describe_now = lambda: "Asia/Kolkata, Monday 14:30 (+05:30)"
        second = build_voice_system_prompt("Collect the overdue EMI.")
    finally:
        clock.describe_now = real

    assert first != second, "the time block is meant to vary; the test is wrong"

    head_first = first.split("## Time")[0]
    head_second = second.split("## Time")[0]
    assert head_first == head_second

    # The overlay is the bulk of the prompt and must sit inside the stable half.
    assert "## Voice conversation rules" in head_first
    assert first.index("## Voice conversation rules") < first.index("## Time")


# --------------------------------------------- retrieval-log flush is off-path


def test_retrieval_log_flush_leaves_the_retrieval_thread():
    """``record_retrieval_log`` runs on the worker thread doing the KB
    retrieval, inside the window the turn is waiting on. Draining the buffer
    there meant one turn in N paid a synchronous executemany INSERT."""
    import threading

    import kb_retrieve

    caller = threading.current_thread().name
    flushed = threading.Event()
    seen: list[str] = []

    def fake_write(rows):
        seen.append(threading.current_thread().name)
        flushed.set()

    real_write = kb_retrieve._write_retrieval_logs
    real_enabled = kb_retrieve._log_buffering_enabled
    try:
        kb_retrieve._write_retrieval_logs = fake_write
        kb_retrieve._log_buffering_enabled = lambda: True
        with kb_retrieve._log_lock:
            kb_retrieve._log_buffer.clear()
            kb_retrieve._log_flush_pending = False
        kb_retrieve._log_last_flush = 0.0  # force "due"

        kb_retrieve.record_retrieval_log({"id": "r1"}, defer=True)
        assert flushed.wait(timeout=5), "flush never ran"
    finally:
        kb_retrieve._write_retrieval_logs = real_write
        kb_retrieve._log_buffering_enabled = real_enabled
        with kb_retrieve._log_lock:
            kb_retrieve._log_buffer.clear()

    assert seen and seen[0] != caller, "the flush still ran on the caller's thread"
    assert seen[0].startswith("kb-retrieval-log")


def test_retrieval_log_buffer_is_bounded():
    """The flush is off-thread now, so a dead database backs rows up here
    instead of blocking the caller. These are analytics: drop, do not grow."""
    import kb_retrieve

    real_enabled = kb_retrieve._log_buffering_enabled
    try:
        kb_retrieve._log_buffering_enabled = lambda: True
        with kb_retrieve._log_lock:
            kb_retrieve._log_buffer.clear()
            kb_retrieve._log_buffer.extend(
                {"id": str(i)} for i in range(kb_retrieve._LOG_BUFFER_MAX_ROWS)
            )
            kb_retrieve._log_flush_pending = True  # suppress the real flush
        kb_retrieve.record_retrieval_log({"id": "newest"}, defer=True)

        with kb_retrieve._log_lock:
            assert len(kb_retrieve._log_buffer) == kb_retrieve._LOG_BUFFER_MAX_ROWS
            assert kb_retrieve._log_buffer[-1]["id"] == "newest"
            assert kb_retrieve._log_buffer[0]["id"] == "1", "dropped the wrong end"
    finally:
        kb_retrieve._log_buffering_enabled = real_enabled
        with kb_retrieve._log_lock:
            kb_retrieve._log_buffer.clear()
            kb_retrieve._log_flush_pending = False


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
