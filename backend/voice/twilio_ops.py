"""Twilio Voice helpers — TwiML dial-in, outbound, warm conference transfer.

Sandbox Live stays on SmallWebRTC. This module is the PSTN path:

  Caller → Twilio number → POST /twilio/voice/incoming (API :8000)
        → TwiML <Connect><Stream wss://VOICE_PUBLIC/ws/></Connect>
        → Pipecat runner (:7860) with ``-t twilio`` / auto-detect

Human takeover defaults to Habibi Inbox (``VOICE_HANDOFF_MODE=callback_queue``).
``warm`` redirects the live CallSid into a Twilio Conference and dials
``SUPERVISOR_CALLBACK_PHONE`` — requires the supervisor number to be a
Verified Caller ID on trial, and geo permissions that allow the dial.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from xml.sax.saxutils import escape

from env_loader import load_env

logger = logging.getLogger(__name__)


def _env(name: str, default: str = "") -> str:
    load_env()
    return (os.getenv(name) or default).strip()


def account_sid() -> str:
    return _env("TWILIO_ACCOUNT_SID")


def auth_token() -> str:
    return _env("TWILIO_AUTH_TOKEN")


def twilio_phone() -> str:
    return _env("TWILIO_PHONE_NUMBER")


def supervisor_phone() -> str:
    return _env("SUPERVISOR_CALLBACK_PHONE")


def handoff_mode() -> str:
    mode = (_env("VOICE_HANDOFF_MODE", "callback_queue") or "callback_queue").lower()
    if mode in {"warm", "warm_transfer", "conference"}:
        return "warm"
    return "callback_queue"


def voice_public_base_url() -> str:
    """HTTPS origin for Media Streams.

    When ``VOICE_WS_VIA_API`` is on (default), Twilio Stream hits the *API*
    ngrok (``PUBLIC_BASE_URL``) and FastAPI proxies ``/ws`` → voice :7860.
    Otherwise set ``VOICE_PUBLIC_BASE_URL`` to a dedicated ngrok on :7860.
    """
    from voice.ws_proxy import ws_proxy_enabled

    if ws_proxy_enabled():
        via_api = _env("PUBLIC_BASE_URL") or _env("VOICE_PUBLIC_BASE_URL")
        return via_api.rstrip("/")
    return _env("VOICE_PUBLIC_BASE_URL").rstrip("/")


def media_stream_wss_url() -> str:
    base = voice_public_base_url()
    if not base:
        raise RuntimeError(
            "PUBLIC_BASE_URL required for Twilio Media Streams when VOICE_WS_VIA_API=true "
            "(same ngrok as WhatsApp). Or set VOICE_PUBLIC_BASE_URL + VOICE_WS_VIA_API=false "
            "for a dedicated voice tunnel."
        )
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :] + "/ws"
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :] + "/ws"
    if base.startswith("wss://") or base.startswith("ws://"):
        return base.rstrip("/") + ("/ws" if not base.rstrip("/").endswith("/ws") else "")
    return f"wss://{base}/ws"


def configured() -> bool:
    return bool(account_sid() and auth_token() and twilio_phone())


def digits_only(phone: str | None) -> str:
    return re.sub(r"\D+", "", phone or "")


def twiml_connect_stream(*, custom: dict[str, str] | None = None) -> str:
    """TwiML that bridges the call into the Pipecat Twilio WebSocket."""
    url = escape(media_stream_wss_url())
    params_xml = ""
    for key, value in (custom or {}).items():
        if value is None:
            continue
        params_xml += (
            f'\n      <Parameter name="{escape(str(key))}" value="{escape(str(value))}" />'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "  <Connect>\n"
        f'    <Stream url="{url}">{params_xml}\n'
        "    </Stream>\n"
        "  </Connect>\n"
        "</Response>\n"
    )


def twiml_say_hangup(message: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f"  <Say voice=\"Polly.Aditi\">{escape(message)}</Say>\n"
        "  <Hangup/>\n"
        "</Response>\n"
    )


def twiml_dial_conference(conference_name: str, *, end_on_exit: bool = False) -> str:
    end_attr = ' endConferenceOnExit="true"' if end_on_exit else ""
    name = escape(conference_name)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "  <Dial>\n"
        f'    <Conference startConferenceOnEnter="true" beep="false"{end_attr}>'
        f"{name}</Conference>\n"
        "  </Dial>\n"
        "</Response>\n"
    )


def _client():
    from twilio.rest import Client

    sid = account_sid()
    token = auth_token()
    if not sid or not token:
        raise RuntimeError("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN missing")
    return Client(sid, token)


def fetch_call(call_sid: str) -> dict[str, Any]:
    call = _client().calls(call_sid).fetch()
    return {
        "callSid": call.sid,
        "from": call.from_,
        "to": call.to,
        "status": call.status,
        "direction": call.direction,
    }


def start_outbound_call(
    *,
    to: str,
    custom: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Dial ``to`` and connect the answer leg into Media Streams."""
    from_number = twilio_phone()
    if not from_number:
        raise RuntimeError("TWILIO_PHONE_NUMBER missing")
    twiml = twiml_connect_stream(
        custom={
            "call_type": "outbound",
            **(custom or {}),
        }
    )
    call = _client().calls.create(to=to, from_=from_number, twiml=twiml)
    logger.info("Twilio outbound started call_sid=%s to=%s", call.sid, to)
    return {"callSid": call.sid, "to": to, "status": call.status}


def warm_transfer_to_supervisor(
    call_sid: str,
    *,
    supervisor: str | None = None,
    reason: str = "customer_requested",
) -> dict[str, Any]:
    """Move the live caller into a conference and dial the supervisor.

    The Media Stream WebSocket will drop when the call is redirected — the bot
    should treat that as a clean handoff end, not an error.
    """
    target = supervisor or supervisor_phone()
    if not target:
        raise RuntimeError("SUPERVISOR_CALLBACK_PHONE missing for warm transfer")
    if not call_sid:
        raise RuntimeError("call_sid required for warm transfer")

    conference = f"bb-handoff-{call_sid[-12:]}"
    client = _client()
    from_number = twilio_phone()

    # 1) Redirect the customer into the conference.
    client.calls(call_sid).update(twiml=twiml_dial_conference(conference, end_on_exit=False))

    # 2) Dial the supervisor into the same conference.
    agent_call = client.calls.create(
        to=target,
        from_=from_number,
        twiml=twiml_dial_conference(conference, end_on_exit=True),
    )
    logger.info(
        "Twilio warm transfer call_sid=%s supervisor=%s conference=%s agent_call=%s reason=%s",
        call_sid,
        target,
        conference,
        agent_call.sid,
        reason,
    )
    return {
        "mode": "warm",
        "callSid": call_sid,
        "agentCallSid": agent_call.sid,
        "conference": conference,
        "supervisor": target,
        "reason": reason,
    }


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
        logger.exception("caller CRM lookup failed for %s", phone)
        return None
