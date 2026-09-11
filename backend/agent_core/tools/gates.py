"""Human-gate consumer shared by voice and text.

The card lists ceremonies (``identity``, ``floor``, ``both``). Membership in
the grant is still ``ToolGrant.may_execute``; this module is the extra
ceremony that grant membership does not imply.

``identity`` reads a real verification event. ``floor`` and ``both`` fail
closed until an authoritative floor-approval record exists — there is none
today, so those requirements deny.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

import db
from db_core import is_unknown_caller

logger = logging.getLogger(__name__)

#: Stable codes the model and the Inspector can branch on.
GATE_IDENTITY = "human_gate_identity"
GATE_FLOOR = "human_gate_floor"

# Text has no in-memory VoiceSession ceremony. These handlers can create or
# mutate regulated records, so a card omitting a decorative human_gate must
# not reopen them. ``identify_customer`` is intentionally absent: it is the
# text verification ceremony and writes the verified event required below.
IDENTITY_REQUIRED_TOOLS: frozenset[str] = frozenset(
    {
        "create_promise_to_pay",
        "flag_dispute",
        "evaluate_authority",
        "apply_goodwill",
        "request_callback",
        "add_customer_note",
        "capture_nonpayment_reason",
        "set_contact_preference",
        "recommend_next_offer",
        "capture_lead",
        "decline_offer",
        "request_documents",
        "ingest_customer_document",
        # Transferring a caller is a regulated act, not navigation: the
        # receiving specialist opens with the borrower's account in front of it.
        #
        # Only intake-v1 declared a human_gate for this, and intake is not the
        # card inbound traffic lands on — BOT_ID resolves to collections — so
        # the gate guarded a door nobody enters while the card every call
        # actually reaches would transfer an unverified caller onward. Gating it
        # here rather than on two cards closes it for every caller on all three
        # dispatch paths, and keeps a later fleet member from reopening it by
        # forgetting to declare the gate its sender holds.
        #
        # `escalate_to_human` is deliberately absent: reaching a person must
        # never require passing a ceremony the caller is failing.
        "handoff_to_agent",
    }
)


def interaction_identity_verified(
    *,
    interaction_id: str | None,
    customer_id: str | None,
) -> bool:
    """True only when ``identity_verifications`` has a verified row.

    A bound customer id is not verification. WhatsApp resolving the sender to
    a CRM row is not a ceremony. Fail closed on missing ids, UNKNOWN-CALLER,
    or a registry/DB error.
    """
    if not interaction_id or not customer_id or is_unknown_caller(customer_id):
        return False
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT 1 FROM identity_verifications
                     WHERE interaction_id = :iid
                       AND customer_id = :cid
                       AND status = 'verified'
                     LIMIT 1
                    """
                ),
                {"iid": interaction_id, "cid": customer_id},
            ).first()
        return bool(row)
    except Exception:
        logger.exception("identity_verifications lookup failed — failing closed")
        return False


def floor_approved(*, interaction_id: str | None, tool_name: str) -> bool:
    """No floor-approval ledger exists yet. Fail closed."""
    del interaction_id, tool_name
    return False


def _requirement_for(tool_name: str, card: Any) -> str | None:
    gates = []
    if card is None:
        return None
    if isinstance(card, dict):
        gates = card.get("human_gates") or []
    else:
        gates = getattr(card, "human_gates", None) or []
    for gate in gates:
        if isinstance(gate, dict):
            name = gate.get("tool_name") or gate.get("toolName")
            require = gate.get("require")
        else:
            name = getattr(gate, "tool_name", None)
            require = getattr(gate, "require", None)
        if name == tool_name and require:
            return str(require)
    return None


def enforce_human_gate(
    tool_name: str,
    *,
    card: Any,
    identity_verified: bool,
    floor_ok: bool = False,
) -> str | None:
    """Return a stable error code, or ``None`` if the ceremony passes.

    Tools with no card gate are unrestricted here; the grant still has to
    allow them. ``floor`` / ``both`` deny unless ``floor_ok`` is true.
    """
    require = _requirement_for(tool_name, card)
    if require is None and tool_name in IDENTITY_REQUIRED_TOOLS:
        require = "identity"
    if require is None:
        return None
    if require in {"identity", "both"} and not identity_verified:
        return GATE_IDENTITY
    if require in {"floor", "both"} and not floor_ok:
        return GATE_FLOOR
    return None
