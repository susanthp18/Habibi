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

# --- Assurance levels ------------------------------------------------------
#
# Identity used to be a boolean, and the boolean was unreachable on WhatsApp.
#
# `identify_customer` is offered there (grant.TEXT_ALWAYS), is executable, and
# does write `identity_verifications`. But the only ceremony a customer can
# naturally pass in a chat thread — the last four digits of their account —
# was downgraded to `status='pending'` by `capture.rebind_interaction_customer`,
# and this module required `'verified'`. The alternative, `phone_match`, asks a
# customer to type back the number the bot is already messaging. So every gated
# tool was permanently denied: in the live thread that prompted this, three in a
# row failed, and one of them was `request_callback` — the fallback the model
# was being told to offer instead.
#
# Meanwhile voice's writer (`voice/persist.record_identity_verification`) has no
# downgrade at all, so on a phone call the same `account_tail` writes
# `verified`. Two channels, one method, two meanings.
#
# The downgrade was not wrong about strength, it was wrong about shape. A tail
# IS weaker than a tail plus a proven endpoint. What was missing is that a
# proven endpoint is itself worth something, and that different tools need
# different amounts. Hence three levels rather than a flag:
LEVEL_NONE = "none"
#: The channel proved the customer controls the endpoint. On WhatsApp, Meta has
#: verified that the sender owns the number and we matched it to a CRM row.
#: Caller ID on a phone call does NOT qualify — ANI is spoofable, which is why
#: voice asks for spoken digits.
LEVEL_ENDPOINT = "endpoint"
#: The customer supplied something only they should know — account tail, date of
#: birth, an OTP — on top of an endpoint we had already reached.
LEVEL_CHALLENGE = "challenge"

_LEVEL_ORDER = {LEVEL_NONE: 0, LEVEL_ENDPOINT: 1, LEVEL_CHALLENGE: 2}

#: Which verification method earns which level. `manual` is an agent ticking the
#: identity box in the Inbox, having spoken to the person: that is a challenge.
_METHOD_LEVEL = {
    "phone_match": LEVEL_ENDPOINT,
    "account_tail": LEVEL_CHALLENGE,
    "dob": LEVEL_CHALLENGE,
    "otp": LEVEL_CHALLENGE,
    "manual": LEVEL_CHALLENGE,
}

#: What the model should do about it, by level. A bare error code taught the
#: model nothing — it retried three different gated tools and never tried the
#: one that would have unblocked them. Voice already had the right shape
#: (`{"error": "need_digits", "hint": "ask_caller_for_last_4_of_account"}`);
#: this is that, sourced from the requirement so the two cannot drift.
_REMEDY = {
    LEVEL_ENDPOINT: "call identify_customer with the sender's phone number first",
    LEVEL_CHALLENGE: (
        "ask the customer for the last 4 digits of their account number, then "
        "call identify_customer with account_tail before retrying this tool"
    ),
}


def meets(level: str, required: str) -> bool:
    return _LEVEL_ORDER.get(level, 0) >= _LEVEL_ORDER.get(required, 0)

# Text has no in-memory VoiceSession ceremony. These handlers can create or
# mutate regulated records, so a card omitting a decorative human_gate must
# not reopen them. ``identify_customer`` is intentionally absent: it is the
# text verification ceremony and writes the verified event required below.
#: Tool -> the level it needs. Tiered by what the act can actually do.
#:
#: `endpoint` covers reads and the reversible, low-harm writes: a note, a
#: callback, a contact preference, an offer put in front of someone. Getting
#: those wrong costs an apology. `challenge` covers money and the regulated
#: acts — a promise to pay, a dispute, a goodwill credit, a transfer to a human
#: who will open the borrower's account — where getting it wrong costs the
#: customer something they cannot undo.
TOOL_ASSURANCE: dict[str, str] = {
    "add_customer_note": LEVEL_ENDPOINT,
    "capture_lead": LEVEL_ENDPOINT,
    "capture_nonpayment_reason": LEVEL_ENDPOINT,
    "decline_offer": LEVEL_ENDPOINT,
    "recommend_next_offer": LEVEL_ENDPOINT,
    "request_callback": LEVEL_ENDPOINT,
    "set_contact_preference": LEVEL_ENDPOINT,
    "apply_goodwill": LEVEL_CHALLENGE,
    "create_promise_to_pay": LEVEL_CHALLENGE,
    "evaluate_authority": LEVEL_CHALLENGE,
    "flag_dispute": LEVEL_CHALLENGE,
    "ingest_customer_document": LEVEL_CHALLENGE,
    "request_documents": LEVEL_CHALLENGE,
    "handoff_to_agent": LEVEL_CHALLENGE,
}

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


def interaction_assurance(
    *,
    interaction_id: str | None,
    customer_id: str | None,
) -> str:
    """The strongest level ``identity_verifications`` records for this interaction.

    A bound customer id on its own is still nothing: resolving a sender to a CRM
    row is a lookup, not a ceremony, and the row that earns ``endpoint`` is
    written deliberately when the channel has actually proved the endpoint.
    Fails closed to ``none`` on missing ids, UNKNOWN-CALLER, or a DB error.
    """
    if not interaction_id or not customer_id or is_unknown_caller(customer_id):
        return LEVEL_NONE
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT method FROM identity_verifications
                     WHERE interaction_id = :iid
                       AND customer_id = :cid
                       AND status = 'verified'
                    """
                ),
                {"iid": interaction_id, "cid": customer_id},
            ).scalars().all()
    except Exception:
        logger.exception("identity_verifications lookup failed — failing closed")
        return LEVEL_NONE
    best = LEVEL_NONE
    for method in rows:
        level = _METHOD_LEVEL.get(str(method or "").strip().lower(), LEVEL_NONE)
        if _LEVEL_ORDER[level] > _LEVEL_ORDER[best]:
            best = level
    return best


def interaction_identity_verified(
    *,
    interaction_id: str | None,
    customer_id: str | None,
) -> bool:
    """Back-compat shim: "did a full challenge happen".

    Kept because the handoff packet and the voice session both ask this exact
    question and mean the strong form. New callers should ask for the level.
    """
    return interaction_assurance(
        interaction_id=interaction_id, customer_id=customer_id
    ) == LEVEL_CHALLENGE


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


def gate_failure(
    tool_name: str,
    *,
    card: Any,
    assurance: str,
    floor_ok: bool = False,
) -> dict[str, str] | None:
    """``None`` when the ceremony passes, else the refusal AND how to pass it.

    The remedy is the point. Returning a bare ``human_gate_identity`` told the
    model that something was wrong and nothing about what; in the thread that
    prompted this it reacted by trying two more gated tools and then offering a
    callback, which is also gated. A refusal that does not say what would work
    is a refusal the caller cannot act on.
    """
    require = _requirement_for(tool_name, card)
    if require is None and tool_name in IDENTITY_REQUIRED_TOOLS:
        require = "identity"
    if require is None:
        return None
    if require in {"identity", "both"}:
        # The card can only say "identity"; how much identity is this module's
        # call, so a card written before the levels existed still gets the
        # right strength for the tool it is gating.
        needed = TOOL_ASSURANCE.get(tool_name, LEVEL_CHALLENGE)
        if not meets(assurance, needed):
            return {
                "error": GATE_IDENTITY,
                "tool": tool_name,
                "required": needed,
                "have": assurance,
                "hint": _REMEDY[needed],
            }
    if require in {"floor", "both"} and not floor_ok:
        return {
            "error": GATE_FLOOR,
            "tool": tool_name,
            "hint": "a human must approve this before it can run",
        }
    return None


def enforce_human_gate(
    tool_name: str,
    *,
    card: Any,
    identity_verified: bool,
    floor_ok: bool = False,
) -> str | None:
    """Back-compat shim returning only the code. Prefer :func:`gate_failure`.

    ``identity_verified`` is the old boolean, so it maps to the strongest level
    — a caller still speaking in booleans is one that has not been taught about
    the weaker one, and reading its ``True`` as merely ``endpoint`` would
    silently weaken a gate it thinks it is enforcing.
    """
    failure = gate_failure(
        tool_name,
        card=card,
        assurance=LEVEL_CHALLENGE if identity_verified else LEVEL_NONE,
        floor_ok=floor_ok,
    )
    return failure["error"] if failure else None
