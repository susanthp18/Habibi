"""PTP fulfillment engine — veto, then act, then log.

The model records a promise. This module creates (or reuses) a payment intent,
picks a channel the customer has not opted out of, enqueues a written confirm
with a pay link, and schedules the due-date reminder. It never invents a URL
for the LLM to read aloud, and it never blocks the voice thread on Meta Graph.
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Engine

import webhooks_dispatch
from env_loader import load_env

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
BLOCKING_CONSENT = frozenset({"opted_out", "dnd", "expired"})
OPEN_INTENT = ("created", "sent", "opened")


def _env(name: str, default: str = "") -> str:
    load_env()
    return (os.getenv(name) or default).strip()


# Meta templates: purpose-specific first, then the documented fallback.
#
# .env.example has documented WHATSAPP_FALLBACK_TEMPLATE_NAME / _LANG since the
# WhatsApp block was written and nothing read either of them. An operator
# working down that file configured a fallback, believed outside-the-24h-window
# sends were covered, and got no template at all — those sends simply failed.
#
# The three purposes (PTP confirm, bounce notice, treatment nudge) each have
# their own var and each keeps priority. The fallback only fills the gap, and a
# template's language travels with the template that was actually chosen: using
# the fallback's language for a purpose-specific template would be a second,
# quieter bug.
FALLBACK_TEMPLATE_NAME_ENV = "WHATSAPP_FALLBACK_TEMPLATE_NAME"
FALLBACK_TEMPLATE_LANG_ENV = "WHATSAPP_FALLBACK_TEMPLATE_LANG"


def resolve_template(name_env: str, lang_env: str) -> tuple[str, str]:
    """(template_name, language) for a purpose, or ("", "") if neither is set.

    Resolution order is purpose var, then fallback var, then nothing. Callers
    that only need to know *whether* a template exists read the name; callers
    that are about to send read both, because the pair has to come from the
    same template.

    The fallback must be registered in WhatsApp Manager with the same body
    parameters as the purpose template it stands in for — the three purposes
    take different params — or Meta rejects the send. That constraint is stated
    in .env.example next to the vars.
    """
    name = _env(name_env)
    if name:
        return name, (_env(lang_env) or "en_US")
    fallback = _env(FALLBACK_TEMPLATE_NAME_ENV)
    if fallback:
        return fallback, (_env(FALLBACK_TEMPLATE_LANG_ENV) or "en_US")
    return "", ""


@dataclass
class FulfillmentResult:
    promise_id: str
    intent_id: str | None = None
    confirm_channel: str | None = None
    phone_last4: str | None = None
    pay_link_sent: bool = False
    suppressed: bool = False
    suppression_reason: str | None = None
    spoken_summary: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "promiseId": self.promise_id,
            "intentId": self.intent_id,
            "confirmChannel": self.confirm_channel,
            "phoneLast4": self.phone_last4,
            "payLinkSent": self.pay_link_sent,
            "suppressed": self.suppressed,
            "suppressionReason": self.suppression_reason,
        }


def _phone_last4(phone: str | None) -> str | None:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else (digits or None)


def _fmt_inr(amount: Any) -> str:
    try:
        n = Decimal(str(amount)).quantize(Decimal("0.01"))
    except Exception:
        return str(amount)
    if n == n.to_integral():
        return f"{int(n):,}"
    return f"{n:,}"


def _promised_date_ist(promised_at: datetime) -> datetime.date:
    if promised_at.tzinfo is None:
        promised_at = promised_at.replace(tzinfo=timezone.utc)
    return promised_at.astimezone(IST).date()


def _intent_expiry(promised_at: datetime, *, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    promised_day = _promised_date_ist(promised_at)
    today = now.astimezone(IST).date()
    if promised_day <= today:
        return now + timedelta(minutes=30)
    # End of promised day IST + 1 day.
    end = datetime(promised_day.year, promised_day.month, promised_day.day, 23, 59, 59, tzinfo=IST)
    return (end + timedelta(days=1)).astimezone(timezone.utc)


def _due_reminder_at(promised_at: datetime) -> datetime:
    day = _promised_date_ist(promised_at)
    return datetime(day.year, day.month, day.day, 8, 15, tzinfo=IST).astimezone(timezone.utc)


def _load_promise(conn: Any, promise_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT p.id, p.customer_id, p.account_id, p.interaction_id, p.amount,
                   p.promised_at, p.status, p.paid_amount, p.channel,
                   c.tenant_id, c.name AS customer_name, c.phone_primary, c.phone_alt,
                   c.dnd, a.outstanding
            FROM promises p
            JOIN customers c ON c.id = p.customer_id
            JOIN accounts a ON a.id = p.account_id
            WHERE p.id = :id
            """
        ),
        {"id": promise_id},
    ).mappings().first()
    return dict(row) if row else None


def _channel_blocked(consent: dict[str, str], channel: str) -> bool:
    status = (consent.get(channel) or "").lower()
    return status in BLOCKING_CONSENT


def _last_customer_inbound_at(conn: Any, conversation_id: str) -> datetime | None:
    row = conn.execute(
        text(
            """
            SELECT COALESCE(sent_at, created_at) AS at
            FROM messages
            WHERE conversation_id = :cid AND sender = 'customer'
            ORDER BY COALESCE(sent_at, created_at) DESC
            LIMIT 1
            """
        ),
        {"cid": conversation_id},
    ).mappings().first()
    if not row or row["at"] is None:
        return None
    at = row["at"]
    if getattr(at, "tzinfo", None) is None:
        at = at.replace(tzinfo=timezone.utc)
    return at


def _inside_service_window(conn: Any, conversation_id: str, *, now: datetime | None = None) -> bool:
    last = _last_customer_inbound_at(conn, conversation_id)
    if last is None:
        return False
    now = now or datetime.now(timezone.utc)
    return (now - last) <= timedelta(hours=24)


def _confirm_copy(*, amount: Any, promised_at: datetime, pay_url: str, expires_at: datetime | None) -> str:
    date_s = _promised_date_ist(promised_at).strftime("%d %b %Y")
    rupees = _fmt_inr(amount)
    expiry = ""
    if expires_at is not None:
        exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
        expiry = f" This link is valid until {exp.astimezone(IST).strftime('%d %b %Y, %I:%M %p IST')}."
    return (
        f"We've recorded your promise to pay ₹{rupees} by {date_s}. "
        f"Pay securely here: {pay_url}.{expiry} Do not share this link."
    )


def _spoken(*, amount: Any, promised_at: datetime, channel: str | None, last4: str | None, suppressed: bool) -> str:
    date_s = _promised_date_ist(promised_at).strftime("%d %B")
    rupees = _fmt_inr(amount)
    if suppressed or not channel:
        return (
            f"I've recorded a promise of {rupees} rupees by {date_s}. "
            "I could not send a payment link because messaging is opted out. "
            "An agent will follow up."
        )
    dest = f"ending {last4}" if last4 else "on file"
    if channel == "whatsapp":
        return (
            f"I've recorded {rupees} rupees by {date_s} and sent a payment link "
            f"to WhatsApp {dest}."
        )
    return (
        f"I've recorded {rupees} rupees by {date_s} and sent a payment link "
        f"by SMS to the number {dest}."
    )


def create_pay_intent(
    conn: Any,
    *,
    tenant_id: str,
    customer_id: str,
    account_id: str,
    amount: Decimal,
    expires_at: datetime,
    promise_id: str | None = None,
    payment_event_id: str | None = None,
    interaction_id: str | None = None,
) -> dict[str, Any]:
    """Create or reuse one open hosted intent for a promise or a bounce event."""
    import db as dbmod
    import payments

    if promise_id:
        existing = conn.execute(
            text(
                """
                SELECT * FROM payment_intents
                WHERE promise_id = :pid AND status = ANY(:statuses)
                ORDER BY created_at DESC
                LIMIT 1
                FOR UPDATE
                """
            ),
            {"pid": promise_id, "statuses": list(OPEN_INTENT)},
        ).mappings().first()
        if existing:
            return dict(existing)
    if payment_event_id:
        existing = conn.execute(
            text(
                """
                SELECT * FROM payment_intents
                WHERE payment_event_id = :eid AND status = ANY(:statuses)
                ORDER BY created_at DESC
                LIMIT 1
                FOR UPDATE
                """
            ),
            {"eid": payment_event_id, "statuses": list(OPEN_INTENT)},
        ).mappings().first()
        if existing:
            return dict(existing)

    token = secrets.token_urlsafe(24)
    intent_id = dbmod._id("PI")
    pay_url = payments.checkout_url(token)
    try:
        conn.execute(
            text(
                """
                INSERT INTO payment_intents (
                  id, tenant_id, customer_id, account_id, promise_id, interaction_id,
                  payment_event_id, amount, currency, public_token, status, provider,
                  pay_url, expires_at
                ) VALUES (
                  :id, :tenant_id, :customer_id, :account_id, :promise_id, :interaction_id,
                  :payment_event_id, :amount, 'INR', :public_token, 'created', :provider,
                  :pay_url, :expires_at
                )
                """
            ),
            {
                "id": intent_id,
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "account_id": account_id,
                "promise_id": promise_id,
                "interaction_id": interaction_id,
                "payment_event_id": payment_event_id,
                "amount": float(amount),
                "public_token": token,
                "provider": payments.provider(),
                "pay_url": pay_url,
                "expires_at": expires_at,
            },
        )
    except Exception:
        logger.debug(
            "payment_intent insert raced promise=%s event=%s",
            promise_id,
            payment_event_id,
            exc_info=True,
        )
        raced = None
        if promise_id:
            raced = conn.execute(
                text(
                    """
                    SELECT * FROM payment_intents
                    WHERE promise_id = :pid AND status = ANY(:statuses)
                    ORDER BY created_at DESC
                    LIMIT 1
                    FOR UPDATE
                    """
                ),
                {"pid": promise_id, "statuses": list(OPEN_INTENT)},
            ).mappings().first()
        elif payment_event_id:
            raced = conn.execute(
                text(
                    """
                    SELECT * FROM payment_intents
                    WHERE payment_event_id = :eid AND status = ANY(:statuses)
                    ORDER BY created_at DESC
                    LIMIT 1
                    FOR UPDATE
                    """
                ),
                {"eid": payment_event_id, "statuses": list(OPEN_INTENT)},
            ).mappings().first()
        if raced:
            return dict(raced)
        raise
    row = conn.execute(
        text("SELECT * FROM payment_intents WHERE id = :id FOR UPDATE"),
        {"id": intent_id},
    ).mappings().first()
    return dict(row)


def _get_or_create_intent(conn: Any, promise: dict[str, Any]) -> dict[str, Any]:
    outstanding = Decimal(str(promise.get("outstanding") or 0))
    amount = Decimal(str(promise["amount"]))
    if outstanding > 0:
        amount = min(amount, outstanding)
    return create_pay_intent(
        conn,
        tenant_id=promise["tenant_id"],
        customer_id=promise["customer_id"],
        account_id=promise["account_id"],
        amount=amount,
        expires_at=_intent_expiry(promise["promised_at"]),
        promise_id=promise["id"],
        interaction_id=promise.get("interaction_id"),
    )


def _schedule_due_reminder(conn: Any, promise: dict[str, Any], channel: str) -> None:
    import db as dbmod

    promised_day = _promised_date_ist(promise["promised_at"])
    today = datetime.now(timezone.utc).astimezone(IST).date()
    if promised_day <= today:
        return
    exists = conn.execute(
        text(
            """
            SELECT 1 FROM promise_reminders
            WHERE promise_id = :pid AND kind = 'due'
            LIMIT 1
            """
        ),
        {"pid": promise["id"]},
    ).fetchone()
    if exists:
        return
    conn.execute(
        text(
            """
            INSERT INTO promise_reminders (
              id, promise_id, channel, kind, scheduled_at, status
            ) VALUES (
              :id, :promise_id, :channel, 'due', :scheduled_at, 'scheduled'
            )
            """
        ),
        {
            "id": dbmod._id("PRM"),
            "promise_id": promise["id"],
            "channel": channel if channel in {"whatsapp", "sms"} else "whatsapp",
            "scheduled_at": _due_reminder_at(promise["promised_at"]),
        },
    )


def enqueue_whatsapp_paylink(
    conn: Any,
    *,
    customer_id: str,
    intent: dict[str, Any],
    to_phone: str,
    body: str,
    use_template: bool,
    purpose: str = "statutory",
    source: str = "ptp_confirm",
    template_env_name: str = "WHATSAPP_PTP_TEMPLATE_NAME",
    template_env_lang: str = "WHATSAPP_PTP_TEMPLATE_LANG",
    template_params: list[str] | None = None,
) -> None:
    """Queue a pay-link WhatsApp (PTP confirm or bounce notice)."""
    import db as dbmod
    import whatsapp_outbound as wa_out

    conversation_id = dbmod._open_whatsapp_conversation(conn, customer_id)
    message_id = dbmod._id("MSG")
    conn.execute(
        text(
            """
            INSERT INTO messages (id, conversation_id, sender, body, delivery_status, sent_at)
            VALUES (:id, :conversation_id, 'bot', :body, 'sending', now())
            """
        ),
        {"id": message_id, "conversation_id": conversation_id, "body": body},
    )
    template_name, template_lang = (
        resolve_template(template_env_name, template_env_lang) if use_template else ("", "")
    )
    params = template_params
    if use_template and template_name and params is None:
        params = [_fmt_inr(intent["amount"]), intent["pay_url"]]
    wa_out.enqueue_agent_send(
        conn,
        message_id=message_id,
        conversation_id=conversation_id,
        customer_id=customer_id,
        to_phone=to_phone,
        body=body,
        preview_url=not use_template,
        template_name=template_name or None,
        template_lang=template_lang or None,
        template_params=params,
        purpose=purpose,
        source=source,
    )


def _enqueue_whatsapp(
    conn: Any,
    *,
    promise: dict[str, Any],
    intent: dict[str, Any],
    to_phone: str,
    body: str,
    use_template: bool,
    purpose: str = "statutory",
    source: str = "ptp_confirm",
) -> None:
    date_s = _promised_date_ist(promise["promised_at"]).isoformat()
    params = [_fmt_inr(intent["amount"]), date_s, intent["pay_url"]] if use_template else None
    enqueue_whatsapp_paylink(
        conn,
        customer_id=promise["customer_id"],
        intent=intent,
        to_phone=to_phone,
        body=body,
        use_template=use_template,
        purpose=purpose,
        source=source,
        template_params=params,
    )


def _enqueue_sms_reminder(
    conn: Any,
    *,
    promise: dict[str, Any],
    body: str,
    resend: bool,
) -> None:
    import db as dbmod

    if not resend:
        existing = conn.execute(
            text(
                """
                SELECT id FROM promise_reminders
                WHERE promise_id = :pid AND kind = 'confirm'
                  AND status IN ('queued','scheduled','sent')
                LIMIT 1
                """
            ),
            {"pid": promise["id"]},
        ).fetchone()
        if existing:
            return
    conn.execute(
        text(
            """
            INSERT INTO promise_reminders (
              id, promise_id, channel, kind, scheduled_at, status
            ) VALUES (
              :id, :promise_id, 'sms', 'confirm', now(), 'queued'
            )
            """
        ),
        {"id": dbmod._id("PRM"), "promise_id": promise["id"]},
    )
    # Body lives on the intent pay_url path; drain reads the open intent.
    _ = body


def fulfill(conn: Any, promise_id: str, *, resend: bool = False) -> FulfillmentResult:
    """Create/reuse an open intent and enqueue a written confirm.

    Send failures are recorded on the intent; they do not raise. The promise
    row must already exist in this transaction.
    """
    import capture
    import db as dbmod

    promise = _load_promise(conn, promise_id)
    if promise is None:
        raise KeyError("promise_not_found")

    intent = _get_or_create_intent(conn, promise)
    result = FulfillmentResult(promise_id=promise_id, intent_id=intent["id"])

    if intent["status"] == "paid":
        result.pay_link_sent = True
        result.confirm_channel = intent.get("confirm_channel")
        result.phone_last4 = intent.get("phone_last4")
        result.spoken_summary = _spoken(
            amount=promise["amount"],
            promised_at=promise["promised_at"],
            channel=result.confirm_channel,
            last4=result.phone_last4,
            suppressed=False,
        )
        return result

    already_sent = intent["status"] in {"sent", "opened"} and not resend
    consent = capture.latest_consent_by_channel(conn, promise["customer_id"])
    phone = promise.get("phone_primary") or promise.get("phone_alt")
    last4 = _phone_last4(phone)
    body = _confirm_copy(
        amount=intent["amount"],
        promised_at=promise["promised_at"],
        pay_url=intent["pay_url"],
        expires_at=intent.get("expires_at"),
    )

    channel: str | None = None
    reason: str | None = None
    wa_blocked = _channel_blocked(consent, "whatsapp")
    sms_blocked = _channel_blocked(consent, "sms")

    if not phone:
        reason = "no_phone_on_file"
    elif not wa_blocked:
        channel = "whatsapp"
    elif not sms_blocked:
        channel = "sms"
    else:
        reason = "channel_opted_out"

    if already_sent:
        result.confirm_channel = intent.get("confirm_channel") or channel
        result.phone_last4 = intent.get("phone_last4") or last4
        result.pay_link_sent = intent["status"] in {"sent", "opened", "paid"}
        result.suppressed = bool(intent.get("suppression_reason"))
        result.suppression_reason = intent.get("suppression_reason")
        result.spoken_summary = _spoken(
            amount=promise["amount"],
            promised_at=promise["promised_at"],
            channel=result.confirm_channel,
            last4=result.phone_last4,
            suppressed=result.suppressed,
        )
        _schedule_due_reminder(conn, promise, result.confirm_channel or "whatsapp")
        return result

    import contact_policy

    def _admit_channel(ch: str) -> contact_policy.Decision:
        session_key = promise_id
        if ch == "whatsapp":
            session_key = dbmod._open_whatsapp_conversation(conn, promise["customer_id"])
        return contact_policy.admit(
            conn,
            customer_id=promise["customer_id"],
            channel=ch,
            purpose="statutory",
            session_key=session_key,
            source="ptp_confirm",
            related_id=intent["id"],
            actor_kind="bot",
            account_id=promise.get("account_id"),
        )

    if channel is not None:
        decision = _admit_channel(channel)
        if not decision.allowed:
            if channel == "whatsapp" and not sms_blocked:
                channel = "sms"
                decision = _admit_channel("sms")
                if not decision.allowed:
                    channel = None
                    reason = decision.reason or "channel_opted_out"
            else:
                channel = None
                reason = decision.reason or "channel_opted_out"

    if channel is None:
        result.suppressed = True
        result.suppression_reason = reason or "channel_opted_out"
        result.phone_last4 = last4
        conn.execute(
            text(
                """
                UPDATE payment_intents
                SET suppression_reason = :reason, phone_last4 = :last4
                WHERE id = :id
                """
            ),
            {"id": intent["id"], "reason": result.suppression_reason, "last4": last4},
        )
        dbmod.record_activity(
            conn,
            "promise",
            promise_id,
            "promise_confirmed",
            "Payment link suppressed",
            result.suppression_reason,
            promise["customer_id"],
        )
        result.spoken_summary = _spoken(
            amount=promise["amount"],
            promised_at=promise["promised_at"],
            channel=None,
            last4=last4,
            suppressed=True,
        )
        _schedule_due_reminder(conn, promise, "whatsapp")
        return result

    sent = False
    try:
        if channel == "whatsapp":
            conversation_id = dbmod._open_whatsapp_conversation(conn, promise["customer_id"])
            inside = _inside_service_window(conn, conversation_id)
            # Only the name matters here: this decides whether a template
            # send is possible at all, and it must agree with what
            # enqueue_whatsapp_paylink will resolve a moment later.
            template_name = resolve_template(
                "WHATSAPP_PTP_TEMPLATE_NAME", "WHATSAPP_PTP_TEMPLATE_LANG"
            )[0]
            if inside:
                _enqueue_whatsapp(
                    conn,
                    promise=promise,
                    intent=intent,
                    to_phone=phone,
                    body=body,
                    use_template=False,
                )
                sent = True
            elif template_name:
                _enqueue_whatsapp(
                    conn,
                    promise=promise,
                    intent=intent,
                    to_phone=phone,
                    body=body,
                    use_template=True,
                )
                sent = True
            elif not sms_blocked:
                channel = "sms"
            else:
                reason = "whatsapp_outside_service_window"
        if channel == "sms" and not sent:
            import twilio_sms

            if not twilio_sms.configured() and not resend:
                # Still queue the reminder so ops can see the miss; drain will
                # mark it failed if Twilio stays unconfigured.
                pass
            _enqueue_sms_reminder(conn, promise=promise, body=body, resend=resend)
            sent = True
    except Exception:
        logger.exception("ptp fulfill enqueue failed promise=%s", promise_id)
        sent = False
        reason = reason or "enqueue_failed"

    if sent:
        conn.execute(
            text(
                """
                UPDATE payment_intents
                SET status = CASE WHEN status IN ('created','failed') THEN 'sent' ELSE status END,
                    confirm_channel = :channel,
                    phone_last4 = :last4,
                    suppression_reason = NULL
                WHERE id = :id
                """
            ),
            {"id": intent["id"], "channel": channel, "last4": last4},
        )
        dbmod.record_activity(
            conn,
            "promise",
            promise_id,
            "promise_confirmed",
            f"Payment link queued on {channel}",
            f"ending {last4}" if last4 else channel,
            promise["customer_id"],
        )
        result.confirm_channel = channel
        result.phone_last4 = last4
        result.pay_link_sent = True
    else:
        result.suppressed = True
        result.suppression_reason = reason or "send_failed"
        result.phone_last4 = last4
        conn.execute(
            text(
                """
                UPDATE payment_intents
                SET suppression_reason = :reason,
                    phone_last4 = :last4
                WHERE id = :id
                """
            ),
            {"id": intent["id"], "reason": result.suppression_reason, "last4": last4},
        )
        dbmod.record_activity(
            conn,
            "promise",
            promise_id,
            "promise_confirmed",
            "Payment link failed",
            result.suppression_reason,
            promise["customer_id"],
        )

    result.spoken_summary = _spoken(
        amount=promise["amount"],
        promised_at=promise["promised_at"],
        channel=result.confirm_channel,
        last4=result.phone_last4,
        suppressed=result.suppressed,
    )
    _schedule_due_reminder(conn, promise, channel or "whatsapp")
    return result


def snapshot(conn: Any, promise_id: str) -> FulfillmentResult:
    """Read the latest intent for spoken_summary / tool payload without sending."""
    promise = _load_promise(conn, promise_id)
    if promise is None:
        raise KeyError("promise_not_found")
    row = conn.execute(
        text(
            """
            SELECT * FROM payment_intents
            WHERE promise_id = :pid
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"pid": promise_id},
    ).mappings().first()
    if row is None:
        return FulfillmentResult(
            promise_id=promise_id,
            spoken_summary=_spoken(
                amount=promise["amount"],
                promised_at=promise["promised_at"],
                channel=None,
                last4=None,
                suppressed=True,
            ),
            suppressed=True,
            suppression_reason="no_intent",
        )
    suppressed = bool(row.get("suppression_reason")) and row["status"] not in {"sent", "opened", "paid"}
    result = FulfillmentResult(
        promise_id=promise_id,
        intent_id=row["id"],
        confirm_channel=row.get("confirm_channel"),
        phone_last4=row.get("phone_last4"),
        pay_link_sent=row["status"] in {"sent", "opened", "paid"},
        suppressed=suppressed,
        suppression_reason=row.get("suppression_reason"),
    )
    result.spoken_summary = _spoken(
        amount=promise["amount"],
        promised_at=promise["promised_at"],
        channel=result.confirm_channel,
        last4=result.phone_last4,
        suppressed=result.suppressed,
    )
    return result


#: followups.channel is a narrower set than the treatment engine's action
#: space. Anything without a home here lands on 'voice', which is what a
#: follow-up in a queue means anyway — a person will pick it up.
_FOLLOWUP_CHANNEL = {"whatsapp": "whatsapp", "sms": "sms", "voice": "voice", "email": "email"}


def _next_action(conn: Any, promise: dict[str, Any]) -> dict[str, Any]:
    """The treatment engine's plan for a promise that just broke.

    Never raises and never blocks the break itself: a settle tick that fails
    because the recommender had a bad day would leave promises marked
    ``upcoming`` past their date, which is worse than a generic note.
    """
    fallback = {
        "due_at": None,
        "note": "Broken promise follow-up",
        "channel": "voice",
    }
    try:
        from agent_core.treatment import Trigger, recommend_treatment

        result = recommend_treatment(
            customer_id=promise["customer_id"],
            account_id=promise.get("account_id"),
            trigger=Trigger(kind="broken_ptp", at=datetime.now(timezone.utc), ref=promise["id"]),
            conn=conn,
        )
        from agent_core.clerk import enqueue_from_treatment

        enqueue_from_treatment(
            trigger_kind="broken_ptp",
            trigger_ref=promise["id"],
            customer_id=promise["customer_id"],
            decision_id=getattr(result, "decision_id", None),
            action=getattr(result, "action", None),
            conn=conn,
        )
    except Exception:
        logger.exception("treatment lookup failed for broken promise %s", promise["id"])
        return fallback
    note = (result.rationale or fallback["note"])[:500]
    if not result.actionable:
        return {**fallback, "note": note}
    return {
        "due_at": result.at,
        "note": note,
        "channel": _FOLLOWUP_CHANNEL.get(result.channel or "", "voice"),
    }


def settle_promises(engine: Engine | Any) -> dict[str, int]:
    """Advance due_today and auto-break after the promised IST day ends."""
    import db as dbmod

    due = 0
    broken = 0
    expired = 0
    with engine.begin() as conn:
        due = conn.execute(
            text(
                """
                UPDATE promises
                SET status = 'due_today'
                WHERE status = 'upcoming'
                  AND (promised_at AT TIME ZONE 'Asia/Kolkata')::date
                    = (now() AT TIME ZONE 'Asia/Kolkata')::date
                """
            )
        ).rowcount or 0
        expired = conn.execute(
            text(
                """
                UPDATE payment_intents
                SET status = 'expired'
                WHERE status IN ('created','sent','opened')
                  AND expires_at IS NOT NULL
                  AND expires_at < now()
                """
            )
        ).rowcount or 0
        rows = conn.execute(
            text(
                """
                SELECT id, customer_id, account_id
                FROM promises
                WHERE status IN ('upcoming','due_today')
                  AND paid_amount < amount
                  AND (promised_at AT TIME ZONE 'Asia/Kolkata')::date
                    < (now() AT TIME ZONE 'Asia/Kolkata')::date
                FOR UPDATE
                """
            )
        ).mappings().all()
        for row in rows:
            conn.execute(
                text("UPDATE promises SET status = 'broken' WHERE id = :id AND status <> 'kept'"),
                {"id": row["id"]},
            )
            # Ask the treatment engine what should happen now, rather than
            # leaving the answer to tomorrow's huddle. In shadow — the default
            # — nothing is dispatched; the plan is logged and its reasoning
            # becomes the follow-up note, so the clerk who picks this up reads
            # "WhatsApp at 09:10, 55% chance of reaching them" instead of
            # "Broken promise follow-up".
            plan = _next_action(conn, row)
            conn.execute(
                text(
                    """
                    INSERT INTO followups
                      (id, promise_id, customer_id, assignee_user_id, status,
                       priority, due_at, note, channel)
                    VALUES
                      (:id, :promise_id, :customer_id, :assignee, 'open', 'high',
                       COALESCE(:due_at, now() + interval '1 day'), :note, :channel)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": f"FU-{row['id']}",
                    "promise_id": row["id"],
                    "customer_id": row["customer_id"],
                    "assignee": dbmod._actor_user_id(),
                    "due_at": plan["due_at"],
                    "note": plan["note"],
                    "channel": plan["channel"],
                },
            )
            dbmod.record_activity(
                conn,
                "promise",
                row["id"],
                "promise_updated",
                "Promise auto-broken",
                "broken",
                row["customer_id"],
            )
            # Same transaction as the status change, so a subscriber is never
            # told about a break that got rolled back.
            webhooks_dispatch.dispatch(
                conn,
                "promise.broken",
                {
                    "promiseId": row["id"],
                    "customerId": row["customer_id"],
                    "accountId": row["account_id"],
                    "reason": "not_paid_by_promised_date",
                },
            )
            broken += 1
    if due or broken or expired:
        logger.info("settle_promises due_today=%s broken=%s intents_expired=%s", due, broken, expired)
    return {"due_today": due, "broken": broken, "expired": expired}


def _send_reminder_copy(conn: Any, reminder: dict[str, Any]) -> tuple[bool, str | None]:
    """Send a due/confirm reminder. Returns (ok, error)."""
    promise = _load_promise(conn, reminder["promise_id"])
    if promise is None:
        return False, "promise_not_found"
    intent = conn.execute(
        text(
            """
            SELECT * FROM payment_intents
            WHERE promise_id = :pid
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"pid": promise["id"]},
    ).mappings().first()
    if intent is None:
        return False, "intent_not_found"
    if intent["status"] == "paid":
        return True, None
    body = _confirm_copy(
        amount=intent["amount"],
        promised_at=promise["promised_at"],
        pay_url=intent["pay_url"],
        expires_at=intent.get("expires_at"),
    )
    channel = reminder["channel"]
    phone = promise.get("phone_primary") or promise.get("phone_alt")
    purpose = "statutory" if reminder.get("kind") == "confirm" else "outreach"
    source = "ptp_confirm" if purpose == "statutory" else "due_reminder"
    if channel == "sms":
        import contact_policy
        import twilio_sms

        decision = contact_policy.admit(
            conn,
            customer_id=promise["customer_id"],
            channel="sms",
            purpose=purpose,
            session_key=promise["id"],
            source=source,
            related_id=reminder.get("id"),
            actor_kind="system",
            account_id=promise.get("account_id"),
        )
        if not decision.allowed:
            return False, decision.reason or "contact_policy"
        twilio_sms.send(
            to_phone=phone or "",
            body=body,
            customer_id=promise["customer_id"],
            related_id=reminder.get("id"),
        )
        return True, None
    if channel == "whatsapp":
        inside = False
        try:
            import db as dbmod

            cid = dbmod._open_whatsapp_conversation(conn, promise["customer_id"])
            inside = _inside_service_window(conn, cid)
        except Exception:
            inside = False
        _enqueue_whatsapp(
            conn,
            promise=promise,
            intent=dict(intent),
            to_phone=phone or "",
            body=body,
            use_template=not inside,
            purpose=purpose,
            source=source,
        )
        return True, None
    return False, "unsupported_channel"


def process_one_reminder(engine: Engine | Any) -> bool:
    """Drain one due/confirm reminder (SKIP LOCKED)."""
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, promise_id, channel, kind, status
                FROM promise_reminders
                WHERE kind IN ('confirm','due')
                  AND status IN ('queued','scheduled')
                  AND (scheduled_at IS NULL OR scheduled_at <= now())
                ORDER BY scheduled_at ASC NULLS FIRST, created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            )
        ).mappings().first()
        if row is None:
            return False
        try:
            ok, err = _send_reminder_copy(conn, dict(row))
        except Exception as exc:
            logger.warning("reminder %s send failed: %s", row["id"], exc, exc_info=True)
            ok, err = False, type(exc).__name__
        conn.execute(
            text(
                """
                UPDATE promise_reminders
                SET status = :status,
                    sent_at = CASE WHEN :ok THEN now() ELSE sent_at END,
                    provider_delivery_id = COALESCE(:err, provider_delivery_id)
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "status": "sent" if ok else "failed",
                "ok": ok,
                "err": (err or "")[:200] or None,
            },
        )
        if ok and row["kind"] == "due":
            conn.execute(
                text(
                    """
                    UPDATE promises SET reminder_status = 'sent'
                    WHERE id = :id AND reminder_status IN ('queued','scheduled')
                    """
                ),
                {"id": row["promise_id"]},
            )
        return True
