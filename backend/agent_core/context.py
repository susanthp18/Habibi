"""CallContext — the one context object every channel loads and injects.

Before this, CRM facts reached the model three different ways: placeholders
rendered into the system prompt (then stripped when unresolved), a
``get_account_position`` tool the hub had to remember to call, and nothing at
all on the WhatsApp side. The docs-aligned pattern is different: keep the system
prompt lean (identity + guardrails + channel rules) and push CRM facts in as
``developer`` messages via ``LLMMessagesAppendFrame`` when they become known.

So:
  * one :class:`CallContext` loaded once at verify time,
  * :meth:`CallContext.crm_card` rendered as a compact developer message,
  * short developer deltas appended after each mutating tool.

The system prompt is never re-rendered mid-call for changed numbers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

Channel = Literal["voice", "whatsapp", "sandbox_text", "sandbox_live"]

# Which KB corpus a given intent/node retrieves against.
#
# ``["collections"]`` is a HARD filter: collections money questions must never
# be answered out of the insurance product corpus.
#
# ``None`` means "no hard product filter" — kb_retrieve then applies its own
# soft product-family steering from the query tokens (travel / home / car /
# maid / …). That is exactly what the WhatsApp product path already does, and
# it is the right scope for upsell, where the caller could be asking about any
# of the non-collections product families. Hard-coding a product key list here
# would silently exclude every corpus added later.
PRODUCT_KEYS_COLLECTIONS = ("collections",)

_PRODUCT_INTENTS = frozenset({"product_faq", "upsell_opportunity"})
_PRODUCT_NODES = frozenset({"gated_upsell"})

# Statuses that mean "this commitment is finished". Shared with
# voice/memory.py, which derives cross-call open_commitments from the same
# tables — two copies of these sets would drift and the memory card would claim
# a promise is still open after the CRM closed it.
#
# Values are taken from the tables' own CHECK constraints:
#   promises          upcoming | due_today | kept | broken | partial
#   disputes          new | under_review | awaiting_customer | resolved | rejected
#   document_requests requested | generating | sent | failed
#   callbacks         scheduled | reminded | in_progress | completed | missed
#                     | rescheduled | cancelled
#
# The document set previously read {"delivered", "cancelled"} — neither of which
# is a legal status — so the filter matched nothing and every fulfilled document
# request stayed on the CRM card as "open work" for the life of the account.
# `partial` and `missed` are deliberately NOT closed: a part-paid promise and a
# missed callback both still need chasing.
CLOSED_PROMISE_STATUSES = frozenset({"kept", "broken"})
CLOSED_DISPUTE_STATUSES = frozenset({"resolved", "rejected"})
CLOSED_DOCUMENT_STATUSES = frozenset({"sent"})
CLOSED_CALLBACK_STATUSES = frozenset({"completed", "cancelled"})


def product_keys_for_intent(intent: str | None) -> list[str] | None:
    """KB corpus scope for an intent. Defaults to the collections corpus."""
    if (intent or "").strip() in _PRODUCT_INTENTS:
        return None
    return list(PRODUCT_KEYS_COLLECTIONS)


def product_keys_for_node(node: str | None) -> list[str] | None:
    """KB corpus scope for a Flows node — upsell talks products, the rest collections."""
    if (node or "") in _PRODUCT_NODES:
        return None
    return list(PRODUCT_KEYS_COLLECTIONS)


def _inr(value: Any) -> str | None:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return f"₹{amount:,.0f}"


@dataclass
class CallContext:
    """Everything the agent knows about this conversation, in one place."""

    channel: Channel
    session_id: str | None = None
    interaction_id: str | None = None
    customer_id: str | None = None
    account_id: str | None = None

    # Compact CRM facts — what the model is allowed to state as truth.
    customer_card: dict[str, Any] = field(default_factory=dict)
    open_work: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    kb_snapshot_id: str | None = None
    product_keys_default: list[str] = field(default_factory=lambda: list(PRODUCT_KEYS_COLLECTIONS))

    persona: dict[str, Any] | None = None
    prompt_version_id: str | None = None
    deployment_id: str | None = None
    bot_id: str | None = None
    tuning: dict[str, Any] = field(default_factory=dict)

    identity_verified: bool = False

    # ----------------------------------------------------------------- load

    @classmethod
    def load_for_customer(
        cls,
        *,
        channel: Channel,
        customer_id: str,
        interaction_id: str | None = None,
        account_id: str | None = None,
        **kwargs: Any,
    ) -> "CallContext":
        """Build a context from the CRM in one pass.

        Falls back to an identity-only context if the read fails — a degraded
        card is better than aborting a live call.

        Pass ``identity_verified=True`` to actually load CRM facts. Without it
        the context is built empty: balances, DPD and open work are the payload
        an unverified caller must never hear, and gating the *load* (not just
        the render) means they never enter the process in the first place.
        """
        ctx = cls(
            channel=channel,
            customer_id=customer_id,
            interaction_id=interaction_id,
            account_id=account_id,
            **kwargs,
        )
        try:
            ctx.refresh_from_crm()
        except Exception:
            logger.exception("CallContext CRM load failed — continuing with empty card")
        return ctx

    def refresh_from_crm(self) -> None:
        """Reload customer_card + open_work from Postgres. Synchronous by design."""
        if not self.customer_id:
            return
        if not self.identity_verified:
            logger.debug("CallContext refresh skipped — identity not verified")
            return
        import db

        customer = db.get_customer(self.customer_id)
        if not customer:
            return

        account = customer.get("account") or {}
        contact = customer.get("contact") or {}
        consent = customer.get("consent") or []
        wa = next((c for c in consent if (c.get("channel") or "").lower() == "whatsapp"), None)

        self.account_id = self.account_id or customer.get("accountId")
        self.customer_card = {
            "customerId": customer.get("id"),
            "name": customer.get("name"),
            "accountId": customer.get("accountId"),
            "accountTail": account_tail(customer.get("accountId")),
            "outstanding": customer.get("outstanding"),
            "minimumDue": customer.get("minimumDue"),
            "dpd": account.get("dpd"),
            "product": account.get("product"),
            "bucket": account.get("bucket"),
            "dnd": bool(contact.get("dnd")),
            "preferredWindow": contact.get("preferredWindow"),
            "whatsappOptedIn": bool(wa.get("optedIn")) if wa else None,
        }

        def _open(rows: Any, closed: set[str]) -> list[dict[str, Any]]:
            return [r for r in (rows or []) if (r.get("status") or "") not in closed][:3]

        self.open_work = {
            "promises": [
                {
                    "id": p.get("id"),
                    "amount": p.get("amount"),
                    "promisedDate": p.get("promisedDate"),
                    "status": p.get("status"),
                }
                for p in _open(customer.get("promises"), set(CLOSED_PROMISE_STATUSES))
            ],
            "disputes": [
                {"id": d.get("id"), "type": d.get("type"), "status": d.get("status")}
                for d in _open(customer.get("disputes"), set(CLOSED_DISPUTE_STATUSES))
            ],
            # db.get_customer() does not carry callbacks — don't fabricate an
            # always-empty section that costs tokens on every turn.
            "documentRequests": [
                {"id": d.get("id"), "type": d.get("type"), "status": d.get("status")}
                for d in _open(customer.get("documents"), set(CLOSED_DOCUMENT_STATUSES))
            ],
        }

    # -------------------------------------------------------------- inject

    def crm_card(self) -> str:
        """Compact CRM facts as a developer message body.

        Deliberately terse: every token here is spent on every subsequent turn.
        """
        if not self.identity_verified:
            # Belt and braces with refresh_from_crm's gate: even a card
            # populated by some other path must not be rendered pre-verify.
            return "NO VERIFIED CUSTOMER FACTS — identity is not verified. State nothing about this account."
        c = self.customer_card
        lines = ["VERIFIED CUSTOMER FACTS (authoritative — never invent or recompute):"]
        if c.get("name"):
            lines.append(f"- Name: {c['name']}")
        tail = c.get("accountTail")
        if tail:
            lines.append(f"- Account ending: {tail}")
        outstanding = _inr(c.get("outstanding"))
        if outstanding:
            lines.append(f"- Outstanding: {outstanding}")
        minimum = _inr(c.get("minimumDue"))
        if minimum:
            lines.append(f"- Minimum due: {minimum}")
        if c.get("dpd") is not None:
            lines.append(f"- Days past due: {c['dpd']}")
        if c.get("product"):
            lines.append(f"- Product: {c['product']}")
        if c.get("dnd"):
            lines.append("- DND is ON: do not promise outbound calls outside consent.")

        for label, key in (
            ("Open promises", "promises"),
            ("Open disputes", "disputes"),
            ("Pending documents", "documentRequests"),
        ):
            rows = self.open_work.get(key) or []
            if rows:
                lines.append(f"- {label}: {len(rows)} — {_summarize(rows)}")

        lines.append(
            "Use these numbers verbatim. If the caller disputes them, log a dispute; "
            "do not argue or recalculate."
        )
        return "\n".join(lines)

    def crm_card_message(self) -> dict[str, str]:
        """``LLMMessagesAppendFrame``-ready developer message."""
        return {"role": "developer", "content": self.crm_card()}

    def persona_message(self) -> dict[str, str] | None:
        """Sandbox persona as a developer message.

        The persona describes the *simulated customer* the tester is playing, so
        the agent knows who it is talking to. It is never a persona for the bot.

        Critically, it is a **stage direction, not an observation**. It is in
        context from turn 0, before the caller has said a word, and the voice
        naturalness overlay tells the bot to "gently mirror the caller's mood".
        Stated as bare fact ("mood: angry"), those two combine into a bot that
        opens the call with "I understand you're upset." to a caller who has not
        yet spoken — observed on a live sandbox call on 2026-08-01. So the mood
        and temperament are labelled as the tester's script and paired with an
        explicit prohibition on acting for them.
        """
        if not self.persona:
            return None
        p = self.persona
        bits = []
        for key, label in (
            ("name", "name"),
            ("language", "language"),
            ("mood", "mood they intend to play"),
            ("temperament", "temperament they intend to play"),
            ("scenario", "scenario"),
        ):
            value = p.get(key)
            if value:
                bits.append(f"{label}: {value}")
        notes = p.get("notes") or p.get("background") or p.get("description")
        if notes:
            bits.append(f"notes: {notes}")
        if not bits:
            return None
        # Which name to use once the account is known. The persona name is a
        # rehearsal label the tester typed; the CRM record is the account this
        # call is really acting on. When they differ and nothing says which
        # wins, the bot uses both — a live call greeted "Rahul" at the identity
        # step and then said "Susanth, your outstanding is ₹62,400" two turns
        # later, because verify_identity had resolved a real customer in
        # between and every tool after it returned that customer's data.
        authority = (
            " The persona is only how the tester is playing the call. Once an"
            " account is verified, the CRM record is the customer: use the name"
            " and the details it returns, not the persona name."
        )
        # The prohibition is the load-bearing half. Without it the model treats
        # the mood as something it has already witnessed and empathises with an
        # emotion the caller has not expressed yet.
        not_yet_observed = (
            " You have NOT heard this caller yet. This is the tester's script,"
            " not something you have observed. Do NOT reference their mood,"
            " name, situation or reason for calling until they say it"
            " themselves — greet them exactly as you would greet a caller you"
            " know nothing about, and let them tell you why they called."
        )
        return {
            "role": "developer",
            "content": (
                "SANDBOX REHEARSAL — the tester is role-playing a customer with "
                + "; ".join(str(b) for b in bits)
                + ". All CRM writes are real."
                + not_yet_observed
                + " Once they do speak, match their actual language and mood."
                + authority
            ),
        }

    def delta_message(self, text: str) -> dict[str, str]:
        """Short developer note after a mutating tool, e.g. 'PTP created id=PR-12'."""
        return {"role": "developer", "content": f"CRM UPDATE: {text}"}


def account_tail(account_id: str | None) -> str | None:
    """Last 4 *digits* of an account id — never letters.

    Ids look like ``AC-77410`` (→ ``7410``), but vanity ids like ``AC-SUSANTH``
    have no trailing digits and a naive ``[-4:]`` would have the bot read
    "ANTH" aloud. Return None so callers omit the phrasing entirely.
    """
    digits = "".join(ch for ch in (account_id or "") if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else None


def _summarize(rows: list[dict[str, Any]]) -> str:
    parts = []
    for r in rows[:3]:
        ident = r.get("id") or "?"
        extra = r.get("type") or r.get("promisedDate") or r.get("scheduledAt") or r.get("status")
        parts.append(f"{ident}{f' ({extra})' if extra else ''}")
    return ", ".join(parts)
