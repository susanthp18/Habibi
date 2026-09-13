"""Thin Twilio SMS send for PTP confirm fallback.

Voice already uses the same Account SID / Auth Token. This module is the
transactional SMS path when WhatsApp is outside the 24-hour window and no
utility template is configured, or when WhatsApp is opted out.
"""

from __future__ import annotations

import logging
from typing import Any

from env_loader import env_str

logger = logging.getLogger(__name__)


def from_number() -> str:
    return env_str("TWILIO_SMS_FROM") or env_str("TWILIO_PHONE_NUMBER")


def configured() -> bool:
    return bool(env_str("TWILIO_ACCOUNT_SID") and env_str("TWILIO_AUTH_TOKEN") and from_number())


def status_callback_url() -> str:
    """Where Twilio should post delivery transitions, or "" if we are not public.

    Empty rather than a localhost guess: Twilio posting into the void is a
    silent hole in the reach corpus, and a configuration error that announces
    itself as "no receipts" is better than one that announces itself as
    "borrowers on this channel are unreachable".
    """
    base = env_str("PUBLIC_BASE_URL").rstrip("/")
    return f"{base}/twilio/sms/status" if base.startswith("http") else ""


def send(
    *,
    to_phone: str,
    body: str,
    customer_id: str | None = None,
    tenant_id: str | None = None,
    related_id: str | None = None,
) -> dict[str, Any]:
    """Send an SMS. Raises ValueError on config/API errors.

    ``customer_id`` and ``tenant_id`` are optional and only used to record the
    receipt. They are taken here rather than left to the caller because this is
    where the message SID is born: without a row mapping SID to borrower, the
    status callback arrives with an identifier nothing in the system recognises,
    and the delivery evidence is unattributable.
    """
    raw = (to_phone or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        raise ValueError("sms_missing_recipient")
    from agent_core.carrier_guard import refuse_real_carrier

    if not configured():
        raise ValueError("sms_not_configured")
    refuse_real_carrier("twilio.sms")
    if raw.startswith("+"):
        to = "+" + digits
    elif len(digits) == 10:
        to = "+91" + digits
    else:
        to = "+" + digits

    from voice import twilio_ops

    client = twilio_ops.rest_client()
    kwargs: dict[str, Any] = {"to": to, "from_": from_number(), "body": body}
    callback = status_callback_url()
    if callback:
        kwargs["status_callback"] = callback
    from voice.twilio_ops import CarrierOptOut, carrier_call

    try:
        msg = carrier_call(client.messages.create, **kwargs)
    except CarrierOptOut:
        # Every SMS leaves through here, so this is the one place the
        # carrier's STOP can reach the consent ledger before the sender
        # decides what to do with the failure.
        _record_carrier_opt_out(customer_id, digits[-4:])
        raise
    logger.info("twilio_sms sent sid=%s to_last4=%s", msg.sid, digits[-4:])

    _record_sent(
        sid=str(msg.sid or ""),
        status=str(msg.status) if msg.status is not None else None,
        customer_id=customer_id,
        tenant_id=tenant_id,
        related_id=related_id,
    )
    return {"sid": msg.sid, "status": msg.status}


def _record_carrier_opt_out(customer_id: str | None, last4: str) -> None:
    """The recipient replied STOP to the carrier: close SMS for them here too.

    Never raises -- the send has already failed and the caller reports that;
    an opt-out that could not be written is logged, not lost in the same
    exception.
    """
    if not customer_id:
        logger.warning("twilio_sms STOP from an unattributed number last4=%s", last4)
        return
    try:
        import db_consent

        db_consent.opt_out(
            customer_id,
            {"channel": "sms", "source": "carrier", "note": "Twilio 21610: the recipient replied STOP"},
        )
        logger.warning("twilio_sms STOP recorded as an sms opt-out customer=%s", customer_id)
    except Exception:
        logger.exception("twilio_sms STOP could not be recorded customer=%s", customer_id)


def _record_sent(
    *,
    sid: str,
    status: str | None,
    customer_id: str | None,
    tenant_id: str | None,
    related_id: str | None,
) -> None:
    """Append the outbound receipt. Never raises — the message is already gone."""
    if not customer_id:
        return
    try:
        import db as dbmod
        import delivery_receipts

        with dbmod.engine.begin() as conn:
            resolved_tenant = tenant_id
            if not resolved_tenant:
                from sqlalchemy import text as _text

                resolved_tenant = conn.execute(
                    _text("SELECT tenant_id FROM customers WHERE id = :cid"),
                    {"cid": customer_id},
                ).scalar()
            if not resolved_tenant:
                return
            delivery_receipts.record(
                conn,
                tenant_id=str(resolved_tenant),
                customer_id=customer_id,
                channel="sms",
                provider="twilio",
                provider_ref=sid,
                related_id=related_id,
                state=delivery_receipts.normalise_twilio(status) or "sent",
            )
    except Exception:
        logger.exception("twilio_sms receipt failed sid=%s", sid)
