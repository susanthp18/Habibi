"""The matrix itself — policy-as-code, not LLM generosity.

Scoring is not a ranking problem here. There is one asked amount and one fee
type, and the answer is ``auto_approve``, ``cap_inr`` or ``escalate``. A scorer
cannot resurrect a vetoed move; there is no scorer.

``approved_amount`` is always inside the cap, or ``None``. That is the same
discipline ``suggest_amount()`` has for upsell: the model never invents a
figure this module did not emit.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_core.authority import config
from agent_core.authority.features import (
    FEE_BOUNCE,
    FEE_LATE,
    FEE_RESTRUCTURE,
    FEE_SETTLEMENT,
    FEE_TYPES,
    SILENCING_HOLDS,
    AccountAuthority,
)

VERDICT_AUTO = "auto_approve"
VERDICT_CAP = "cap_inr"
VERDICT_ESCALATE = "escalate"

VERDICTS = frozenset({VERDICT_AUTO, VERDICT_CAP, VERDICT_ESCALATE})

# --- reason codes (stable, logged, counted) --------------------------------
ENGINE_OFF = "engine_off"
ENGINE_ERROR = "engine_error"
UNKNOWN_FEE = "unknown_fee_type"
IDENTITY = "identity_not_verified"
HOLD_PREFIX = "hold:"
PRIOR_GOODWILL = "prior_goodwill_12m"
DPD_TOO_HIGH = "dpd_too_high"
DPD_UNKNOWN = "dpd_unknown"
OUTSTANDING_TOO_HIGH = "outstanding_too_high"
TENURE_TOO_SHORT = "tenure_too_short"
SETTLEMENT_FORBIDDEN = "settlement_live_forbidden"
RESTRUCTURE_FORBIDDEN = "restructure_live_forbidden"
BOUNCE_FORBIDDEN = "bounce_reversal_live_forbidden"
ASKED_ABOVE_CAP = "asked_above_cap"
WITHIN_CAP = "within_cap"
CAP_AVAILABLE = "cap_available"
NOTHING_TO_WAIVE = "nothing_to_waive"


@dataclass(frozen=True)
class MatrixDecision:
    verdict: str
    approved_amount: float | None
    cap_amount: float | None
    reason: str
    reason_codes: tuple[str, ...]

    def to_log(self) -> dict[str, object]:
        return {
            "verdict": self.verdict,
            "approvedAmount": self.approved_amount,
            "capAmount": self.cap_amount,
            "reason": self.reason,
            "reasonCodes": list(self.reason_codes),
        }


def _escalate(reason: str, *extra: str, cap: float | None = None) -> MatrixDecision:
    codes = (reason,) + extra
    return MatrixDecision(
        verdict=VERDICT_ESCALATE,
        approved_amount=None,
        cap_amount=cap,
        reason=reason,
        reason_codes=codes,
    )


def _round_inr(value: float) -> float:
    """Whole rupees. A waiver of ₹499.73 is a spreadsheet cell, not a sentence."""
    return float(max(0, round(value)))


def late_fee_cap_for(features: AccountAuthority) -> float | None:
    """The rupee ceiling for this account, or None if live goodwill is forbidden.

    Returns 0 when the posted fee is known and already zero — that is a
    different signal from "we do not know the fee".
    """
    dpd = features.dpd
    if dpd is None:
        return None
    if dpd >= config.late_fee_max_dpd():
        return None
    if dpd <= 30:
        cap = config.late_fee_cap()
    else:
        cap = config.late_fee_mid_cap()
    posted = features.posted_late_fee
    if posted is not None:
        cap = min(cap, max(0.0, posted))
    return _round_inr(cap)


def decide(
    features: AccountAuthority,
    *,
    fee_type: str,
    asked_amount: float | None,
) -> MatrixDecision:
    """May we close this request on the call? Never raises."""
    kind = (fee_type or "").strip().lower() or FEE_LATE
    if kind not in FEE_TYPES:
        return _escalate(UNKNOWN_FEE)

    if not features.identity_verified:
        return _escalate(IDENTITY)

    for hold in features.holds:
        if hold in SILENCING_HOLDS:
            return _escalate(f"{HOLD_PREFIX}{hold}")

    if kind == FEE_SETTLEMENT:
        return _escalate(SETTLEMENT_FORBIDDEN)
    if kind == FEE_RESTRUCTURE:
        return _escalate(RESTRUCTURE_FORBIDDEN)
    if kind == FEE_BOUNCE:
        return _escalate(BOUNCE_FORBIDDEN)

    # late_fee from here.
    if features.goodwill_count_12m > 0:
        return _escalate(PRIOR_GOODWILL)

    if features.dpd is None:
        return _escalate(DPD_UNKNOWN)

    if features.dpd >= config.late_fee_max_dpd():
        return _escalate(DPD_TOO_HIGH)

    outstanding = features.outstanding
    if outstanding is not None and outstanding > config.late_fee_max_outstanding():
        return _escalate(OUTSTANDING_TOO_HIGH)

    tenure = features.tenure_months
    if tenure is not None and tenure < config.min_tenure_months():
        return _escalate(TENURE_TOO_SHORT)

    cap = late_fee_cap_for(features)
    if cap is None:
        return _escalate(DPD_TOO_HIGH)
    if cap <= 0:
        return _escalate(NOTHING_TO_WAIVE, cap=0.0)

    asked = None
    if asked_amount is not None:
        try:
            asked = float(asked_amount)
        except (TypeError, ValueError):
            asked = None
        if asked is not None and asked < 0:
            asked = None

    if asked is None:
        return MatrixDecision(
            verdict=VERDICT_CAP,
            approved_amount=cap,
            cap_amount=cap,
            reason=CAP_AVAILABLE,
            reason_codes=(CAP_AVAILABLE,),
        )

    if asked <= cap:
        approved = _round_inr(asked) if asked > 0 else cap
        approved = min(approved, cap)
        return MatrixDecision(
            verdict=VERDICT_AUTO,
            approved_amount=approved,
            cap_amount=cap,
            reason=WITHIN_CAP,
            reason_codes=(WITHIN_CAP,),
        )

    # Asked above the cap: the allowed move is still the cap. The agent may
    # offer up to that figure. Insisting on more is an escalate, without
    # quoting a larger number — that is what ``ASKED_ABOVE_CAP`` tells the UI.
    return MatrixDecision(
        verdict=VERDICT_CAP,
        approved_amount=cap,
        cap_amount=cap,
        reason=ASKED_ABOVE_CAP,
        reason_codes=(ASKED_ABOVE_CAP, CAP_AVAILABLE),
    )
