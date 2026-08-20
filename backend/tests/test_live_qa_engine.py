"""Live QA — deterministic FPC, never an LLM on the barge path.

Almost everything worth testing is a restraint: hours, third-party leak,
identity-before-dues, WhatsApp not treated as a call, hardship not punished
for a missing PTP close, and the engine never raising.
"""

from __future__ import annotations

from agent_core.live_qa import config
from agent_core.live_qa.checks import (
    ACTION_BARGE,
    ACTION_INBOX,
    ACTION_NONE,
    VERDICT_CRITICAL,
    TurnFacts,
    evaluate_turn,
    worst_action,
)
from agent_core.live_qa.engine import evaluate_live_qa
from agent_core.live_qa.scorecard import NEUTRAL_SCORE, _entry_for


def _facts(**overrides) -> TurnFacts:
    base = dict(
        channel="voice",
        bot_text="",
        customer_text="",
        turn_index=2,
        elapsed_seconds=30.0,
        identity_verified=True,
        third_party=False,
        now_hour=11,
        guardrail_flags=(),
    )
    base.update(overrides)
    return TurnFacts(**base)


def test_default_barge_mode_is_shadow(monkeypatch) -> None:
    monkeypatch.delenv("LIVE_QA_BARGE_MODE", raising=False)
    assert config.mode() == config.MODE_SHADOW


def test_unrecognised_mode_degrades_to_shadow(monkeypatch) -> None:
    monkeypatch.setenv("LIVE_QA_BARGE_MODE", "lvie")
    assert config.mode() == config.MODE_SHADOW


def test_voice_after_hours_is_a_critical_barge() -> None:
    findings = evaluate_turn(_facts(now_hour=19, bot_text="Just checking in."))
    assert any(f.check_id == "hours-breach" for f in findings)
    assert worst_action(findings, channel="voice") == ACTION_BARGE


def test_whatsapp_after_hours_is_not_a_calling_hours_breach() -> None:
    findings = evaluate_turn(
        _facts(channel="whatsapp", now_hour=21, bot_text="Your EMI is overdue.")
    )
    assert all(f.check_id != "hours-breach" for f in findings)


def test_identity_before_dues_barges() -> None:
    findings = evaluate_turn(
        _facts(identity_verified=False, bot_text="Your outstanding is ₹12,400.")
    )
    assert any(f.check_id == "identity-before-verify" for f in findings)
    assert worst_action(findings, channel="voice") == ACTION_BARGE


def test_verified_dues_do_not_fail_identity() -> None:
    findings = evaluate_turn(
        _facts(identity_verified=True, bot_text="Your outstanding is ₹12,400.")
    )
    assert all(f.check_id != "identity-before-verify" for f in findings)


def test_third_party_with_amount_barges() -> None:
    findings = evaluate_turn(
        _facts(third_party=True, bot_text="The EMI is ₹8,200 this month.")
    )
    assert any(f.check_id == "third-party-leak" for f in findings)


def test_third_party_polite_goodbye_does_not_leak() -> None:
    findings = evaluate_turn(
        _facts(
            third_party=True,
            bot_text="I can only speak with the account holder. Please ask them to call us.",
        )
    )
    assert all(f.check_id != "third-party-leak" for f in findings)


def test_opt_out_then_payment_push_fails() -> None:
    findings = evaluate_turn(
        _facts(
            customer_text="Please stop calling me",
            bot_text="You still need to pay now. The outstanding is due.",
        )
    )
    assert any(f.check_id == "opt-out-ignored" for f in findings)


def test_authority_cap_flag_promotes_to_barge() -> None:
    findings = evaluate_turn(
        _facts(guardrail_flags=("authority-cap-exceeded",), bot_text="I can waive ₹2000.")
    )
    assert any(f.check_id == "authority-cap-exceeded" for f in findings)
    assert worst_action(findings, channel="voice") == ACTION_BARGE


def test_whatsapp_critical_becomes_inbox_not_barge() -> None:
    findings = evaluate_turn(
        _facts(
            channel="whatsapp",
            identity_verified=False,
            bot_text="Your outstanding is ₹12,400.",
        )
    )
    assert worst_action(findings, channel="whatsapp") == ACTION_INBOX


def test_clean_turn_recommends_nothing() -> None:
    findings = evaluate_turn(_facts(bot_text="Thank you, I have noted that."))
    assert findings == ()
    assert worst_action(findings, channel="voice") == ACTION_NONE


def test_hardship_hold_does_not_zero_res_close() -> None:
    cell = _entry_for(
        cid="res-close",
        flags=[],
        disclosures=set(),
        verified=True,
        hold_kinds={"hardship"},
        ptp_captured=False,
        ptp_written=False,
        upsell_presented=False,
        offer_suppressed=False,
    )
    assert cell["score"] == NEUTRAL_SCORE
    assert str(cell["note"] or "").startswith("[live]")


def test_ptp_without_written_confirm_fails_res_close() -> None:
    cell = _entry_for(
        cid="res-close",
        flags=[],
        disclosures=set(),
        verified=True,
        hold_kinds=set(),
        ptp_captured=True,
        ptp_written=False,
        upsell_presented=False,
        offer_suppressed=False,
    )
    assert cell["score"] == 0.0


def test_evaluate_live_qa_never_raises(monkeypatch) -> None:
    monkeypatch.setattr("agent_core.live_qa.decisions.record", lambda **_k: None)
    result = evaluate_live_qa(_facts(bot_text="ok"), interaction_id=None)
    assert result.verdict in {"pass", "fail_soft", "fail_critical"}


def test_shadow_mode_does_not_auto_barge(monkeypatch) -> None:
    monkeypatch.setattr("agent_core.live_qa.decisions.record", lambda **_k: "LQ-TEST")
    result = evaluate_live_qa(
        _facts(now_hour=20, bot_text="hello"),
        force_mode="shadow",
    )
    assert result.recommended_action == ACTION_BARGE
    assert result.auto_barge is False
    assert result.verdict == VERDICT_CRITICAL


def test_live_mode_auto_barges_hours(monkeypatch) -> None:
    monkeypatch.setattr("agent_core.live_qa.decisions.record", lambda **_k: "LQ-TEST")
    result = evaluate_live_qa(
        _facts(now_hour=20, bot_text="hello"),
        force_mode="live",
    )
    assert result.auto_barge is True


def test_shadow_evaluate_does_not_call_twilio(monkeypatch) -> None:
    monkeypatch.setattr("agent_core.live_qa.decisions.record", lambda **_k: "LQ-TEST")

    def boom(*_a, **_k):
        raise AssertionError("evaluate_live_qa must not dial Twilio")

    monkeypatch.setattr("voice.twilio_ops.warm_transfer_to_supervisor", boom)
    result = evaluate_live_qa(
        _facts(now_hour=20, bot_text="hello"),
        force_mode="shadow",
    )
    assert result.auto_barge is False
    assert result.recommended_action == ACTION_BARGE
