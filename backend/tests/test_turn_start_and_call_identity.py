"""Interruption policy, and the carrier call id that was never written.

Two unrelated defects, both invisible from the outside:

* ``barge_in="on"`` left ``UserTurnStrategies.start`` unset, so Pipecat filled
  in its default — ``[VADUserTurnStartStrategy, TranscriptionUserTurnStartStrategy]``.
  Two independent interrupt triggers, and the transcription one fires on audio
  that is already hundreds of milliseconds old. On VS-39B35AC484 the bot was cut
  off three times mid-reply.

* ``voice_sessions.provider_call_id`` and its unique index have existed since
  ``sql/12_crosscutting.sql``; ``persist.start_voice_call`` and
  ``crm_sink.bind_session_start`` both took the argument. Nothing ever passed
  it, so the column was NULL on every row and no call could be traced from the
  carrier's log back to a customer.
"""

from __future__ import annotations

import inspect

import pytest

pytest.importorskip("pipecat.turns.user_turn_strategies")

from agent_core.tuning import normalize_tuning  # noqa: E402
from voice.tuning_apply import build_user_turn_strategies  # noqa: E402


def _tuning(barge: str, **interaction) -> dict:
    t = normalize_tuning({})
    t["interaction"]["barge_in"] = barge
    t["interaction"].update(interaction)
    return t


def _names(strategies) -> list[str]:
    return [type(s).__name__ for s in strategies]


#: A plain sentence -- no keypad prefix, no replay marker.
_ORDINARY_SPEECH = "I will pay on Friday"


def _opens_a_turn_on(strategy, text: str) -> bool:
    """Whether this strategy would open a user turn for that transcript."""
    import asyncio

    from pipecat.frames.frames import TranscriptionFrame

    fired: list[bool] = []
    strategy.add_event_handler("on_user_turn_started", lambda *a, **k: fired.append(True))
    asyncio.run(
        strategy.process_frame(TranscriptionFrame(text=text, user_id="", timestamp=""))
    )
    return bool(fired)


# --- barge_in="on": VAD may interrupt, a stale transcript may not ------------


def test_on_states_its_start_strategy_instead_of_inheriting_the_default() -> None:
    """The regression. An unset ``start`` is not the same as a chosen one."""
    s = build_user_turn_strategies(_tuning("on"))
    assert "VADUserTurnStartStrategy" in _names(s.start)
    assert "TranscriptionUserTurnStartStrategy" not in _names(s.start)


def test_on_does_not_let_transcripts_start_a_turn() -> None:
    """A transcript describes the past; interrupting on it interrupts on the past."""
    s = build_user_turn_strategies(_tuning("on"))
    assert "TranscriptionUserTurnStartStrategy" not in _names(s.start)


@pytest.mark.parametrize("mode", ["on", "locked", "min_words"])
def test_keypad_start_cannot_be_opened_by_speech(mode: str) -> None:
    """The keypad strategy is the ONE narrow re-admission of a transcript-driven
    start, and the VS-39B35AC484 lesson survives it only because it matches the
    DTMF prefix and nothing else. If that scoping ever widens, this fails."""
    import asyncio

    from pipecat.frames.frames import TranscriptionFrame

    from voice.ivr import DTMF_TRANSCRIPT_PREFIX

    s = build_user_turn_strategies(_tuning(mode))
    keypad = next(x for x in s.start if type(x).__name__ == "KeypadUserTurnStartStrategy")

    started: list[str] = []
    keypad.add_event_handler("on_user_turn_started", lambda *a, **k: started.append("x"))

    speech = TranscriptionFrame(text="I will pay on Friday", user_id="", timestamp="")
    asyncio.run(keypad.process_frame(speech))
    assert started == [], f"speech opened a keypad turn in barge_in={mode!r}"

    digits = TranscriptionFrame(text=f"{DTMF_TRANSCRIPT_PREFIX}9", user_id="", timestamp="")
    asyncio.run(keypad.process_frame(digits))
    assert started == ["x"], f"keypad turn never opened in barge_in={mode!r}"


def test_on_keeps_smart_turn_v3_for_end_of_turn() -> None:
    """Fixing interruption must not cost end-of-turn quality."""
    s = build_user_turn_strategies(_tuning("on"))
    assert _names(s.stop) == ["TurnAnalyzerUserTurnStopStrategy"]


def test_on_still_allows_interruptions() -> None:
    """VAD-only is a narrower trigger, not a disabled one — that is ``locked``.

    Reads the private attribute deliberately: Pipecat exposes no property for
    it, and asserting on a ``getattr(..., default)`` would pass whether the flag
    existed or not.
    """
    s = build_user_turn_strategies(_tuning("on"))
    assert all(x._enable_interruptions is True for x in s.start)


# --- locked: unchanged ------------------------------------------------------


def test_locked_never_interrupts() -> None:
    s = build_user_turn_strategies(_tuning("locked"))
    assert "VADUserTurnStartStrategy" in _names(s.start)
    assert "TranscriptionUserTurnStartStrategy" not in _names(s.start)
    # Greeting replay starts after unmute, when the disclosure is already
    # complete — that start may barge. The live-speech starts must not.
    live = [x for x in s.start if type(x).__name__ != "GreetingReplayUserTurnStartStrategy"]
    assert live and all(x._enable_interruptions is False for x in live)


# --- min_words: a matched pair, not an oversight -----------------------------


def test_min_words_pairs_a_transcript_start_with_a_transcript_stop() -> None:
    """Guards against "fixing" this to share the Smart Turn stop strategy.

    ``TurnAnalyzerUserTurnStopStrategy`` ends a turn on
    ``VADUserStoppedSpeakingFrame``. A ``MinWords`` start fires off a transcript,
    which arrives *after* that VAD stop — so the pairing would wait for an event
    that already happened and the turn would never end.
    """
    s = build_user_turn_strategies(_tuning("min_words", min_words=3))
    assert "MinWordsUserTurnStartStrategy" in _names(s.start)
    assert _names(s.stop) == ["SpeechTimeoutUserTurnStopStrategy"]


def test_min_words_carries_the_configured_threshold() -> None:
    s = build_user_turn_strategies(_tuning("min_words", min_words=5))
    min_words = next(
        x for x in s.start if type(x).__name__ == "MinWordsUserTurnStartStrategy"
    )
    assert getattr(min_words, "_min_words") == 5


def test_every_mode_supplies_both_halves() -> None:
    """No mode may leave a half to Pipecat's default again."""
    for mode in ("on", "locked", "min_words"):
        s = build_user_turn_strategies(_tuning(mode))
        assert s.start, mode
        assert s.stop, mode


# --- the carrier call id ----------------------------------------------------


def test_bind_session_start_forwards_the_provider_call_id() -> None:
    from voice import crm_sink

    sig = inspect.signature(crm_sink.bind_session_start)
    assert "provider_call_id" in sig.parameters
    src = inspect.getsource(crm_sink.bind_session_start)
    assert "provider_call_id=provider_call_id" in src


def test_bind_session_start_forwards_direction() -> None:
    """An outbound dial filed as inbound inverts every answer-rate report."""
    from voice import crm_sink

    sig = inspect.signature(crm_sink.bind_session_start)
    assert sig.parameters["direction"].default == "inbound"
    assert "direction=direction" in inspect.getsource(crm_sink.bind_session_start)


def test_the_bot_actually_supplies_both() -> None:
    """The plumbing existed end to end; only this last hop was missing."""

    from tests.voice_tools_source import handlers_source

    src = handlers_source()
    assert "provider_call_id=provider_call_id" in src
    assert "direction=direction" in src


def test_the_call_session_uses_the_account_the_dial_was_reserved_for(monkeypatch) -> None:
    """Left to resolve on its own, the session picked the borrower's first
    account while a campaign had briefed and reserved against their most
    overdue one, so the bot's tools wrote to a different ledger."""
    from voice import crm_sink, persist
    from voice.session import VoiceSession

    seen: dict = {}

    def _start(**kw):
        seen.update(kw)
        return {"interactionId": "INT-T", "customerId": kw["customer_id"], "accountId": kw["account_id"]}

    monkeypatch.setattr(persist, "start_voice_call", _start)
    session = VoiceSession(session_id="VS-ACCT")
    crm_sink.bind_session_start(
        session, deployment_id=None, customer_id="CUST-T", account_id="AC-MOST-OVERDUE"
    )

    assert seen["account_id"] == "AC-MOST-OVERDUE"
    assert session.account_id == "AC-MOST-OVERDUE"

    from tests.voice_tools_source import handlers_source

    assert 'account_id=(session.extra.get("mission") or {}).get("accountId")' in handlers_source()


def test_a_sandbox_call_with_no_carrier_id_passes_none_not_empty_string() -> None:
    """The unique index is partial on NOT NULL — '' would collide across calls."""

    from tests.voice_tools_source import handlers_source

    src = handlers_source()
    assert 'str(session.extra.get("call_sid") or "").strip() or None' in src


# --- one handoff mode, reported honestly ------------------------------------


def test_transfer_mode_reports_an_invalid_setting_instead_of_hiding_it(
    monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    from voice import tools

    monkeypatch.setenv("VOICE_HANDOFF_MODE", "warn")  # the documented typo
    with caplog.at_level("ERROR"):
        assert tools._transfer_mode() == "callback_queue"
    assert any("VOICE_HANDOFF_MODE" in r.getMessage() for r in caplog.records)


def test_status_reports_the_mode_the_runtime_would_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three copies of this logic disagreed; the status endpoint used the lenient one."""
    from voice import tools, twilio_ops
    from voice.config import voice_handoff_mode

    for value in ("warm", "warm_transfer", "conference", "callback_queue"):
        monkeypatch.setenv("VOICE_HANDOFF_MODE", value)
        assert twilio_ops.handoff_mode() == voice_handoff_mode() == tools._transfer_mode()


def test_status_does_not_raise_on_a_typo(monkeypatch: pytest.MonkeyPatch) -> None:
    from voice import twilio_ops

    monkeypatch.setenv("VOICE_HANDOFF_MODE", "warn")
    assert twilio_ops.handoff_mode() == "callback_queue"


@pytest.mark.parametrize("mode", ["on", "locked"])
def test_no_start_strategy_opens_a_turn_on_ordinary_speech(mode: str) -> None:
    """The VS-39B35AC484 lesson, stated so it cannot drift.

    Habibi re-admits transcript-driven starts, but only scoped ones: keypad
    digits match the DTMF prefix, greeting replay matches the hold marker.
    Asserting the exact contents of ``start`` made this a hand-kept list that
    broke every time a scoped strategy was added. What actually matters is that
    none of them -- however many there are -- can be opened by a sentence the
    caller simply said. ``min_words`` is excluded because it is transcript-driven
    by design; that is what the mode is.
    """
    s = build_user_turn_strategies(_tuning(mode))
    assert s.start, mode
    for strategy in s.start:
        assert not _opens_a_turn_on(strategy, _ORDINARY_SPEECH), (
            f"{type(strategy).__name__} opened a turn on ordinary speech in "
            f"barge_in={mode!r} -- a transcript describes audio from hundreds of "
            "milliseconds ago, which is how the bot was cut off three times"
        )
