"""The written record of what happened on the call, beyond a promise to pay.

``promise_fulfillment.fulfill()`` is the pattern this generalises, and it is a
good one: it creates the intent, picks a channel the borrower has not opted out
of, runs the contact gate, enqueues through ``whatsapp_outbound_jobs`` where the
retry/locking/dead-letter shape already exists, and **never invents a URL for
the model to read aloud**. What it does not do is cover any outcome other than a
promise. A borrower who declared hardship, raised a dispute or asked for a
callback got a conversation and then silence.

No model writes this copy
-------------------------
Every body below is an f-string over values that came from the structured
outcome — an amount the authority matrix approved, a reference the dispute tool
minted, a time the borrower named. There is no summariser in this path, so there
is nothing to number-fence: the numbers cannot be wrong the way an LLM's numbers
can be wrong, because no LLM produced them.

Two outcomes are deliberately not written to
--------------------------------------------
Both look like obvious candidates and both are wrong, for the same underlying
reason — the message would arrive at a person who did not agree to receive it.

* **wrong number.** We have just established that the handset does not belong to
  the borrower. A message to it saying anything at all — even an apology, even
  one carrying our grievance officer's details — tells a stranger that a bank
  was trying to reach somebody at their number. Under RBI para 100O that is the
  borrower's information going to a third party, and the correct handling of a
  wrong number is to stop using it, which ``mark_phone_dead`` already does.

* **opt-out confirmation.** The borrower has just told us to stop contacting
  them. One more message confirming that we will stop is still one more message,
  and the confirmation properly belongs to the call itself, where the agent says
  it while the borrower is on the line. There is a second, sharper reason:
  ``contact_policy`` blocks on consent *before* it considers purpose, so the only
  way to send this would be to open a hole in a fail-closed gate — and a hole
  opened for the most sympathetic case is the hole everything else eventually
  goes through.

Both return a refusal with a reason rather than failing quietly, so an author who
writes ``confirm_written`` into either rule can see why it did nothing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Mapping

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: Kinds that produce a message.
#:
#: There is deliberately no ``plan_ack``. An agreed plan reaches the Closer as a
#: promise row, and a promise routes to ``promise_fulfillment.fulfill`` — the
#: path with the pay link. A separate plan acknowledgement could only fire on an
#: outcome that agreed a plan *without* writing a promise, which means it could
#: only ever fire with no amount and no date to state. Shipping it would have
#: added a fifth kind that validates, versions and never sends: the exact
#: failure section 20 of the design doc is about.
SENDABLE = ("hardship_ack", "dispute_ref", "callback_confirm")

#: Kinds that are understood, deliberately refused, and say so. See the module
#: docstring — each of these is a decision, not a gap.
REFUSED = {
    "wrong_number_ack": "third_party_number",
    "optout_confirm": "opt_out_honoured",
}

KINDS = SENDABLE + tuple(REFUSED)

#: Outcome code -> follow-up kind. This is what an author gets by writing a bare
#: ``confirm_written`` against an outcome that is not a promise.
BY_OUTCOME = {
    "hardship_declared": "hardship_ack",
    "dispute_raised": "dispute_ref",
    "callback_requested": "callback_confirm",
    "wrong_number": "wrong_number_ack",
    "opt_out_requested": "optout_confirm",
}


@dataclass
class Written:
    sent: bool = False
    kind: str = ""
    channel: str | None = None
    reason: str | None = None
    message_id: str | None = None

    def describe(self) -> str:
        if self.sent:
            return f"{self.kind}:{self.channel}"
        return f"{self.kind}:refused:{self.reason or 'unknown'}"


def _fmt_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "").strip()


def _fmt_when(value: Any) -> str:
    """A datetime a person would read back. Platform-portable on purpose.

    ``%-I`` is a glibc extension and this runs on Windows in development, so the
    leading zero is stripped by hand rather than by a format code that raises on
    half the machines the test suite runs on.
    """
    if isinstance(value, datetime):
        stamp = value.strftime("%d %b at %I:%M %p")
        head, _, tail = stamp.partition(" at ")
        return f"{head} at {tail.lstrip('0')}"
    return str(value or "").strip()


def _brand(tenant_id: str | None = None) -> str:
    import db as dbmod

    return (tenant_id or dbmod.current_tenant()).split(".")[0].upper()


def render(
    kind: str, context: dict[str, Any] | None = None, *, tenant_id: str | None = None
) -> str | None:
    """The body without the footer, or None when the context cannot support one.

    Returning None where a required value is missing is deliberate: a hardship
    acknowledgement that cannot say what was agreed is worse than no message,
    because it invites a reply we have nothing to answer with.
    """
    ctx = context or {}
    brand = _brand(tenant_id)

    if kind == "hardship_ack":
        until = _fmt_date(ctx.get("holdUntil"))
        if not until:
            return None
        return (
            f"{brand}: thank you for telling us about your circumstances. We have "
            f"paused collection activity on your account until {until} and a "
            "specialist will be in touch. You do not need to do anything now."
        )

    if kind == "dispute_ref":
        ref = str(ctx.get("reference") or "").strip()
        if not ref:
            return None
        return (
            f"{brand}: we have logged your dispute under reference {ref}. We will "
            "not pursue recovery of the disputed amount while it is under review "
            "and will write to you with the outcome."
        )

    if kind == "callback_confirm":
        when = _fmt_when(ctx.get("callbackAt"))
        if not when:
            return None
        return (
            f"{brand}: we have booked your call back for {when}. If that no longer "
            "suits, reply to this message and we will move it."
        )

    return None


#: The approved WhatsApp template for a kind, for a send outside Meta's 24-hour
#: window: (brand, the booked time or the reference, the grievance officer).
TEMPLATES = {
    "callback_confirm": ("WHATSAPP_CALLBACK_TEMPLATE_NAME", "WHATSAPP_CALLBACK_TEMPLATE_LANG"),
    "dispute_ref": ("WHATSAPP_DISPUTE_TEMPLATE_NAME", "WHATSAPP_DISPUTE_TEMPLATE_LANG"),
}


def _template_params(kind: str, ctx: dict[str, Any], *, tenant_id: str | None, footer: str) -> list[str]:
    value = _fmt_when(ctx.get("callbackAt")) if kind == "callback_confirm" else str(ctx.get("reference") or "")
    officer = footer.removeprefix("Grievance officer: ").rstrip(".")
    return [_brand(tenant_id), value, officer]


def _channel_blocked(conn: Any, customer_id: str, channel: str) -> bool:
    import capture
    import contact_policy

    status = capture.latest_consent_by_channel(conn, customer_id).get(channel)
    return status in contact_policy.BLOCKING_CONSENT


def _customer(conn: Any, customer_id: str) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text(
                "SELECT id, tenant_id, name, phone_primary, phone_alt, timezone "
                "FROM customers WHERE id = :id"
            ),
            {"id": customer_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def _route(
    conn: Any,
    *,
    customer_id: str,
    kind: str,
    context: dict[str, Any] | None,
    account_id: str | None,
    related_id: str | None,
    source: str,
    purpose: str,
    actor_kind: str,
) -> dict[str, Any]:
    """Compose, choose the channel, gate, and hand WhatsApp to its queue.
    Contacts nobody itself. One of::

        {"outcome": "failed", "reason": ...}                  # will not be sent
        {"outcome": "deferred", "reason": ..., "at": ...}      # admitted later
        {"outcome": "handed", "channel": "whatsapp", "message_id": ...}
        {"outcome": "send", "channel": "sms", "to": ..., "body": ..., "tenant_id": ...}
    """
    import compliance_copy
    import contact_policy
    import db as dbmod
    import promise_fulfillment as pf
    import whatsapp_outbound as wa_out

    def failed(reason: str, channel: str | None = None) -> dict[str, Any]:
        return {"outcome": "failed", "reason": reason, "channel": channel}

    customer = _customer(conn, customer_id)
    if customer is None:
        return failed("no_customer")

    # The borrower's own tenant, not the ambient one. The Closer drains a
    # queue that spans tenants, so resolving the brand and the grievance
    # officer from `current_tenant()` would eventually name one bank's
    # officer in another bank's message - which is a worse disclosure defect
    # than omitting the officer entirely.
    tenant_id = str(customer.get("tenant_id") or "") or None

    context = dict(context or {})
    at = context.get("callbackAt")
    if isinstance(at, str) and at.strip():
        at = datetime.fromisoformat(at.strip())
    if isinstance(at, datetime) and at.tzinfo is not None:
        from agent_core import clock

        # The customer's wall clock, not the instant's UTC digits.
        context["callbackAt"] = at.astimezone(clock.zone(customer.get("timezone")))

    body = render(kind, context, tenant_id=tenant_id)
    if body is None:
        return failed("insufficient_context")

    # A follow-up is a recovery communication and owes para 100AA the same
    # disclosure the voicemail and the dunning SMS owe it.
    footer = compliance_copy.written_footer(compliance_copy.tenant_contacts(tenant_id, conn=conn))
    if footer is None:
        return failed(compliance_copy.NO_GRIEVANCE_CONTACT)
    body = f"{body} {footer}"

    phone = customer.get("phone_primary")
    if not phone:
        return failed("no_phone_on_file")

    wa_blocked = _channel_blocked(conn, customer_id, "whatsapp")
    sms_blocked = _channel_blocked(conn, customer_id, "sms")
    channel = "whatsapp" if not wa_blocked else ("sms" if not sms_blocked else None)
    if channel is None:
        return failed("channel_opted_out")

    conversation_id = None
    template_name = template_lang = ""
    if channel == "whatsapp":
        conversation_id = dbmod._open_whatsapp_conversation(conn, customer_id)
        # Outside Meta's 24-hour window a freeform message is undeliverable:
        # the kind's approved template, or SMS rather than enqueue something
        # the carrier will drop.
        if not pf._inside_service_window(conn, conversation_id):
            template_name, template_lang = (
                pf.resolve_template(*TEMPLATES[kind]) if kind in TEMPLATES else ("", "")
            )
            if not template_name:
                if sms_blocked:
                    return failed("outside_service_window")
                channel = "sms"
                conversation_id = None
    if channel == "sms":
        import twilio_sms

        if not twilio_sms.configured():
            return failed("sms_not_configured", channel)

    decision = contact_policy.admit(
        conn,
        customer_id=customer_id,
        channel=channel,
        purpose=purpose,
        session_key=conversation_id or related_id,
        source=source,
        related_id=related_id,
        actor_kind=actor_kind,
        account_id=account_id,
        endpoint=phone,
    )
    if not decision.allowed:
        if decision.deferrable:
            return {"outcome": "deferred", "reason": decision.reason, "at": decision.next_allowed_at,
                    "channel": channel}
        return failed(decision.reason or "not_admitted", channel)

    if channel == "sms":
        return {"outcome": "send", "channel": "sms", "to": phone, "body": body, "tenant_id": tenant_id}
    message_id = dbmod._id("MSG")
    conn.execute(
        text(
            """
            INSERT INTO messages (id, conversation_id, sender, body,
                                  delivery_status, sent_at)
            VALUES (:id, :cid, 'bot', :body, 'sending', now())
            """
        ),
        {"id": message_id, "cid": conversation_id, "body": body},
    )
    wa_out.enqueue_agent_send(
        conn,
        message_id=message_id,
        conversation_id=conversation_id,
        customer_id=customer_id,
        to_phone=phone,
        body=body,
        preview_url=False,
        template_name=template_name or None,
        template_lang=template_lang or None,
        template_params=(_template_params(kind, context, tenant_id=tenant_id, footer=footer)
                         if template_name else None),
        purpose=purpose,
        source=source,
    )
    return {"outcome": "handed", "channel": "whatsapp", "message_id": message_id}


def send(
    conn: Any,
    *,
    customer_id: str,
    kind: str,
    context: dict[str, Any] | None = None,
    account_id: str | None = None,
    related_id: str | None = None,
    source: str = "post_call",
    purpose: str = "statutory",
) -> Written:
    """Compose, gate and enqueue one written follow-up now. Never raises.

    ``purpose`` defaults to ``statutory`` because every sendable kind here is a
    record of something the borrower and the institution just agreed, not an
    approach — closer to a receipt than to outreach. It still counts as a touch,
    which is correct: it is a message arriving on their handset.

    A Voice Studio call does not send here: it owes the copy (:func:`queue`).
    """
    result = Written(kind=kind)

    if kind in REFUSED:
        result.reason = REFUSED[kind]
        return result
    if kind not in SENDABLE:
        result.reason = "unknown_kind"
        return result

    try:
        step = _route(conn, customer_id=customer_id, kind=kind, context=context, account_id=account_id,
                      related_id=related_id, source=source, purpose=purpose, actor_kind="bot")
        result.channel = step.get("channel")
        if step["outcome"] in ("failed", "deferred"):
            result.reason = step["reason"] or "not_admitted"
            return result
        if step["outcome"] == "handed":
            result.message_id = step["message_id"]
        else:
            import twilio_sms

            sent = twilio_sms.send(
                to_phone=step["to"],
                body=step["body"],
                customer_id=customer_id,
                tenant_id=step["tenant_id"],
                related_id=related_id,
            )
            result.message_id = sent.get("sid")

        result.sent = True
        return result
    except Exception:
        logger.exception("written follow-up failed · kind=%s", kind)
        result.reason = "failed"
        return result


# ---------------------------------------------------------------------------
# Owed copies: the Voice Studio path
# ---------------------------------------------------------------------------

#: ``contact_events.source`` and ``whatsapp_outbound_jobs.source``.
QUEUE_SOURCE = "written_followup"
#: An SMS lease older than this is a send that never reported back: failed for
#: a person, never retried, since it may have gone out.
LEASE_MINUTES = 15
#: A copy still not admitted after this long is no longer a confirmation of
#: anything the customer remembers agreeing to.
GIVE_UP_AFTER = timedelta(days=3)
_SETTLE_BATCH = 20


def queue(
    conn: Any,
    *,
    customer_id: str,
    kind: str,
    related_id: str,
    context: dict[str, Any] | None = None,
    account_id: str | None = None,
) -> bool:
    """Owe the customer one written copy of this booking or reference.

    True when it is newly owed. Atomic on ``(kind, related_id)``: two tool
    calls racing on the same booking insert one row, and a repeat after the
    first is a no-op. The send happens later, in :func:`process_one`, so the
    live tool call never waits on a carrier and a refusal that expires
    (messaging hours) waits instead of dropping the copy.
    """
    import db as dbmod

    if kind not in SENDABLE or not related_id:
        return False
    tenant_id = conn.execute(
        text("SELECT tenant_id FROM customers WHERE id = :id"), {"id": customer_id}
    ).scalar()
    if tenant_id is None:
        return False
    row = conn.execute(
        text(
            """
            INSERT INTO written_followups (id, tenant_id, customer_id, account_id, kind, related_id, context)
            VALUES (:id, :tenant, :customer, :account, :kind, :related, CAST(:context AS jsonb))
            ON CONFLICT (kind, related_id) DO NOTHING
            RETURNING id
            """
        ),
        {"id": dbmod._id("WFU"), "tenant": tenant_id, "customer": customer_id, "account": account_id,
         "kind": kind, "related": related_id, "context": json.dumps(context or {}, default=str)},
    ).first()
    return row is not None


_CLAIM = text(
    """
    SELECT id, tenant_id, customer_id, account_id, kind, related_id, context, created_at
      FROM written_followups
     WHERE status = 'scheduled' AND scheduled_at <= now()
     ORDER BY scheduled_at, id
       FOR UPDATE SKIP LOCKED
     LIMIT 1
    """
)

#: Handed-off copies with an outcome: the WhatsApp job's (or Meta's receipt,
#: including a failure reported after acceptance), or an expired SMS lease.
_SETTLE = text(
    """
    SELECT w.id, w.kind, w.related_id, w.customer_id, w.channel, w.status,
           COALESCE(m.delivery_status IN ('sent','delivered','read') OR j.status = 'succeeded', false)
             AND COALESCE(m.delivery_status, '') <> 'failed' AS sent,
           CASE WHEN w.message_id IS NULL THEN 'outcome_unknown'
                ELSE COALESCE(j.error, 'whatsapp_' || COALESCE(m.delivery_status, j.status))
           END AS reason
      FROM written_followups w
      LEFT JOIN messages m ON m.id = w.message_id
      LEFT JOIN whatsapp_outbound_jobs j ON j.message_id = w.message_id
     WHERE (w.status = 'queued'
            AND (m.delivery_status IN ('sent','delivered','read','failed')
                 OR j.status IN ('succeeded','failed','dead')
                 OR (w.message_id IS NULL AND w.attempted_at < now() - make_interval(mins => :lease))))
        OR (w.status = 'sent' AND w.message_id IS NOT NULL AND m.delivery_status = 'failed')
     ORDER BY w.id
       FOR UPDATE OF w SKIP LOCKED
     LIMIT :batch
    """
)


def _finish(conn: Any, row: Mapping[str, Any], *, sent: bool, reason: str | None) -> None:
    from db_core import _activity

    reason = None if sent else (reason or "unknown")[:200]
    conn.execute(
        text(
            """
            UPDATE written_followups
               SET status = :status,
                   sent_at = CASE WHEN :sent THEN now() ELSE sent_at END,
                   failure_reason = :reason
             WHERE id = :id
            """
        ),
        {"id": row["id"], "status": "sent" if sent else "failed", "sent": sent, "reason": reason},
    )
    entity = "callback" if row["kind"] == "callback_confirm" else "dispute"
    if sent:
        _activity(conn, entity, row["related_id"], "written_confirmation_sent",
                  "Written confirmation sent", row.get("channel"), row["customer_id"])
    else:
        _activity(conn, entity, row["related_id"], "written_confirmation_failed",
                  "Written confirmation not sent", reason, row["customer_id"])


def _settle(conn: Any) -> int:
    rows = conn.execute(_SETTLE, {"lease": LEASE_MINUTES, "batch": _SETTLE_BATCH}).mappings().all()
    for row in rows:
        _finish(conn, row, sent=bool(row["sent"]), reason=row["reason"])
    return len(rows)


def _prepare(conn: Any, row: Mapping[str, Any]) -> dict[str, Any]:
    from agent_core.clock import utc_now

    context = row["context"] if isinstance(row["context"], dict) else json.loads(row["context"] or "{}")
    now = utc_now()
    if row["created_at"] < now - GIVE_UP_AFTER:
        return {"outcome": "failed", "reason": "too_late"}
    at = context.get("callbackAt")
    if row["kind"] == "callback_confirm" and at and datetime.fromisoformat(str(at)) <= now:
        return {"outcome": "failed", "reason": "callback_passed"}
    import tenant_context

    # The row's tenant: the drain spans tenants, and the gate and the copy
    # (brand, grievance officer) are the customer's.
    with tenant_context.bind(row["tenant_id"]):
        return _route(conn, customer_id=row["customer_id"], kind=row["kind"], context=context,
                      account_id=row["account_id"], related_id=row["related_id"],
                      source=QUEUE_SOURCE, purpose="statutory", actor_kind="system")


def process_one(engine: Any) -> bool:
    """Settle handed-off copies, then send one that is due. True if either did work."""
    with engine.begin() as conn:
        settled = _settle(conn)
        row = conn.execute(_CLAIM).mappings().first()
        if row is None:
            return settled > 0
        row = dict(row)
        try:
            with conn.begin_nested():
                step = _prepare(conn, row)
        except Exception as exc:
            logger.exception("written follow-up %s could not be prepared", row["id"])
            step = {"outcome": "failed", "reason": type(exc).__name__}
        row["channel"] = step.get("channel")
        if step["outcome"] == "failed":
            _finish(conn, row, sent=False, reason=step["reason"])
            return True
        if step["outcome"] == "deferred":
            conn.execute(
                text("UPDATE written_followups SET scheduled_at = :at, failure_reason = :r WHERE id = :id"),
                {"id": row["id"], "at": step["at"], "r": step["reason"]},
            )
            return True
        conn.execute(
            text(
                "UPDATE written_followups SET status = 'queued', attempted_at = now(), channel = :ch, "
                "message_id = :mid, failure_reason = NULL WHERE id = :id"
            ),
            {"id": row["id"], "ch": step["channel"], "mid": step.get("message_id")},
        )
        if step["outcome"] == "handed":
            return True

    import twilio_sms

    try:
        twilio_sms.send(
            to_phone=step["to"],
            body=step["body"],
            customer_id=row["customer_id"],
            tenant_id=step["tenant_id"],
            related_id=row["id"],
        )
        sent, reason = True, None
    except Exception as exc:
        # Our own refusals are ValueError codes; a carrier's text can carry
        # the number, so it is reduced to its type.
        logger.warning("written follow-up %s not sent", row["id"], exc_info=True)
        sent, reason = False, str(exc) if isinstance(exc, ValueError) else type(exc).__name__
    with engine.begin() as conn:
        _finish(conn, row, sent=sent, reason=reason)
    return True


def for_outcome(
    conn: Any,
    *,
    customer_id: str,
    business: str | None,
    context: dict[str, Any] | None = None,
    account_id: str | None = None,
    related_id: str | None = None,
) -> Written:
    """Map a business outcome to its follow-up kind and send it."""
    kind = BY_OUTCOME.get(str(business or ""))
    if kind is None:
        return Written(kind="none", reason="no_followup_for_outcome")
    return send(
        conn,
        customer_id=customer_id,
        kind=kind,
        context=context,
        account_id=account_id,
        related_id=related_id,
    )
