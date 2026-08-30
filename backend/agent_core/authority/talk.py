"""Sentences a human (or the model) is allowed to say.

Talk tracks are reconstructed from the verdict, never stored, so the sentence a
rep sees on Handoff is the sentence the bot would have been given. Figures come
only from ``approved_amount`` / ``cap_amount`` — a number that is not in the
decision must not appear here.
"""

from __future__ import annotations

import money_inr
from agent_core.authority.matrix import (
    ASKED_ABOVE_CAP,
    BOUNCE_FORBIDDEN,
    DPD_TOO_HIGH,
    HOLD_PREFIX,
    IDENTITY,
    PRIOR_GOODWILL,
    RESTRUCTURE_FORBIDDEN,
    SETTLEMENT_FORBIDDEN,
    TENURE_TOO_SHORT,
    VERDICT_AUTO,
    VERDICT_CAP,
    VERDICT_ESCALATE,
    MatrixDecision,
)


def _inr(amount: float | None) -> str:
    """Rupees for a line the agent says out loud to the customer.

    Empty string on None, not an em dash: these are concatenated into sentences
    ("Goodwill ceiling is …"), and a dash read aloud is worse than silence.
    """
    return money_inr.inr(amount, none="")


def talk_track(decision: MatrixDecision, *, fee_type: str = "late_fee") -> str:
    if decision.verdict == VERDICT_AUTO and decision.approved_amount is not None:
        return (
            f"You may reverse {_inr(decision.approved_amount)} late fee on this call. "
            "Do not offer more. Call apply_goodwill with that amount."
        )
    if decision.verdict == VERDICT_CAP and decision.approved_amount is not None:
        extra = ""
        if decision.reason == ASKED_ABOVE_CAP:
            extra = " They asked for more than the ceiling — do not quote a larger figure."
        return (
            f"Goodwill ceiling is {_inr(decision.approved_amount)}. "
            "You may reverse up to that. If they insist on more, escalate without quoting a larger number."
            + extra
        )
    return escalate_line(decision.reason, fee_type=fee_type)


def escalate_line(reason: str | None, *, fee_type: str = "late_fee") -> str:
    if reason == SETTLEMENT_FORBIDDEN:
        return (
            "Do not quote a settlement percentage. Warm-transfer to a specialist "
            "with the transcript and the amount they asked for."
        )
    if reason == RESTRUCTURE_FORBIDDEN:
        return (
            "Restructuring needs a documented review. Log interest and warm-transfer. "
            "Do not approve a plan or quote terms on this call."
        )
    if reason == BOUNCE_FORBIDDEN:
        return (
            "Do not promise bounce-charge reversal on this call. Log a dispute "
            "and offer a specialist callback."
        )
    if reason == PRIOR_GOODWILL:
        return (
            "A goodwill waiver already posted in the last 12 months. Escalate — "
            "do not offer another reversal on this call."
        )
    if reason == DPD_TOO_HIGH:
        return (
            "Out of policy for live goodwill — DPD is too high. Transfer; "
            "do not quote a waiver amount."
        )
    if reason == TENURE_TOO_SHORT:
        return "Tenure is too short for live goodwill. Escalate without quoting a figure."
    if reason == IDENTITY:
        return "Identity is not verified. Do not discuss fees or quote any amount."
    if reason and reason.startswith(HOLD_PREFIX):
        kind = reason.split(":", 1)[-1]
        return (
            f"A {kind} hold is on this account. Do not pitch a waiver. "
            "Warm-transfer with the packet."
        )
    if fee_type == "settlement":
        return "Do not quote a settlement percentage. Warm-transfer."
    return (
        "Out of policy for live goodwill. Escalate to a specialist with the "
        "transcript, the asked amount, and this reason. Do not quote a figure."
    )


def packet(
    decision: MatrixDecision,
    *,
    fee_type: str,
    asked_amount: float | None,
    customer_id: str | None = None,
) -> dict[str, object]:
    """What a specialist needs if this leaves the call."""
    return {
        "feeType": fee_type,
        "askedAmount": asked_amount,
        "verdict": decision.verdict,
        "approvedAmount": decision.approved_amount,
        "capAmount": decision.cap_amount,
        "reason": decision.reason,
        "reasonCodes": list(decision.reason_codes),
        "talkTrack": talk_track(decision, fee_type=fee_type),
        "customerId": customer_id,
    }
