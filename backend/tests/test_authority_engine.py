"""Live authority matrix — policy-as-code, not LLM generosity.

The matrix is a veto list plus a rupee ceiling. Almost everything worth
testing is a restraint: a case where the right answer is escalate, or a cap
smaller than what the caller asked for. A recommender that only ever waives
looks like it works until the first out-of-policy quote hits a recording.
"""

from __future__ import annotations


from agent_core.authority import config
from agent_core.authority.engine import recommend_authority
from agent_core.authority.features import AccountAuthority
from agent_core.authority.matrix import (
    ASKED_ABOVE_CAP,
    BOUNCE_FORBIDDEN,
    DPD_TOO_HIGH,
    NOTHING_TO_WAIVE,
    PRIOR_GOODWILL,
    RESTRUCTURE_FORBIDDEN,
    SETTLEMENT_FORBIDDEN,
    TENURE_TOO_SHORT,
    UNKNOWN_FEE,
    VERDICT_AUTO,
    VERDICT_CAP,
    VERDICT_ESCALATE,
    decide,
)


def make_features(**overrides) -> AccountAuthority:
    base = dict(
        customer_id="probe-cust",
        tenant_id="hdfc.retail",
        account_id="probe-acct",
        dpd=12,
        outstanding=25_000.0,
        product_type="Personal Loan",
        tenure_months=18,
        posted_late_fee=800.0,
        goodwill_12m=0.0,
        goodwill_count_12m=0,
        holds=(),
        identity_verified=True,
    )
    base.update(overrides)
    return AccountAuthority(**base)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_default_mode_is_shadow(monkeypatch) -> None:
    monkeypatch.delenv("AUTHORITY_MODE", raising=False)
    assert config.mode() == config.MODE_SHADOW


def test_an_unrecognised_mode_degrades_to_shadow_not_off(monkeypatch) -> None:
    monkeypatch.setenv("AUTHORITY_MODE", "lvie")
    assert config.mode() == config.MODE_SHADOW


# ---------------------------------------------------------------------------
# The matrix
# ---------------------------------------------------------------------------


def test_asked_inside_the_cap_is_auto_approve() -> None:
    d = decide(make_features(), fee_type="late_fee", asked_amount=400)
    assert d.verdict == VERDICT_AUTO
    assert d.approved_amount == 400
    assert d.cap_amount == 500


def test_no_asked_amount_returns_the_ceiling() -> None:
    d = decide(make_features(), fee_type="late_fee", asked_amount=None)
    assert d.verdict == VERDICT_CAP
    assert d.approved_amount == 500
    assert d.cap_amount == 500


def test_asked_above_the_cap_is_still_the_cap_not_a_larger_quote() -> None:
    d = decide(make_features(), fee_type="late_fee", asked_amount=2000)
    assert d.verdict == VERDICT_CAP
    assert d.approved_amount == 500
    assert d.reason == ASKED_ABOVE_CAP


def test_approved_amount_is_always_inside_the_cap_or_none() -> None:
    features = make_features()
    for asked in (None, 0, 1, 250, 500, 501, 9999, -50):
        d = decide(features, fee_type="late_fee", asked_amount=asked)
        if d.approved_amount is None:
            assert d.verdict == VERDICT_ESCALATE
        else:
            assert d.cap_amount is not None
            assert d.approved_amount <= d.cap_amount
            assert d.approved_amount <= 500


def test_mid_bucket_uses_the_tighter_cap() -> None:
    d = decide(make_features(dpd=45), fee_type="late_fee", asked_amount=400)
    assert d.verdict == VERDICT_CAP
    assert d.approved_amount == 250
    assert d.cap_amount == 250


def test_posted_fee_clamps_the_cap() -> None:
    d = decide(make_features(posted_late_fee=200), fee_type="late_fee", asked_amount=None)
    assert d.approved_amount == 200
    assert d.cap_amount == 200


def test_settlement_always_escalates_with_no_figure() -> None:
    d = decide(make_features(), fee_type="settlement", asked_amount=0.4)
    assert d.verdict == VERDICT_ESCALATE
    assert d.approved_amount is None
    assert d.reason == SETTLEMENT_FORBIDDEN


def test_restructuring_always_escalates() -> None:
    d = decide(make_features(), fee_type="restructuring", asked_amount=None)
    assert d.verdict == VERDICT_ESCALATE
    assert d.reason == RESTRUCTURE_FORBIDDEN


def test_bounce_charge_always_escalates() -> None:
    d = decide(make_features(), fee_type="bounce_charge", asked_amount=500)
    assert d.verdict == VERDICT_ESCALATE
    assert d.reason == BOUNCE_FORBIDDEN
    assert d.approved_amount is None


def test_unknown_fee_type_escalates() -> None:
    d = decide(make_features(), fee_type="cashback", asked_amount=100)
    assert d.verdict == VERDICT_ESCALATE
    assert d.reason == UNKNOWN_FEE


def test_prior_goodwill_is_one_time() -> None:
    d = decide(make_features(goodwill_count_12m=1), fee_type="late_fee", asked_amount=200)
    assert d.verdict == VERDICT_ESCALATE
    assert d.reason == PRIOR_GOODWILL
    assert d.approved_amount is None


def test_high_dpd_escalates() -> None:
    d = decide(make_features(dpd=61), fee_type="late_fee", asked_amount=200)
    assert d.verdict == VERDICT_ESCALATE
    assert d.reason == DPD_TOO_HIGH


def test_unknown_tenure_is_not_treated_as_new() -> None:
    d = decide(make_features(tenure_months=None), fee_type="late_fee", asked_amount=200)
    assert d.verdict == VERDICT_AUTO
    assert d.approved_amount == 200


def test_short_known_tenure_escalates() -> None:
    d = decide(make_features(tenure_months=3), fee_type="late_fee", asked_amount=200)
    assert d.verdict == VERDICT_ESCALATE
    assert d.reason == TENURE_TOO_SHORT


def test_a_dispute_hold_does_not_veto_goodwill() -> None:
    d = decide(make_features(holds=("dispute",)), fee_type="late_fee", asked_amount=200)
    assert d.verdict == VERDICT_AUTO
    assert d.approved_amount == 200


def test_a_hardship_hold_does_veto() -> None:
    d = decide(make_features(holds=("hardship",)), fee_type="late_fee", asked_amount=200)
    assert d.verdict == VERDICT_ESCALATE
    assert d.reason == "hold:hardship"
    assert d.approved_amount is None


def test_nothing_to_waive_when_the_posted_fee_is_zero() -> None:
    d = decide(make_features(posted_late_fee=0), fee_type="late_fee", asked_amount=200)
    assert d.verdict == VERDICT_ESCALATE
    assert d.reason == NOTHING_TO_WAIVE


def test_outstanding_too_high_escalates() -> None:
    d = decide(make_features(outstanding=150_000), fee_type="late_fee", asked_amount=200)
    assert d.verdict == VERDICT_ESCALATE
    assert d.approved_amount is None


# ---------------------------------------------------------------------------
# Engine contract
# ---------------------------------------------------------------------------


def test_recommend_authority_never_raises(monkeypatch) -> None:
    from agent_core.authority import engine as engine_mod

    def _boom(*_a, **_k):
        raise RuntimeError("matrix exploded")

    monkeypatch.setattr(engine_mod, "decide", _boom)
    result = recommend_authority(
        customer_id="probe-cust",
        features=make_features(),
    )
    assert result.verdict == VERDICT_ESCALATE
    assert result.reason == "engine_error"
    assert result.approved_amount is None


def test_shadow_mode_is_not_actionable(monkeypatch) -> None:
    monkeypatch.setenv("AUTHORITY_MODE", "shadow")
    monkeypatch.setattr(
        "agent_core.authority.decisions.record", lambda **_k: "AD-SHADOW"
    )
    result = recommend_authority(
        customer_id="probe-cust",
        features=make_features(),
        asked_amount=200,
    )
    assert result.verdict == VERDICT_AUTO
    assert result.approved_amount == 200
    assert result.suppressed is True
    assert result.actionable is False
    assert result.to_tool_payload()["apply"] is False


def test_live_in_policy_is_actionable(monkeypatch) -> None:
    monkeypatch.setenv("AUTHORITY_MODE", "live")
    monkeypatch.setattr(
        "agent_core.authority.decisions.record", lambda **_k: "AD-LIVE"
    )
    result = recommend_authority(
        customer_id="probe-cust",
        features=make_features(),
        asked_amount=200,
    )
    assert result.actionable is True
    assert result.to_tool_payload()["apply"] is True


def test_quoting_above_the_cap_is_a_halt_flag() -> None:
    from agent_core.guardrails import evaluate_guardrails, should_halt

    flags = evaluate_guardrails(
        customer_text="please waive the late fee",
        bot_text="We can reverse ₹800 as a goodwill gesture.",
        intent="waiver_request",
        guardrails={},
        turn_index=3,
        elapsed_seconds=20,
        customer_bot_exchanges=2,
        max_waiver_inr=500,
    )
    assert "authority-cap-exceeded" in flags
    assert should_halt(flags)
