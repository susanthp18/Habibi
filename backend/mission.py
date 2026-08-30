"""The Mission — an authorised intervention, carried end to end.

An outbound call is not the inbound script with a different greeting. We chose
this borrower, this moment and this reason; the agent then asked them why they
thought we were calling. ``discover_intent`` is correct on an inbound call and
absurd on an outbound one, and it exists because nothing ever told the runtime
what the call was *for*.

A Mission is that missing object. It is assembled at dial time from three
sources and none of them is a prompt:

* the **Action Contract** from the decision engine — which borrower, when, at
  what expected value, under which policy version, with what propensity;
* the **agent card** — which mission this agent may run, where in its flow that
  mission starts, what it may concede, what it may offer, how long it has;
* the **book** — the account position, the open promise, the last contact and
  whether it was read.

Where it lives on the wire
--------------------------
Serialised onto ``call_attempts.context`` and passed to the voice worker as an
``attempt_id`` in the Twilio stream parameters. Not as the parameters
themselves: TwiML ``<Parameter>`` values are attributes on a document the
carrier parses, and putting a ledger position in one is a size limit waiting to
be discovered on a borrower with a long name. One id and one read is cheaper and
cannot truncate.

What it deliberately does not do
--------------------------------
It never decides *whether* to contact. That question is answered before a
Mission exists — by ``treatment`` and by ``contact_policy`` — and an executor
that could re-open it would be a second policy engine with no audit trail. The
Mission's own words are: *you are authorised to perform this intervention*.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: What a mission is *for*, in one line, in the agent's own second person. Used
#: to build the developer message the entry node opens with, so an authored
#: graph that says nothing still produces a call that knows why it happened.
OBJECTIVE_BRIEF: dict[str, str] = {
    "pre_due_reminder": (
        "Their instalment is due shortly and has not been paid. Remind them "
        "warmly — this is a courtesy, not a chase — and confirm they can pay on time."
    ),
    "bounce_cure": (
        "Their auto-debit failed. Find out whether it was a timing problem or a "
        "money problem, and agree how the instalment gets paid."
    ),
    "dpd_reminder": (
        "Their account is overdue. State the position plainly and without "
        "pressure, find out why, and agree a way forward."
    ),
    "broken_ptp_chase": (
        "They promised to pay and the date has passed. Refer to the promise they "
        "made, without reproach, and agree a new one you both believe."
    ),
    "hardship_intake": (
        "They have told us they are in difficulty. Listen, capture the reason, "
        "and offer the paths that exist. Do not negotiate and do not sell."
    ),
    "mandate_reregistration": (
        "Their auto-debit mandate is cancelled or invalid, so no payment can "
        "reach us however willing they are. This call is about fixing that, not "
        "about the arrears."
    ),
    "document_chase": (
        "A document we need is outstanding. Explain which, why, and how to send it."
    ),
    "callback_honour": (
        "They asked us to call back at this time. They are expecting you — open "
        "by saying so."
    ),
    "welcome_onboarding": (
        "Their loan has just started. Walk them through the first instalment and "
        "confirm the auto-debit is set up. Nothing is overdue."
    ),
    "retention_save": (
        "They have signalled they may leave. Understand why before offering "
        "anything."
    ),
    "cross_sell": (
        "They are eligible for a product. Mention it once, briefly, and stop if "
        "they are not interested."
    ),
    "manual_outbound": "A colleague asked for this call to be placed.",
}

#: Missions where naming a product is never acceptable regardless of what the
#: card allows. Hardship is the obvious one; a mandate call is the subtle one —
#: the borrower is trying to pay us and being sold to mid-repair is the kind of
#: thing that ends a pilot.
NEVER_OFFER: frozenset[str] = frozenset(
    {"hardship_intake", "mandate_reregistration", "broken_ptp_chase"}
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Warm context
# ---------------------------------------------------------------------------


def _account_position(conn: Any, account_id: str | None) -> dict[str, Any]:
    if not account_id:
        return {}
    row = conn.execute(
        text(
            """
            SELECT a.id, a.dpd, a.outstanding, a.minimum_due, a.status,
                   a.product_id, p.name AS product_name
            FROM accounts a
            LEFT JOIN products p ON p.id = a.product_id
            WHERE a.id = :id
            """
        ),
        {"id": account_id},
    ).mappings().first()
    if row is None:
        return {}
    # The shared helper, not a slice. `AC-SUSANTH`[-4:] is "ANTH", and the
    # briefing would have had the agent say "account ending ANTH" out loud —
    # which is precisely the case ``agent_core.context.account_tail`` was
    # written for. It returns None when there are no trailing digits, and the
    # briefing then omits the phrasing entirely.
    from agent_core.context import account_tail

    return {
        "accountId": row["id"],
        "accountTail": account_tail(row["id"]),
        "dpd": int(row["dpd"] or 0),
        "outstandingInr": float(row["outstanding"]) if row["outstanding"] is not None else None,
        "minimumDueInr": float(row["minimum_due"]) if row["minimum_due"] is not None else None,
        "status": row["status"],
        "productName": row["product_name"],
    }


def _open_promise(conn: Any, customer_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT id, amount, promised_at, status
            FROM promises
            WHERE customer_id = :cid AND status IN ('upcoming','due_today','broken','partial')
            ORDER BY promised_at DESC
            LIMIT 1
            """
        ),
        {"cid": customer_id},
    ).mappings().first()
    if row is None:
        return None
    promised = row["promised_at"]
    days_late = None
    if promised is not None:
        at = promised if promised.tzinfo else promised.replace(tzinfo=timezone.utc)
        days_late = max(0, int((_now() - at).total_seconds() // 86_400))
    return {
        "promiseId": row["id"],
        "amountInr": float(row["amount"]) if row["amount"] is not None else None,
        "promisedDate": promised.date().isoformat() if promised else None,
        "status": row["status"],
        "daysLate": days_late,
    }


def _last_contact(conn: Any, customer_id: str) -> dict[str, Any] | None:
    """The most recent thing we sent, and whether it landed.

    A borrower who read our WhatsApp yesterday and one who has heard nothing for
    a month are different conversations, and opening with "I'm following up on
    the message we sent" only works if the message was actually delivered.
    """
    row = conn.execute(
        text(
            """
            SELECT e.channel, e.occurred_at,
                   (
                     SELECT d.state FROM contact_delivery_events d
                     WHERE d.customer_id = e.customer_id
                       AND d.related_id = e.related_id
                     ORDER BY d.occurred_at DESC LIMIT 1
                   ) AS delivery
            FROM contact_events e
            WHERE e.customer_id = :cid
              AND e.outcome = 'allowed'
              AND e.direction = 'outbound'
            ORDER BY e.occurred_at DESC
            LIMIT 1
            """
        ),
        {"cid": customer_id},
    ).mappings().first()
    if row is None:
        return None
    at = row["occurred_at"]
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    hours = int((_now() - at).total_seconds() // 3600) if at else None
    return {
        "channel": row["channel"],
        "hoursAgo": hours,
        "delivery": row["delivery"],
        "read": row["delivery"] == "read",
    }


def _customer(conn: Any, customer_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT id, tenant_id, name, language, timezone, phone_primary, phone_alt
            FROM customers WHERE id = :id
            """
        ),
        {"id": customer_id},
    ).mappings().first()
    return dict(row) if row else None


def _first_name(name: str | None) -> str:
    return (name or "").strip().split(" ")[0] if name else ""


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build(
    conn: Any,
    *,
    customer_id: str,
    objective: str,
    account_id: str | None = None,
    card: Any = None,
    bot_id: str | None = None,
    deployment_id: str | None = None,
    decision: dict[str, Any] | None = None,
    campaign_run_id: str | None = None,
    attempt_no: int = 1,
) -> dict[str, Any] | None:
    """Assemble one Mission. Returns None only when the borrower is gone.

    Never raises: a missing product name or an unreadable promise degrades the
    briefing, and a call that opens slightly colder is a much better failure
    than a call that does not happen.
    """
    customer = _customer(conn, customer_id)
    if customer is None:
        return None

    objective_spec = None
    outbound_cfg = getattr(card, "outbound", None) if card is not None else None
    if outbound_cfg is not None:
        objective_spec = outbound_cfg.objective(objective)

    context: dict[str, Any] = {}
    try:
        context["position"] = _account_position(conn, account_id)
        context["promise"] = _open_promise(conn, customer_id)
        context["lastContact"] = _last_contact(conn, customer_id)
    except Exception:
        logger.exception("mission warm context failed for %s", customer_id)

    # Offers: the card's allowance, narrowed by the mission's own conscience and
    # by the number we are dialling from. Three independent gates that can only
    # ever subtract, so no single misconfiguration opens a sales pitch.
    allowed_offers: list[str] = list(getattr(objective_spec, "allowed_offers", []) or [])
    if objective in NEVER_OFFER:
        allowed_offers = []
    if outbound_cfg is not None and outbound_cfg.pool_kind == "service_1600":
        allowed_offers = []

    prohibited = ["third_party_disclosure", "pressure_language"]
    if not allowed_offers:
        prohibited.append("cross_sell")

    mission = {
        "objective": objective,
        "brief": OBJECTIVE_BRIEF.get(objective, ""),
        "customerId": customer_id,
        "customerName": customer.get("name"),
        "firstName": _first_name(customer.get("name")),
        "accountId": account_id,
        "language": customer.get("language"),
        "timezone": customer.get("timezone"),
        "botId": bot_id,
        "deploymentId": deployment_id,
        "entryNode": getattr(objective_spec, "entry_node", "") or "",
        "maxDurationSec": int(getattr(objective_spec, "max_duration_sec", 240) or 240),
        "authorityProfile": getattr(objective_spec, "authority_profile", None),
        # The voicemail policy travels with the mission because the decision
        # "leave a message or not" is made on the audio path, seconds after the
        # detector fires, with no time to go and read a card.
        "voicemail": _voicemail_policy(objective_spec),
        # Card-level, not per-objective: whether this agent may navigate a third
        # party's phone menu is a property of the agent, not of why it called.
        "ivrTraversal": bool(getattr(outbound_cfg, "ivr_traversal", False)),
        "ivrMaxSec": int(getattr(outbound_cfg, "ivr_max_sec", 90) or 90),
        "allowedOffers": allowed_offers,
        "prohibited": prohibited,
        "success": list(getattr(objective_spec, "success", []) or []),
        "attemptNo": attempt_no,
        "campaignRunId": campaign_run_id,
        "context": context,
    }
    if decision:
        # Carried verbatim. Without decision_id the outcome cannot be attributed
        # to the decision that caused it; without propensity no off-policy
        # estimate over the log is valid. Both are cheap and neither can be
        # reconstructed afterwards.
        mission.update(
            {
                "decisionId": decision.get("id"),
                "propensity": float(decision["propensity"])
                if decision.get("propensity") is not None
                else None,
                "policyVersion": decision.get("policy_version"),
                "variant": decision.get("variant"),
                "expectedValueInr": float(decision["expected_value"])
                if decision.get("expected_value") is not None
                else None,
                "trigger": decision.get("trigger_kind"),
            }
        )
    return mission


def _voicemail_policy(objective_spec: Any) -> dict[str, Any]:
    vm = getattr(objective_spec, "voicemail", None)
    return {
        "leave": getattr(vm, "leave", "first_attempt_only"),
        "maxSec": getattr(vm, "max_sec", 25),
        "includeGrievanceContact": getattr(vm, "include_grievance_contact", True),
    }


def load(conn: Any, attempt_id: str) -> dict[str, Any] | None:
    """Read the Mission back off the attempt the voice worker was handed."""
    row = conn.execute(
        text("SELECT context FROM call_attempts WHERE id = :id"), {"id": attempt_id}
    ).mappings().first()
    if row is None:
        return None
    context = row["context"] if isinstance(row["context"], dict) else {}
    mission = context.get("mission")
    return mission if isinstance(mission, dict) else None


# ---------------------------------------------------------------------------
# The briefing
# ---------------------------------------------------------------------------


def _inr(value: Any) -> str:
    try:
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return ""


def briefing(mission: dict[str, Any]) -> str:
    """The developer message the outbound call opens with.

    Facts, not prose the model has to trust: every figure here came out of a
    row moments ago. This is what replaces ``discover_intent`` — the agent
    starts the call already knowing what an inbound agent has to spend two turns
    discovering, which is the single biggest cause of an early hang-up.
    """
    lines: list[str] = ["OUTBOUND CALL — you placed this call. The customer did not."]
    brief = mission.get("brief")
    if brief:
        lines.append(f"Why you are calling: {brief}")

    first = mission.get("firstName")
    if first:
        lines.append(
            f"You dialled {first}'s number on file. Open by confirming you are "
            f"speaking to {first} BEFORE mentioning the account, the balance, or "
            "anything about money. If it is not them, or you are unsure, say only "
            "that you are calling from the bank about a personal matter and ask "
            "when {name} is available.".replace("{name}", first)
        )

    ctx = mission.get("context") or {}
    position = ctx.get("position") or {}
    if position.get("outstandingInr") is not None:
        tail = position.get("accountTail")
        bits = [f"outstanding is INR {_inr(position['outstandingInr'])}"]
        if position.get("minimumDueInr") is not None:
            bits.append(f"minimum due INR {_inr(position['minimumDueInr'])}")
        if position.get("dpd"):
            bits.append(f"{position['dpd']} days overdue")
        lines.append(
            "Account position (already fetched — do not call get_account_position "
            f"unless they ask for detail): {', '.join(bits)}"
            + (f", account ending {tail}." if tail else ".")
        )

    promise = ctx.get("promise")
    if promise and promise.get("amountInr") is not None:
        state = "was not kept" if promise.get("status") == "broken" else "is open"
        late = f", {promise['daysLate']} days ago" if promise.get("daysLate") else ""
        lines.append(
            f"They promised INR {_inr(promise['amountInr'])} by "
            f"{promise.get('promisedDate')}{late} and that promise {state}. "
            "Refer to it without reproach."
        )

    last = ctx.get("lastContact")
    if last and last.get("hoursAgo") is not None and last["hoursAgo"] < 168:
        seen = "which they read" if last.get("read") else "which may not have been seen"
        lines.append(
            f"We sent them a {last['channel']} message about {last['hoursAgo']} "
            f"hours ago, {seen}. You may refer to it."
        )

    if not mission.get("allowedOffers"):
        lines.append(
            "Do NOT mention any product, offer, top-up or upgrade on this call, "
            "and do not explain why."
        )

    budget = mission.get("maxDurationSec")
    if budget:
        lines.append(
            f"Keep this call under about {int(budget) // 60} minutes. If you are "
            "not converging, offer a callback rather than continuing."
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Card resolution
# ---------------------------------------------------------------------------


def resolve_outbound_bot_id(
    *,
    explicit: str | None = None,
    decision: dict[str, Any] | None = None,
    objective: str | None = None,
) -> str:
    """The agent that should place this dial.

    Order: an explicit id (campaign, demo env, request), then the treatment
    decision, then a production bot whose card claims this objective, then the
    tenant default. Hard-coding ``DEFAULT_BOT_ID`` at the call site is how a
    card authored in Agent Studio still rang as ``kaia-v2-4``.
    """
    import db as dbmod

    for candidate in (
        (explicit or "").strip(),
        str((decision or {}).get("bot_id") or (decision or {}).get("botId") or "").strip(),
    ):
        if candidate:
            return candidate

    obj = (objective or "").strip()
    default = str(dbmod.DEFAULT_BOT_ID)

    def _claims(bot_id: str) -> bool:
        if not obj:
            return False
        card = card_for_bot(bot_id)
        return bool(
            card is not None
            and card.outbound.dials
            and card.outbound.objective(obj) is not None
        )

    if _claims(default):
        return default
    if obj:
        try:
            for bot_id in sorted(dbmod.list_bot_ids()):
                if bot_id != default and _claims(bot_id):
                    return bot_id
        except Exception:
            logger.debug("outbound bot scan failed", exc_info=True)
    return default


def card_for_bot(bot_id: str | None, *, environment: str = "production") -> Any | None:
    """The published card for this agent, or the first-party default, or None.

    Order matters. The *published* card is what the compiler gated and what a
    regulator would be shown, so it wins. The first-party default is the
    fallback for a fresh install whose bot has no version yet — useful in
    development and never authoritative. Neither is required: a dial with no
    card still happens, it just carries no mission envelope, which is exactly
    what every outbound call did before this module existed.
    """
    bot = (bot_id or "").strip()
    if not bot:
        return None
    from agent_core.cards.schema import parse_card

    try:
        import db as dbmod

        deployment = dbmod.get_active_deployment(bot_id=bot, environment=environment)
        if deployment and deployment.get("promptVersionId"):
            version = dbmod.get_prompt_version(deployment["promptVersionId"])
            raw = (version or {}).get("agentCard") or (version or {}).get("agent_card")
            if isinstance(raw, dict) and raw:
                return parse_card(raw)
    except Exception:
        logger.debug("published card unreadable for %s", bot, exc_info=True)

    try:
        from agent_core.cards.defaults import card_for

        return card_for(bot)
    except Exception:
        return None


def objective_for_trigger(trigger: str | None) -> str:
    """Decision-engine trigger -> mission. The engine already knows why it chose
    to dial; carrying that word through is what lets reach and outcome be
    reported per mission rather than for "voice" as a whole."""
    return {
        "bounce": "bounce_cure",
        "broken_ptp": "broken_ptp_chase",
        "pre_due": "pre_due_reminder",
        "dpd_tick": "dpd_reminder",
    }.get(str(trigger or ""), "dpd_reminder")
