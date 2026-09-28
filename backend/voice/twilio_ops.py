"""Twilio account helpers: credentials, the REST client under its circuit
breaker (SMS), the say-and-hang-up TwiML the voice webhooks answer with, and a
caller's CRM match.

Voice Studio places and carries every call; the media-stream runner these
helpers used to dial into was retired with the legacy voice runtime.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from xml.sax.saxutils import escape

from env_loader import env_str

logger = logging.getLogger(__name__)


class OutboundDisabled(RuntimeError):
    """The master outbound switch is off, so no dial was attempted.

    Distinct from every other failure this module raises: nothing was tried,
    nothing reached the carrier, and retrying changes nothing until an operator
    turns the switch on. Callers that record attempts use it to write a
    *suppressed* row rather than a failed one — a dial we declined to place is
    not a dial the carrier rejected, and conflating them corrupts the answer
    rate every outbound metric is built on.
    """


def account_sid() -> str:
    return env_str("TWILIO_ACCOUNT_SID")


def auth_token() -> str:
    return env_str("TWILIO_AUTH_TOKEN")


def twilio_phone() -> str:
    return env_str("TWILIO_PHONE_NUMBER")


def digits_only(phone: str | None) -> str:
    return re.sub(r"\D+", "", phone or "")


def twiml_say_hangup(message: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f"  <Say voice=\"Polly.Aditi\">{escape(message)}</Say>\n"
        "  <Hangup/>\n"
        "</Response>\n"
    )


class CarrierRejected(Exception):
    """Twilio answered 4xx: the request was wrong, the carrier is fine.

    Distinguished so the breaker does not count a bad number against the
    dependency. Carries the original exception as ``__cause__``.
    """


#: Twilio's "the recipient has replied STOP to this number" -- a statutory
#: opt-out the carrier recorded and we had not.
TWILIO_STOP_CODE = 21610


class CarrierOptOut(CarrierRejected):
    """The recipient told the carrier to stop. Not a bad number: an opt-out
    that must reach the consent ledger, whichever sender tripped it."""


def _is_rejection(exc: BaseException) -> bool:
    status = getattr(exc, "status", None)
    return isinstance(status, int) and 400 <= status < 500 and status not in (408, 429)


def carrier_breaker():
    """The one breaker for Twilio REST -- SMS and voice share the account,
    the endpoint and the outage."""
    import circuit_breaker

    return circuit_breaker.get_breaker("twilio", ignore_exceptions=(CarrierRejected,))


def carrier_call(fn, *args, **kwargs):
    """Run one Twilio REST call under the breaker.

    Every other outbound dependency had one; Twilio -- the one that reaches a
    borrower's phone -- did not, so a carrier outage was retried at full rate
    by every scheduler until the attempts ran out. A 4xx is re-raised as
    :class:`CarrierRejected` (not counted); 5xx, 429 and timeouts trip it;
    an open circuit raises ``circuit_breaker.CircuitOpenError`` before any
    request is made, which the callers report as ``carrier_unavailable``.
    """

    def _guarded():
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if _is_rejection(exc):
                if getattr(exc, "code", None) == TWILIO_STOP_CODE:
                    raise CarrierOptOut(str(exc)) from exc
                raise CarrierRejected(str(exc)) from exc
            raise

    return carrier_breaker().call(_guarded)


def rest_client():
    """The Twilio REST client every caller shares the shape of: the account
    credentials and a 10 s HTTP timeout. SMS and the webhook-setting script
    used to construct their own, the script with no timeout at all.
    """
    from twilio.http.http_client import TwilioHttpClient
    from twilio.rest import Client

    sid = account_sid()
    token = auth_token()
    if not sid or not token:
        raise RuntimeError("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN missing")
    return Client(sid, token, http_client=TwilioHttpClient(timeout=10))


def lookup_customer_for_caller(from_number: str | None) -> dict[str, Any] | None:
    """Best-effort CRM match for an inbound PSTN caller."""
    phone = digits_only(from_number)
    if not phone:
        return None
    try:
        import db
        from sqlalchemy import text

        row = db.find_customer_by_phone(phone)
        if not row:
            return None
        with db.engine.connect() as conn:
            acct = conn.execute(
                text(
                    """
                    SELECT a.id AS account_id, a.outstanding, a.dpd, p.name AS product
                    FROM accounts a
                    LEFT JOIN products p ON p.id = a.product_id
                    WHERE a.customer_id = :cid
                    ORDER BY a.outstanding DESC NULLS LAST, a.id
                    LIMIT 1
                    """
                ),
                {"cid": row["id"]},
            ).mappings().first()
        return {
            "customerId": row["id"],
            "name": row.get("name"),
            "phone": row.get("phone_primary") or from_number,
            "accountId": (acct or {}).get("account_id"),
            "outstanding": float((acct or {}).get("outstanding") or 0),
            "dpd": int((acct or {}).get("dpd") or 0),
            "product": (acct or {}).get("product"),
        }
    except Exception:
        suffix = "".join(ch for ch in str(phone or "") if ch.isdigit())[-4:]
        logger.exception("caller CRM lookup failed for ***%s", suffix or "?")
        return None
