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

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

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


def _channel_blocked(conn: Any, customer_id: str, channel: str) -> bool:
    import capture
    import contact_policy

    status = capture.latest_consent_by_channel(conn, customer_id).get(channel)
    return status in contact_policy.BLOCKING_CONSENT


def _customer(conn: Any, customer_id: str) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text(
                "SELECT id, tenant_id, name, phone_primary, phone_alt "
                "FROM customers WHERE id = :id"
            ),
            {"id": customer_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


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
    """Compose, gate and enqueue one written follow-up. Never raises.

    ``purpose`` defaults to ``statutory`` because every sendable kind here is a
    record of something the borrower and the institution just agreed, not an
    approach — closer to a receipt than to outreach. It still counts as a touch,
    which is correct: it is a message arriving on their handset.
    """
    result = Written(kind=kind)

    if kind in REFUSED:
        result.reason = REFUSED[kind]
        return result
    if kind not in SENDABLE:
        result.reason = "unknown_kind"
        return result

    try:
        import compliance_copy
        import contact_policy
        import db as dbmod
        import promise_fulfillment as pf
        import whatsapp_outbound as wa_out

        customer = _customer(conn, customer_id)
        if customer is None:
            result.reason = "no_customer"
            return result

        # The borrower's own tenant, not the ambient one. The Closer drains a
        # queue that spans tenants, so resolving the brand and the grievance
        # officer from `current_tenant()` would eventually name one bank's
        # officer in another bank's message - which is a worse disclosure defect
        # than omitting the officer entirely.
        tenant_id = str(customer.get("tenant_id") or "") or None

        body = render(kind, context, tenant_id=tenant_id)
        if body is None:
            result.reason = "insufficient_context"
            return result

        # A follow-up is a recovery communication and owes para 100AA the same
        # disclosure the voicemail and the dunning SMS owe it.
        footer = compliance_copy.written_footer(compliance_copy.tenant_contacts(tenant_id))
        if footer is None:
            result.reason = compliance_copy.NO_GRIEVANCE_CONTACT
            return result
        body = f"{body} {footer}"

        phone = customer.get("phone_primary") or customer.get("phone_alt")
        if not phone:
            result.reason = "no_phone_on_file"
            return result

        wa_blocked = _channel_blocked(conn, customer_id, "whatsapp")
        sms_blocked = _channel_blocked(conn, customer_id, "sms")
        channel = "whatsapp" if not wa_blocked else ("sms" if not sms_blocked else None)
        if channel is None:
            result.reason = "channel_opted_out"
            return result

        conversation_id = None
        if channel == "whatsapp":
            conversation_id = dbmod._open_whatsapp_conversation(conn, customer_id)
            # Outside Meta's 24-hour window a freeform message is undeliverable
            # and there is no approved template for these kinds, so fall to SMS
            # rather than enqueue something the carrier will drop.
            if not pf._inside_service_window(conn, conversation_id):
                if sms_blocked:
                    result.reason = "outside_service_window"
                    return result
                channel = "sms"
                conversation_id = None

        decision = contact_policy.admit(
            conn,
            customer_id=customer_id,
            channel=channel,
            purpose=purpose,
            session_key=conversation_id or related_id,
            source=source,
            related_id=related_id,
            actor_kind="bot",
            account_id=account_id,
        )
        if not decision.allowed:
            result.channel = channel
            result.reason = decision.reason or "not_admitted"
            return result

        if channel == "whatsapp":
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
                purpose=purpose,
                source=source,
            )
            result.message_id = message_id
        else:
            import twilio_sms

            if not twilio_sms.configured():
                result.channel = channel
                result.reason = "sms_not_configured"
                return result
            sent = twilio_sms.send(
                to_phone=phone,
                body=body,
                customer_id=customer_id,
                tenant_id=customer.get("tenant_id"),
                related_id=related_id,
            )
            result.message_id = sent.get("sid")

        result.sent = True
        result.channel = channel
        return result
    except Exception:
        logger.exception("written follow-up failed · kind=%s", kind)
        result.reason = "failed"
        return result


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
