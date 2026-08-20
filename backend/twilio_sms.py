"""Thin Twilio SMS send for PTP confirm fallback.

Voice already uses the same Account SID / Auth Token. This module is the
transactional SMS path when WhatsApp is outside the 24-hour window and no
utility template is configured, or when WhatsApp is opted out.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from env_loader import load_env

logger = logging.getLogger(__name__)


def _env(name: str, default: str = "") -> str:
    load_env()
    return (os.getenv(name) or default).strip()


def from_number() -> str:
    return _env("TWILIO_SMS_FROM") or _env("TWILIO_PHONE_NUMBER")


def configured() -> bool:
    return bool(_env("TWILIO_ACCOUNT_SID") and _env("TWILIO_AUTH_TOKEN") and from_number())


def send(*, to_phone: str, body: str) -> dict[str, Any]:
    """Send an SMS. Raises ValueError on config/API errors."""
    raw = (to_phone or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        raise ValueError("sms_missing_recipient")
    if not configured():
        raise ValueError("sms_not_configured")
    if raw.startswith("+"):
        to = "+" + digits
    elif len(digits) == 10:
        to = "+91" + digits
    else:
        to = "+" + digits

    from twilio.http.http_client import TwilioHttpClient
    from twilio.rest import Client

    client = Client(
        _env("TWILIO_ACCOUNT_SID"),
        _env("TWILIO_AUTH_TOKEN"),
        http_client=TwilioHttpClient(timeout=10),
    )
    msg = client.messages.create(to=to, from_=from_number(), body=body)
    logger.info("twilio_sms sent sid=%s to_last4=%s", msg.sid, digits[-4:])
    return {"sid": msg.sid, "status": msg.status}
