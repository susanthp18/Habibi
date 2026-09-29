"""Callback reminders: delivered by the system, or recorded as not sent.

Nothing read ``callback_reminders`` to deliver them. The client posted
``status: "sent"``, the callback moved to ``reminded``, the timeline said
"Callback reminder sent", and nobody was contacted. This is the drain that
sends them, a ``bot_worker`` stage beside the promise reminders.

A due reminder is claimed and decided in one transaction that contacts nobody:
the callback must still be open and its window not over, the channel one we
send on, a number on file, a grievance officer to name, and
``contact_policy.require_admit`` must say yes. The purpose is ``outreach`` -- a
reminder goes out at a time we chose, so caps and cooling-off bind. A refusal is
``failed`` with its reason, not retried: it was due now, and later is a message
about a call that may already have happened.

* **WhatsApp** goes through ``whatsapp_outbound`` like every agent send, and
  only inside Meta's 24-hour window: there is no approved template for this
  text, and a freeform message outside the window is one Meta drops. The row
  waits at ``queued`` and becomes ``sent`` when that job succeeds.
* **SMS** takes a lease (``attempted_at``), commits, and calls Twilio with
  nothing locked -- ``process_one_reminder`` learnt that a carrier call under
  the row lock turns one message into two.

``sent`` is written only after a provider accepted the message. The copy is
fixed, as in ``written_followup``: no model writes it.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: ``contact_events.source`` and ``whatsapp_outbound_jobs.source``.
SOURCE = "callback_reminder"
#: The callback states a reminder is still owed in.
OPEN = ("scheduled", "rescheduled", "reminded")
#: An SMS lease older than this is a send that never reported back. It is
#: failed for a person, never retried: it may have gone out.
LEASE_MINUTES = 15
_SETTLE_BATCH = 20

_CLAIM = text(
    """
    SELECT r.id, r.callback_id, r.channel,
           cb.customer_id, cb.account_id, cb.status AS callback_status,
           cb.scheduled_at AS callback_at,
           cb.scheduled_at + make_interval(mins => COALESCE(cb.window_mins, 30)) <= now()
             AS callback_over
      FROM callback_reminders r
      JOIN callbacks cb ON cb.id = r.callback_id
     WHERE r.status = 'scheduled' AND r.scheduled_at <= now()
     ORDER BY r.scheduled_at, r.id
       FOR UPDATE OF r SKIP LOCKED
     LIMIT 1
    """
)

# A handed-off reminder is settled when its WhatsApp job has an outcome, or
# when its SMS lease has expired. Accepted by the provider is `sent`, even if a
# later delivery receipt says otherwise.
_SETTLE = text(
    """
    SELECT r.id, r.callback_id, r.channel, cb.customer_id,
           COALESCE(m.delivery_status IN ('sent', 'delivered', 'read')
                    OR j.status = 'succeeded', false) AS sent,
           CASE WHEN r.message_id IS NULL THEN 'outcome_unknown'
                ELSE COALESCE(j.error, 'whatsapp_' || COALESCE(j.status, m.delivery_status))
           END AS reason
      FROM callback_reminders r
      JOIN callbacks cb ON cb.id = r.callback_id
      LEFT JOIN messages m ON m.id = r.message_id
      LEFT JOIN whatsapp_outbound_jobs j ON j.message_id = r.message_id
     WHERE r.status = 'queued'
       AND (m.delivery_status IN ('sent', 'delivered', 'read', 'failed')
            OR j.status IN ('succeeded', 'failed', 'dead')
            OR (r.message_id IS NULL
                AND r.attempted_at < now() - make_interval(mins => :lease)))
     ORDER BY r.id
       FOR UPDATE OF r SKIP LOCKED
     LIMIT :batch
    """
)


def render(conn: Any, *, callback_at: datetime, timezone: str | None, tenant_id: str | None) -> str | None:
    """The reminder text, or None when the tenant has no grievance officer."""
    import compliance_copy
    import written_followup
    from agent_core import clock

    footer = compliance_copy.written_footer(compliance_copy.tenant_contacts(tenant_id, conn=conn))
    if footer is None:
        return None
    when = written_followup._fmt_when(callback_at.astimezone(clock.zone(timezone)))
    return f"{written_followup._brand(tenant_id)}: a reminder that we will call you on {when}. {footer}"


def _whatsapp_thread(conn: Any, customer_id: str) -> str | None:
    """The thread ``_open_whatsapp_conversation`` would pick -- never a new one.

    No thread means no inbound message, so no service window: opening one here
    would file an empty conversation and an active interaction for nothing.
    """
    return conn.execute(
        text(
            "SELECT id FROM conversations WHERE customer_id = :cid AND channel = 'whatsapp' "
            "ORDER BY COALESCE(updated_at, created_at) DESC, id LIMIT 1"
        ),
        {"cid": customer_id},
    ).scalar()


def _refusal(conn: Any, reminder: Mapping[str, Any], phone: str, *, session_key: str | None) -> str | None:
    """The contact policy's reason to refuse this send, or None when admitted."""
    import contact_policy

    try:
        contact_policy.require_admit(
            conn,
            customer_id=reminder["customer_id"],
            channel=reminder["channel"],
            purpose="outreach",
            session_key=session_key,
            source=SOURCE,
            related_id=reminder["id"],
            actor_kind="system",
            account_id=reminder["account_id"],
            endpoint=phone,
        )
    except ValueError as refused:
        return str(refused)
    return None


def _prepare(conn: Any, reminder: Mapping[str, Any]) -> dict[str, Any]:
    """Decide one claimed reminder. Contacts nobody.

    ``{"outcome": "failed", "reason": ...}``, ``{"outcome": "queued"}`` (handed
    to whatsapp_outbound), or ``{"outcome": "send", ...}`` (an SMS to send after
    the claim commits).
    """
    import compliance_copy
    import contact_policy

    def failed(reason: str) -> dict[str, Any]:
        return {"outcome": "failed", "reason": reason}

    if reminder["callback_status"] not in OPEN:
        return failed(f"callback_{reminder['callback_status']}")
    if reminder["callback_over"]:
        return failed("callback_passed")
    channel = reminder["channel"]
    if channel not in ("whatsapp", "sms"):
        return failed("channel_unsupported")
    customer = (
        conn.execute(
            text("SELECT tenant_id, timezone, phone_primary FROM customers WHERE id = :id"),
            {"id": reminder["customer_id"]},
        )
        .mappings()
        .first()
    )
    phone = contact_policy.chosen_phone(customer)
    if customer is None or not phone:
        return failed("no_phone_on_file")
    body = render(
        conn,
        callback_at=reminder["callback_at"],
        timezone=customer["timezone"],
        tenant_id=customer["tenant_id"],
    )
    if body is None:
        return failed(compliance_copy.NO_GRIEVANCE_CONTACT)

    if channel == "sms":
        import twilio_sms

        if not twilio_sms.configured():
            return failed("sms_not_configured")
        refused = _refusal(conn, reminder, phone, session_key=None)
        if refused:
            return failed(refused)
        return {"outcome": "send", "to": phone, "body": body, "tenant_id": customer["tenant_id"]}

    import db as dbmod
    import promise_fulfillment as pf
    import whatsapp_outbound

    conversation_id = _whatsapp_thread(conn, reminder["customer_id"])
    if conversation_id is None or not pf._inside_service_window(conn, conversation_id):
        return failed("outside_service_window")
    # The conversation is the session key whatsapp_outbound re-admits the job
    # under, so its second check at send time is the same touch.
    refused = _refusal(conn, reminder, phone, session_key=conversation_id)
    if refused:
        return failed(refused)

    message_id = dbmod._id("MSG")
    conn.execute(
        text(
            """
            INSERT INTO messages (id, conversation_id, sender, body, delivery_status, sent_at)
            VALUES (:id, :cid, 'bot', :body, 'sending', now())
            """
        ),
        {"id": message_id, "cid": conversation_id, "body": body},
    )
    whatsapp_outbound.enqueue_agent_send(
        conn,
        message_id=message_id,
        conversation_id=conversation_id,
        customer_id=reminder["customer_id"],
        to_phone=phone,
        body=body,
        purpose="outreach",
        source=SOURCE,
    )
    conn.execute(
        text(
            "UPDATE callback_reminders SET status = 'queued', attempted_at = now(), "
            "message_id = :mid WHERE id = :id"
        ),
        {"id": reminder["id"], "mid": message_id},
    )
    return {"outcome": "queued"}


def _finish(conn: Any, reminder: Mapping[str, Any], *, sent: bool, reason: str | None) -> None:
    """The outcome on the row, the callback and its timeline."""
    from db_core import _activity

    reason = None if sent else (reason or "unknown")[:200]
    conn.execute(
        text(
            """
            UPDATE callback_reminders
               SET status = :status,
                   sent_at = CASE WHEN :sent THEN now() ELSE sent_at END,
                   failure_reason = :reason
             WHERE id = :id
            """
        ),
        {"id": reminder["id"], "status": "sent" if sent else "failed", "sent": sent, "reason": reason},
    )
    channel = reminder["channel"]
    if sent:
        conn.execute(
            text(
                "UPDATE callbacks SET status = 'reminded' "
                "WHERE id = :id AND status IN ('scheduled', 'rescheduled')"
            ),
            {"id": reminder["callback_id"]},
        )
        _activity(conn, "callback", reminder["callback_id"], "callback_reminder_sent",
                  "Callback reminder sent", channel, reminder["customer_id"])
    else:
        _activity(conn, "callback", reminder["callback_id"], "callback_reminder_failed",
                  "Callback reminder not sent", f"{channel}: {reason}", reminder["customer_id"])


def _settle(conn: Any) -> int:
    rows = conn.execute(_SETTLE, {"lease": LEASE_MINUTES, "batch": _SETTLE_BATCH}).mappings().all()
    for row in rows:
        _finish(conn, row, sent=bool(row["sent"]), reason=row["reason"])
    return len(rows)


def process_one(engine: Any) -> bool:
    """Settle handed-off reminders, then send one that is due. True if either did work."""
    with engine.begin() as conn:
        settled = _settle(conn)
        row = conn.execute(_CLAIM).mappings().first()
        if row is None:
            return settled > 0
        reminder = dict(row)
        try:
            with conn.begin_nested():
                step = _prepare(conn, reminder)
        except Exception as exc:
            # Recorded, so a reminder that cannot be decided is not retried
            # on every tick.
            logger.exception("callback reminder %s could not be prepared", reminder["id"])
            step = {"outcome": "failed", "reason": type(exc).__name__}
        if step["outcome"] == "failed":
            _finish(conn, reminder, sent=False, reason=step["reason"])
        if step["outcome"] != "send":
            return True
        conn.execute(
            text("UPDATE callback_reminders SET status = 'queued', attempted_at = now() WHERE id = :id"),
            {"id": reminder["id"]},
        )

    import twilio_sms

    try:
        twilio_sms.send(
            to_phone=step["to"],
            body=step["body"],
            customer_id=reminder["customer_id"],
            tenant_id=step["tenant_id"],
            related_id=reminder["id"],
        )
        sent, reason = True, None
    except Exception as exc:
        # Our own refusals are ValueError codes; a carrier's text can carry
        # the number, so it is reduced to its type.
        logger.warning("callback reminder %s not sent", reminder["id"], exc_info=True)
        sent, reason = False, str(exc) if isinstance(exc, ValueError) else type(exc).__name__
    with engine.begin() as conn:
        _finish(conn, reminder, sent=sent, reason=reason)
    return True
