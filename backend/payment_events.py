"""Bounce-to-contact: ingest a payment event, open a case, send a pay-link.

HMAC ``POST /webhooks/collections/payment-events`` and the sandbox emit share
:func:`ingest`. Idempotent on ``(tenant_id, source, source_ref)``. Digital
first-touch is ``statutory`` / ``bounce_notice`` (counts, not blocked by cap
or hours). Voice is last-resort outreach and defaults off.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from env_loader import load_env

logger = logging.getLogger(__name__)

BLOCKING_CONSENT = frozenset({"opted_out", "dnd", "expired"})
REASONS = frozenset(
    {"insufficient_funds", "account_closed", "mandate_expired", "technical", "unknown"}
)
SOURCES = frozenset({"nach", "upi", "ecs", "sandbox", "webhook"})
REASON_LABELS = {
    "insufficient_funds": "insufficient funds",
    "account_closed": "account closed",
    "mandate_expired": "mandate expired",
    "technical": "a technical failure",
    "unknown": "an unknown reason",
}
DEFAULT_TZ = "Asia/Kolkata"


def _env(name: str, default: str = "") -> str:
    load_env()
    return (os.getenv(name) or default).strip()


def bounce_voice_enabled() -> bool:
    return _env("BOUNCE_VOICE_ENABLED").lower() in {"1", "true", "yes", "on"}


def webhook_secret() -> str:
    return _env("PAYMENT_EVENTS_WEBHOOK_SECRET") or _env("PAYMENT_WEBHOOK_SECRET")


def verify_webhook_signature(*, raw_body: bytes, header: str | None) -> bool:
    secret = webhook_secret()
    if not secret or not header:
        return False
    provided = header.strip()
    if provided.lower().startswith("sha256="):
        provided = provided[7:]
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)


def _pick(body: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in body and body[key] not in (None, ""):
            return body[key]
    return None


def parse_payload(body: dict[str, Any]) -> dict[str, Any]:
    """Normalize camelCase / snake_case webhook bodies."""
    source = str(_pick(body, "source") or "webhook").strip().lower()
    if source not in SOURCES:
        source = "webhook"
    reason = str(_pick(body, "reason") or "unknown").strip().lower()
    if reason not in REASONS:
        reason = "unknown"
    return {
        "account_id": _pick(body, "accountId", "account_id"),
        "source": source,
        "source_ref": str(_pick(body, "sourceRef", "source_ref") or "").strip(),
        "amount": _pick(body, "amount"),
        "occurred_at": _pick(body, "occurredAt", "occurred_at"),
        "reason": reason,
        "emi_id": _pick(body, "emiId", "emi_id"),
        "bounce_fee": _pick(body, "bounceFee", "bounce_fee"),
        "next_credit_at": _pick(body, "nextCreditAt", "next_credit_at"),
        "customer_id": _pick(body, "customerId", "customer_id"),
    }


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_dt(raw: Any, fallback: datetime) -> datetime:
    if raw is None or raw == "":
        return fallback
    if isinstance(raw, datetime):
        return _aware(raw)
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return fallback
    return _aware(parsed)


def _zone(name: str | None) -> ZoneInfo:
    raw = (name or "").strip() or DEFAULT_TZ
    try:
        return ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def _intent_expiry(*, now: datetime, tz: ZoneInfo) -> datetime:
    local = now.astimezone(tz)
    end = (local + timedelta(days=7)).replace(hour=23, minute=59, second=59, microsecond=0)
    return end.astimezone(timezone.utc)


def next_voice_window(*, tz_name: str | None, now: datetime) -> datetime:
    """Next RBI 08:00 in the customer's zone, or ``now`` if already inside 08–19."""
    import contact_policy

    tz = _zone(tz_name)
    local = now.astimezone(tz)
    start = local.replace(
        hour=contact_policy.RBI_VOICE_START, minute=0, second=0, microsecond=0
    )
    if local.hour < contact_policy.RBI_VOICE_START:
        return start.astimezone(timezone.utc)
    if local.hour >= contact_policy.RBI_VOICE_END:
        return (start + timedelta(days=1)).astimezone(timezone.utc)
    return now


def _bounce_copy(
    *,
    amount: Any,
    due_at: datetime | None,
    pay_url: str,
    reason: str,
    tz: ZoneInfo,
) -> str:
    import promise_fulfillment as pf

    rupees = pf._fmt_inr(amount)
    why = REASON_LABELS.get(reason, reason.replace("_", " "))
    date_s = "the due date"
    if due_at is not None:
        due = due_at if due_at.tzinfo else due_at.replace(tzinfo=timezone.utc)
        date_s = due.astimezone(tz).strftime("%d %b %Y")
    return (
        f"Your EMI of ₹{rupees} due {date_s} did not go through ({why}). "
        f"Pay securely here: {pay_url}. Do not share this link."
    )


def ingest(conn: Any, payload: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Persist a bounce, book EMI/DPD, send statutory pay-link. Never double-sends.

    Raises ``ValueError`` for a missing/unknown account (HTTP 400). Idempotent
    replays return ``{ok, eventId, idempotent: True}`` without a second send
    once first-touch is recorded.
    """
    parsed = parse_payload(payload)
    account_id = (parsed.get("account_id") or "").strip()
    source_ref = (parsed.get("source_ref") or "").strip()
    if not account_id:
        raise ValueError("account_required")
    if not source_ref:
        raise ValueError("source_ref_required")

    instant = _aware(now or datetime.now(timezone.utc))
    occurred = _parse_dt(parsed.get("occurred_at"), instant)

    account = conn.execute(
        text(
            """
            SELECT a.id, a.customer_id, a.dpd, a.bucket, a.outstanding,
                   c.tenant_id, c.assigned_user_id, c.timezone,
                   c.phone_primary, c.phone_alt, c.name
            FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE a.id = :id
            FOR UPDATE OF a
            """
        ),
        {"id": account_id},
    ).mappings().first()
    if account is None:
        raise ValueError("account_required")

    tenant_id = account["tenant_id"]
    existing = conn.execute(
        text(
            """
            SELECT * FROM payment_events
            WHERE tenant_id = :tid AND source = :source AND source_ref = :ref
            FOR UPDATE
            """
        ),
        {"tid": tenant_id, "source": parsed["source"], "ref": source_ref},
    ).mappings().first()
    if existing:
        event = dict(existing)
        if event.get("first_touch_at") or event["status"] in {"cured", "suppressed"}:
            return _result(event, idempotent=True)
        _first_touch(conn, event, account=dict(account), now=instant)
        refreshed = conn.execute(
            text("SELECT * FROM payment_events WHERE id = :id"),
            {"id": event["id"]},
        ).mappings().first()
        return _result(dict(refreshed or event), idempotent=True)

    emi = _resolve_emi(
        conn,
        account_id=account_id,
        emi_id=parsed.get("emi_id"),
        occurred_at=occurred,
    )
    amount = _money(parsed.get("amount"))
    if amount <= 0 and emi is not None:
        amount = _money(emi["amount"])
    if amount <= 0:
        amount = _money(account.get("outstanding"))
    if amount <= 0:
        raise ValueError("amount_required")

    if emi is not None:
        open_emi = conn.execute(
            text(
                """
                SELECT * FROM payment_events
                WHERE account_id = :aid
                  AND emi_installment_id = :emi
                  AND kind = 'bounce'
                  AND status IN ('open','in_progress')
                FOR UPDATE
                """
            ),
            {"aid": account_id, "emi": emi["id"]},
        ).mappings().first()
        if open_emi:
            event = dict(open_emi)
            if event.get("first_touch_at") or event["status"] in {"cured", "suppressed"}:
                return _result(event, idempotent=True)
            _first_touch(conn, event, account=dict(account), now=instant, emi=emi)
            refreshed = conn.execute(
                text("SELECT * FROM payment_events WHERE id = :id"),
                {"id": event["id"]},
            ).mappings().first()
            return _result(dict(refreshed or event), idempotent=True)

    if emi is not None and emi["status"] != "paid":
        conn.execute(
            text(
                """
                UPDATE emi_installments
                SET status = 'overdue'
                WHERE id = :id AND status <> 'paid'
                """
            ),
            {"id": emi["id"]},
        )

    bucket = account.get("bucket")
    new_bucket = bucket
    if not bucket or str(bucket).strip() in {"", "0"}:
        new_bucket = "0-30"
    conn.execute(
        text(
            """
            UPDATE accounts
            SET dpd = GREATEST(dpd, 1),
                bucket = :bucket
            WHERE id = :id
            """
        ),
        {"id": account_id, "bucket": new_bucket},
    )

    fee = _money(parsed.get("bounce_fee")) if parsed.get("bounce_fee") not in (None, "") else Decimal("0")
    if fee > 0:
        import db as dbmod

        conn.execute(
            text(
                """
                INSERT INTO ledger_entries (id, account_id, type, description, amount, posted_at)
                VALUES (:id, :account_id, 'fee', :description, :amount, :posted_at)
                """
            ),
            {
                "id": dbmod._id("LED"),
                "account_id": account_id,
                "description": "EMI bounce fee",
                "amount": float(fee),
                "posted_at": occurred,
            },
        )
        conn.execute(
            text(
                """
                UPDATE accounts
                SET outstanding = outstanding + :fee
                WHERE id = :id
                """
            ),
            {"id": account_id, "fee": float(fee)},
        )

    import db as dbmod

    event_id = dbmod._id("PE")
    next_credit = _parse_dt(parsed.get("next_credit_at"), occurred) if parsed.get("next_credit_at") else None
    if parsed.get("next_credit_at") in (None, ""):
        next_credit = None
    try:
        conn.execute(
            text(
                """
                INSERT INTO payment_events (
                  id, tenant_id, customer_id, account_id, emi_installment_id,
                  kind, reason, amount, bounce_fee, source, source_ref, status,
                  next_credit_at, assignee_user_id, occurred_at
                ) VALUES (
                  :id, :tenant_id, :customer_id, :account_id, :emi_id,
                  'bounce', :reason, :amount, :bounce_fee, :source, :source_ref, 'open',
                  :next_credit_at, :assignee_user_id, :occurred_at
                )
                """
            ),
            {
                "id": event_id,
                "tenant_id": tenant_id,
                "customer_id": account["customer_id"],
                "account_id": account_id,
                "emi_id": emi["id"] if emi else None,
                "reason": parsed["reason"],
                "amount": float(amount),
                "bounce_fee": float(fee) if fee > 0 else None,
                "source": parsed["source"],
                "source_ref": source_ref,
                "next_credit_at": next_credit,
                "assignee_user_id": account.get("assigned_user_id"),
                "occurred_at": occurred,
            },
        )
    except IntegrityError:
        raced = conn.execute(
            text(
                """
                SELECT * FROM payment_events
                WHERE tenant_id = :tid AND source = :source AND source_ref = :ref
                FOR UPDATE
                """
            ),
            {"tid": tenant_id, "source": parsed["source"], "ref": source_ref},
        ).mappings().first()
        if raced is None and emi is not None:
            raced = conn.execute(
                text(
                    """
                    SELECT * FROM payment_events
                    WHERE account_id = :aid
                      AND emi_installment_id = :emi
                      AND kind = 'bounce'
                      AND status IN ('open','in_progress')
                    FOR UPDATE
                    """
                ),
                {"aid": account_id, "emi": emi["id"]},
            ).mappings().first()
        if raced is None:
            raise
        event = dict(raced)
        if event.get("first_touch_at") or event["status"] in {"cured", "suppressed"}:
            return _result(event, idempotent=True)
        _first_touch(conn, event, account=dict(account), now=instant)
        refreshed = conn.execute(
            text("SELECT * FROM payment_events WHERE id = :id"),
            {"id": event["id"]},
        ).mappings().first()
        return _result(dict(refreshed or event), idempotent=True)

    event = conn.execute(
        text("SELECT * FROM payment_events WHERE id = :id FOR UPDATE"),
        {"id": event_id},
    ).mappings().first()
    assert event is not None
    event_d = dict(event)
    dbmod.record_activity(
        conn,
        "payment_event",
        event_id,
        "bounce_ingested",
        "EMI bounce ingested",
        parsed["reason"],
        account["customer_id"],
    )
    _first_touch(conn, event_d, account=dict(account), now=instant, emi=emi)
    _plan_next(conn, event_d, now=instant)
    refreshed = conn.execute(
        text("SELECT * FROM payment_events WHERE id = :id"),
        {"id": event_id},
    ).mappings().first()
    return _result(dict(refreshed or event_d), idempotent=False)


def _plan_next(conn: Any, event: dict[str, Any], *, now: datetime) -> None:
    """Ask the treatment engine what happens after the statutory first touch.

    The pay-link is not the campaign; it is the legally required written notice.
    What comes next — a WhatsApp nudge timed to the salary credit, a bot call in
    the morning, an agent, or nothing at all — is a decision, and it is made
    here so it is made in the same minute as the bounce rather than in tomorrow
    morning's allocation.

    Shares this transaction on purpose: ``ingest`` holds ``FOR UPDATE`` on the
    account row, and a second connection here would be a deadlock waiting for
    load. It also means a bounce that rolls back leaves no plan behind
    describing a case that no longer exists.

    Default mode is shadow, so this logs a decision and changes nothing.
    """
    try:
        from agent_core.treatment import Trigger, recommend_treatment

        result = recommend_treatment(
            customer_id=event["customer_id"],
            account_id=event["account_id"],
            trigger=Trigger(kind="bounce", at=event.get("occurred_at") or now, ref=event["id"]),
            now=now,
            conn=conn,
        )
        from agent_core.clerk import enqueue_from_treatment

        enqueue_from_treatment(
            trigger_kind="bounce",
            trigger_ref=event["id"],
            customer_id=event["customer_id"],
            decision_id=getattr(result, "decision_id", None),
            action=getattr(result, "action", None),
            conn=conn,
        )
    except Exception:
        # recommend_treatment does not raise; this catches an import failure or
        # a schema that predates the engine. A bounce must still be ingested.
        logger.exception("treatment planning failed for bounce %s", event.get("id"))


def _result(event: dict[str, Any], *, idempotent: bool) -> dict[str, Any]:
    return {
        "ok": True,
        "eventId": event["id"],
        "idempotent": idempotent,
        "status": event.get("status"),
        "firstTouch": event.get("first_touch_channel"),
        "intentId": event.get("payment_intent_id"),
        "suppressionReason": event.get("suppression_reason"),
    }


def _resolve_emi(
    conn: Any,
    *,
    account_id: str,
    emi_id: Any,
    occurred_at: datetime,
) -> dict[str, Any] | None:
    if emi_id:
        row = conn.execute(
            text(
                """
                SELECT * FROM emi_installments
                WHERE id = :id AND account_id = :aid
                FOR UPDATE
                """
            ),
            {"id": str(emi_id), "aid": account_id},
        ).mappings().first()
        return dict(row) if row else None
    row = conn.execute(
        text(
            """
            SELECT * FROM emi_installments
            WHERE account_id = :aid
              AND status IN ('upcoming','partial')
              AND due_date <= :occurred
            ORDER BY due_date ASC
            LIMIT 1
            FOR UPDATE
            """
        ),
        {"aid": account_id, "occurred": occurred_at},
    ).mappings().first()
    if row:
        return dict(row)
    row = conn.execute(
        text(
            """
            SELECT * FROM emi_installments
            WHERE account_id = :aid
              AND status IN ('upcoming','partial')
            ORDER BY due_date ASC
            LIMIT 1
            FOR UPDATE
            """
        ),
        {"aid": account_id},
    ).mappings().first()
    return dict(row) if row else None


def _channel_blocked(consent: dict[str, str], channel: str) -> bool:
    return (consent.get(channel) or "").lower() in BLOCKING_CONSENT


def _first_touch(
    conn: Any,
    event: dict[str, Any],
    *,
    account: dict[str, Any],
    now: datetime,
    emi: dict[str, Any] | None = None,
) -> None:
    import capture
    import contact_policy
    import db as dbmod
    import promise_fulfillment as pf

    customer_id = event["customer_id"]
    tz = _zone(account.get("timezone"))
    intent = pf.create_pay_intent(
        conn,
        tenant_id=event["tenant_id"],
        customer_id=customer_id,
        account_id=event["account_id"],
        amount=_money(event["amount"]),
        expires_at=_intent_expiry(now=now, tz=tz),
        payment_event_id=event["id"],
    )
    conn.execute(
        text("UPDATE payment_events SET payment_intent_id = :iid WHERE id = :id"),
        {"iid": intent["id"], "id": event["id"]},
    )
    event["payment_intent_id"] = intent["id"]

    if emi is None and event.get("emi_installment_id"):
        emi = conn.execute(
            text("SELECT * FROM emi_installments WHERE id = :id"),
            {"id": event["emi_installment_id"]},
        ).mappings().first()
        emi = dict(emi) if emi else None

    body = _bounce_copy(
        amount=intent["amount"],
        due_at=emi["due_date"] if emi else None,
        pay_url=intent["pay_url"],
        reason=event.get("reason") or "unknown",
        tz=tz,
    )
    consent = capture.latest_consent_by_channel(conn, customer_id)
    phone = account.get("phone_primary") or account.get("phone_alt")
    sms_blocked = _channel_blocked(consent, "sms")

    def _admit(ch: str) -> Any:
        session_key = event["id"]
        if ch == "whatsapp":
            session_key = dbmod._open_whatsapp_conversation(conn, customer_id)
        return contact_policy.admit(
            conn,
            customer_id=customer_id,
            channel=ch,
            purpose="statutory",
            session_key=session_key,
            source="bounce_notice",
            related_id=intent["id"],
            actor_kind="system",
            account_id=event["account_id"],
            now=now,
        )

    channel: str | None = None
    reason: str | None = None
    if not phone:
        reason = "no_phone_on_file"
    else:
        wa_decision = _admit("whatsapp")
        if wa_decision.allowed:
            channel = "whatsapp"
        else:
            sms_decision = _admit("sms")
            if sms_decision.allowed:
                channel = "sms"
            else:
                reason = sms_decision.reason or wa_decision.reason or "channel_opted_out"

    sent = False
    if channel == "whatsapp":
        conversation_id = dbmod._open_whatsapp_conversation(conn, customer_id)
        inside = pf._inside_service_window(conn, conversation_id, now=now)
        template_name = _env("WHATSAPP_BOUNCE_TEMPLATE_NAME")
        due_s = ""
        if emi and emi.get("due_date"):
            due = emi["due_date"]
            due = due if getattr(due, "tzinfo", None) else due.replace(tzinfo=timezone.utc)
            due_s = due.astimezone(tz).strftime("%d %b %Y")
        params = [pf._fmt_inr(intent["amount"]), due_s or "due", intent["pay_url"]]
        if inside:
            pf.enqueue_whatsapp_paylink(
                conn,
                customer_id=customer_id,
                intent=intent,
                to_phone=phone or "",
                body=body,
                use_template=False,
                purpose="statutory",
                source="bounce_notice",
                template_env_name="WHATSAPP_BOUNCE_TEMPLATE_NAME",
                template_env_lang="WHATSAPP_BOUNCE_TEMPLATE_LANG",
            )
            sent = True
        elif template_name:
            pf.enqueue_whatsapp_paylink(
                conn,
                customer_id=customer_id,
                intent=intent,
                to_phone=phone or "",
                body=body,
                use_template=True,
                purpose="statutory",
                source="bounce_notice",
                template_env_name="WHATSAPP_BOUNCE_TEMPLATE_NAME",
                template_env_lang="WHATSAPP_BOUNCE_TEMPLATE_LANG",
                template_params=params,
            )
            sent = True
        elif not sms_blocked:
            channel = "sms"
            decision = _admit("sms")
            if not decision.allowed:
                channel = None
                reason = decision.reason or "whatsapp_outside_service_window"
        else:
            reason = "whatsapp_outside_service_window"

    if channel == "sms" and not sent:
        import twilio_sms

        try:
            if twilio_sms.configured():
                twilio_sms.send(to_phone=phone or "", body=body)
            sent = True
        except Exception:
            logger.exception("bounce sms send failed event=%s", event["id"])
            reason = reason or "sms_send_failed"

    if sent and channel:
        conn.execute(
            text(
                """
                UPDATE payment_events
                SET status = 'in_progress',
                    first_touch_at = :at,
                    first_touch_channel = :ch,
                    suppression_reason = NULL
                WHERE id = :id
                """
            ),
            {"id": event["id"], "at": now, "ch": channel},
        )
        conn.execute(
            text(
                """
                UPDATE payment_intents
                SET status = CASE WHEN status = 'created' THEN 'sent' ELSE status END,
                    confirm_channel = :ch,
                    phone_last4 = :last4
                WHERE id = :id
                """
            ),
            {
                "id": intent["id"],
                "ch": channel,
                "last4": pf._phone_last4(phone),
            },
        )
        dbmod.record_activity(
            conn,
            "payment_event",
            event["id"],
            "bounce_first_touch",
            f"Bounce pay-link sent via {channel}",
            None,
            customer_id,
        )
        return

    _digital_blocked(
        conn,
        event,
        account=account,
        reason=reason or "channel_opted_out",
        now=now,
        intent_id=intent["id"],
        last4=pf._phone_last4(phone),
    )


def _digital_blocked(
    conn: Any,
    event: dict[str, Any],
    *,
    account: dict[str, Any],
    reason: str,
    now: datetime,
    intent_id: str,
    last4: str | None,
) -> None:
    import db as dbmod

    conn.execute(
        text(
            """
            UPDATE payment_intents
            SET suppression_reason = :reason, phone_last4 = :last4
            WHERE id = :id
            """
        ),
        {"id": intent_id, "reason": reason, "last4": last4},
    )
    next_voice = None
    if bounce_voice_enabled():
        nxt = next_voice_window(tz_name=account.get("timezone"), now=now)
        if nxt <= now:
            if _try_voice_now(conn, event, account=account, now=now):
                return
            already = conn.execute(
                text("SELECT next_voice_at FROM payment_events WHERE id = :id"),
                {"id": event["id"]},
            ).mappings().first()
            if already and already["next_voice_at"]:
                conn.execute(
                    text(
                        """
                        UPDATE payment_events
                        SET suppression_reason = COALESCE(suppression_reason, :reason)
                        WHERE id = :id
                        """
                    ),
                    {"id": event["id"], "reason": reason},
                )
                dbmod.record_activity(
                    conn,
                    "payment_event",
                    event["id"],
                    "bounce_suppressed",
                    "Bounce digital send blocked",
                    reason,
                    event["customer_id"],
                )
                return
        else:
            next_voice = nxt
    conn.execute(
        text(
            """
            UPDATE payment_events
            SET suppression_reason = :reason,
                next_voice_at = :next_voice
            WHERE id = :id
            """
        ),
        {"id": event["id"], "reason": reason, "next_voice": next_voice},
    )
    dbmod.record_activity(
        conn,
        "payment_event",
        event["id"],
        "bounce_suppressed",
        "Bounce digital send blocked",
        reason,
        event["customer_id"],
    )


def _try_voice_now(
    conn: Any,
    event: dict[str, Any],
    *,
    account: dict[str, Any],
    now: datetime,
) -> bool:
    import contact_policy

    phone = account.get("phone_primary") or account.get("phone_alt")
    if not phone:
        return False
    decision = contact_policy.admit(
        conn,
        customer_id=event["customer_id"],
        channel="voice",
        purpose="outreach",
        session_key=event["id"],
        source="bounce_voice",
        related_id=event["id"],
        actor_kind="system",
        account_id=event["account_id"],
        now=now,
    )
    if not decision.allowed:
        if decision.reason == contact_policy.REASON_HOURS:
            nxt = next_voice_window(tz_name=account.get("timezone"), now=now)
            conn.execute(
                text(
                    """
                    UPDATE payment_events
                    SET next_voice_at = :nxt, suppression_reason = :reason
                    WHERE id = :id
                    """
                ),
                {"id": event["id"], "nxt": nxt, "reason": decision.reason},
            )
        return False
    try:
        from voice import twilio_ops

        twilio_ops.start_outbound_call(
            to=phone,
            custom={"customer_id": event["customer_id"], "account_id": event["account_id"]},
        )
    except Exception:
        logger.exception("bounce voice dial failed event=%s", event["id"])
        return False
    conn.execute(
        text(
            """
            UPDATE payment_events
            SET status = 'in_progress',
                first_touch_at = :at,
                first_touch_channel = 'voice',
                next_voice_at = NULL,
                suppression_reason = NULL
            WHERE id = :id
            """
        ),
        {"id": event["id"], "at": now},
    )
    return True


def process_one_voice(engine: Engine) -> bool:
    """Drain one due last-resort bounce autodial. SKIP LOCKED."""
    if not bounce_voice_enabled():
        return False
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT pe.*, c.phone_primary, c.phone_alt, c.timezone
                FROM payment_events pe
                JOIN customers c ON c.id = pe.customer_id
                WHERE pe.kind = 'bounce'
                  AND pe.status IN ('open','in_progress')
                  AND pe.next_voice_at IS NOT NULL
                  AND pe.next_voice_at <= now()
                  AND pe.first_touch_at IS NULL
                ORDER BY pe.next_voice_at ASC
                FOR UPDATE OF pe SKIP LOCKED
                LIMIT 1
                """
            )
        ).mappings().first()
        if row is None:
            return False
        event = dict(row)
        account = {
            "phone_primary": row["phone_primary"],
            "phone_alt": row["phone_alt"],
            "timezone": row["timezone"],
        }
        now = datetime.now(timezone.utc)
        if not _try_voice_now(conn, event, account=account, now=now):
            conn.execute(
                text("UPDATE payment_events SET next_voice_at = NULL WHERE id = :id"),
                {"id": event["id"]},
            )
        return True


def cure_for_account(
    conn: Any,
    *,
    account_id: str,
    amount: Decimal,
    preferred_emi_id: str | None = None,
    intent_id: str | None = None,
) -> list[str]:
    """Apply a credit to overdue EMIs and cure matching open bounces."""
    remaining = _money(amount)
    if remaining <= 0:
        return []
    rows = conn.execute(
        text(
            """
            SELECT id, amount, paid_amount, status
            FROM emi_installments
            WHERE account_id = :aid
              AND status IN ('overdue','partial','upcoming')
            ORDER BY
              CASE WHEN id = :preferred THEN 0 ELSE 1 END,
              due_date ASC, installment_index ASC
            FOR UPDATE
            """
        ),
        {"aid": account_id, "preferred": preferred_emi_id},
    ).mappings().all()
    cured: list[str] = []
    posted = datetime.now(timezone.utc)
    for row in rows:
        if remaining <= 0:
            break
        due = _money(row["amount"])
        already = _money(row["paid_amount"])
        need = due - already
        if need <= 0:
            continue
        take = min(need, remaining)
        new_paid = already + take
        next_status = "paid" if new_paid >= due else "partial"
        conn.execute(
            text(
                """
                UPDATE emi_installments
                SET paid_amount = :paid,
                    status = :status,
                    paid_on = CASE WHEN :status = 'paid' THEN :paid_on ELSE paid_on END
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "paid": float(new_paid),
                "status": next_status,
                "paid_on": posted,
            },
        )
        remaining -= take
        if next_status == "paid":
            updated = conn.execute(
                text(
                    """
                    UPDATE payment_events
                    SET status = 'cured', next_voice_at = NULL
                    WHERE account_id = :aid
                      AND emi_installment_id = :emi
                      AND kind = 'bounce'
                      AND status IN ('open','in_progress')
                    RETURNING id
                    """
                ),
                {"aid": account_id, "emi": row["id"]},
            ).mappings().all()
            cured.extend(r["id"] for r in updated)
    if intent_id:
        extra = conn.execute(
            text(
                """
                UPDATE payment_events
                SET status = 'cured', next_voice_at = NULL
                WHERE payment_intent_id = :iid
                  AND kind = 'bounce'
                  AND status IN ('open','in_progress')
                RETURNING id
                """
            ),
            {"iid": intent_id},
        ).mappings().all()
        for r in extra:
            if r["id"] not in cured:
                cured.append(r["id"])
    return cured
