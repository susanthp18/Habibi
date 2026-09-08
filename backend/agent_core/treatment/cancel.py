"""Honest abort reasons. Every one is censoring; none is a training outcome.

``outcome='cancelled'`` stays on the row so existing CHECKs and case-ending
logic keep working. Trainers, OPE, and dashboards exclude cancelled rows and
read ``cancel_reason`` instead. The first five reasons are operational defect
signatures and page; the rest are expected policy or business censoring.
"""

from __future__ import annotations

PLAN_EXPIRED = "plan_expired"
NO_EXECUTOR = "no_executor"
UNKNOWN_ACTION = "unknown_action"
CUSTOMER_ROW_MISSING = "customer_row_missing"
CONTACT_GATE_REFUSED = "contact_gate_refused"
HANDLER_EXCEPTION = "handler_exception"
PAID_SINCE_DECISION = "paid_since_decision"
POLICY_EFFECTIVE_CHANGE = "policy_effective_change"
WINDOW_EDGE_CAPACITY = "window_edge_capacity"
PREREQUISITE_NOT_DELIVERED = "prerequisite_not_delivered"
ENDPOINT_UNVERIFIED = "endpoint_unverified"

REASONS: frozenset[str] = frozenset(
    {
        PLAN_EXPIRED,
        NO_EXECUTOR,
        UNKNOWN_ACTION,
        CUSTOMER_ROW_MISSING,
        CONTACT_GATE_REFUSED,
        HANDLER_EXCEPTION,
        PAID_SINCE_DECISION,
        POLICY_EFFECTIVE_CHANGE,
        WINDOW_EDGE_CAPACITY,
        PREREQUISITE_NOT_DELIVERED,
        ENDPOINT_UNVERIFIED,
    }
)

#: Operational defects. Expected policy/business censoring is not in this set.
PAGE_ON: frozenset[str] = frozenset(
    {
        PLAN_EXPIRED,
        NO_EXECUTOR,
        UNKNOWN_ACTION,
        CUSTOMER_ROW_MISSING,
        HANDLER_EXCEPTION,
    }
)

_NOTE_TO_REASON = {
    "plan_expired": PLAN_EXPIRED,
    "customer_gone": CUSTOMER_ROW_MISSING,
    "enactment_failed": HANDLER_EXCEPTION,
    "not_live": POLICY_EFFECTIVE_CHANGE,
}


def from_note(note: str | None) -> str:
    """Map an executor note onto a canonical reason."""
    raw = (note or "").strip()
    if raw in REASONS:
        return raw
    if raw in _NOTE_TO_REASON:
        return _NOTE_TO_REASON[raw]
    if raw.startswith("no_executor"):
        return NO_EXECUTOR
    if raw.startswith("unknown_action"):
        return UNKNOWN_ACTION
    if raw.startswith("contact:"):
        return CONTACT_GATE_REFUSED
    if raw.startswith("card_forbids") or raw.startswith("outside_service"):
        return PREREQUISITE_NOT_DELIVERED
    if raw in {"no_phone_on_file", "sms_not_configured", "whatsapp_not_configured"}:
        return ENDPOINT_UNVERIFIED
    return HANDLER_EXCEPTION


def pages(reason: str | None) -> bool:
    return (reason or "") in PAGE_ON
