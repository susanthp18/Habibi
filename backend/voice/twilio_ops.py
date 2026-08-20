"""Twilio Voice helpers — TwiML dial-in, outbound, warm conference transfer.

Sandbox Live stays on SmallWebRTC. This module is the PSTN path:

  Caller → Twilio number → POST /twilio/voice/incoming (API :8000)
        → TwiML <Connect><Stream wss://…/ws[/{secret}]/></Connect>
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
from xml.sax.saxutils import escape, quoteattr

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
    """The mode the *runtime* will actually use, for status reporting.

    Delegates to :func:`voice.config.voice_handoff_mode` rather than re-parsing
    the variable. This used to be a third, more lenient copy of that logic, so
    ``GET /twilio/voice/status`` could report a mode the escalation path would
    never choose — a status endpoint disagreeing with the behaviour it claims to
    describe is worse than no status endpoint.

    The strict version raises on an unrecognised value; a status read must not
    500, so the same fallback ``voice.tools._transfer_mode`` applies is mirrored
    here, with the misconfiguration logged rather than hidden.
    """
    try:
        from voice.config import voice_handoff_mode

        return voice_handoff_mode()
    except RuntimeError as exc:
        logger.error("VOICE_HANDOFF_MODE is invalid (%s) — reporting callback_queue", exc)
        return "callback_queue"
    except Exception:
        logger.exception("handoff mode unreadable — reporting callback_queue")
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


def voice_https_public_base_url() -> str:
    """HTTPS origin for Twilio HTTP callbacks (fallback / status), not wss."""
    base = voice_public_base_url()
    if not base:
        return ""
    if base.startswith("https://"):
        return base.rstrip("/")
    if base.startswith("wss://"):
        return "https://" + base[len("wss://") :].rstrip("/")
    if base.startswith("http://"):
        raise RuntimeError("Twilio callbacks require https PUBLIC_BASE_URL")
    if base.startswith("ws://"):
        raise RuntimeError("Twilio callbacks require https PUBLIC_BASE_URL")
    return f"https://{base.rstrip('/')}"


def media_stream_wss_url() -> str:
    """Build the Media Streams ``wss://`` URL.

    Twilio ``<Stream url>`` does **not** support query strings (error 31920).
    When ``VOICE_WS_PROXY_SECRET`` is set, embed it as a path segment
    ``/ws/{secret}`` so the upgrade gate can authorize without query params.
    """
    base = voice_public_base_url()
    if not base:
        raise RuntimeError(
            "PUBLIC_BASE_URL required for Twilio Media Streams when VOICE_WS_VIA_API=true "
            "(same ngrok as WhatsApp). Or set VOICE_PUBLIC_BASE_URL + VOICE_WS_VIA_API=false "
            "for a dedicated voice tunnel."
        )
    if base.startswith("https://"):
        host_path = base[len("https://") :].rstrip("/")
        if host_path.endswith("/ws"):
            url = "wss://" + host_path
        else:
            url = "wss://" + host_path + "/ws"
    elif base.startswith("http://"):
        raise RuntimeError(
            "Twilio Media Streams require TLS — set an https:// public base URL "
            "(PUBLIC_BASE_URL / VOICE_PUBLIC_BASE_URL)."
        )
    elif base.startswith("ws://"):
        raise RuntimeError(
            "Twilio Media Streams require TLS — use wss://, not ws://, for the "
            "voice public base URL."
        )
    elif base.startswith("wss://"):
        url = base.rstrip("/") + ("/ws" if not base.rstrip("/").endswith("/ws") else "")
    else:
        url = f"wss://{base}/ws"

    secret = _env("VOICE_WS_PROXY_SECRET")
    if secret:
        from urllib.parse import quote

        # Path segment only — never ?query= (Twilio Media Streams rejects it).
        url = url.rstrip("/") + "/" + quote(secret, safe="")
    return url


def stream_status_callback_url() -> str | None:
    """Absolute HTTPS URL for ``<Stream statusCallback>`` events."""
    try:
        base = voice_https_public_base_url()
    except RuntimeError:
        return None
    if not base:
        return None
    return f"{base}/twilio/voice/stream-status"


def voice_fallback_url() -> str | None:
    try:
        base = voice_https_public_base_url()
    except RuntimeError:
        return None
    if not base:
        return None
    return f"{base}/twilio/voice/fallback"


def call_status_callback_url() -> str | None:
    try:
        base = voice_https_public_base_url()
    except RuntimeError:
        return None
    if not base:
        return None
    return f"{base}/twilio/voice/call-status"


def configured() -> bool:
    return bool(account_sid() and auth_token() and twilio_phone())


def digits_only(phone: str | None) -> str:
    return re.sub(r"\D+", "", phone or "")


def twiml_connect_stream(*, custom: dict[str, str] | None = None) -> str:
    """TwiML that bridges the call into the Pipecat Twilio WebSocket."""
    # quoteattr, matching the Parameter attributes below: escape() leaves the
    # double-quote character untouched, so a configured URL containing one
    # would close the attribute and inject markup into the TwiML.
    url = quoteattr(media_stream_wss_url())
    status_cb = stream_status_callback_url()
    status_attrs = ""
    if status_cb:
        status_attrs = (
            f" statusCallback={quoteattr(status_cb)} statusCallbackMethod={quoteattr('POST')}"
        )
    params_xml = ""
    for key, value in (custom or {}).items():
        if value is None:
            continue
        # quoteattr() supplies its own quoting and escapes the quote character
        # itself — manual escape()+"..." leaves a value containing a double
        # quote able to close the attribute and inject markup.
        params_xml += (
            f"\n      <Parameter name={quoteattr(str(key))} value={quoteattr(str(value))} />"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "  <Connect>\n"
        f"    <Stream url={url}{status_attrs}>{params_xml}\n"
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
    from twilio.http.http_client import TwilioHttpClient
    from twilio.rest import Client

    sid = account_sid()
    token = auth_token()
    if not sid or not token:
        raise RuntimeError("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN missing")
    return Client(sid, token, http_client=TwilioHttpClient(timeout=10))


def fetch_call(call_sid: str) -> dict[str, Any]:
    call = _client().calls(call_sid).fetch()
    from_num = getattr(call, "from_", None) or getattr(call, "_from", None)
    return {
        "callSid": call.sid,
        "from": from_num,
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
    # Validate before redirecting: without a from_number the supervisor dial
    # below fails, and the customer is already parked alone in a conference
    # with the bot's media stream torn down — a silent dead call.
    if not from_number:
        raise RuntimeError("TWILIO_PHONE_NUMBER missing for warm transfer")

    # Supervisor leg first. Redirecting the customer tears down the bot's media
    # stream, so if the supervisor dial then failed the customer would be parked
    # alone in an empty conference with nothing left to talk to. The supervisor
    # hears conference hold music for the moment before the customer joins.
    agent_call = client.calls.create(
        to=target,
        from_=from_number,
        twiml=twiml_dial_conference(conference, end_on_exit=True),
    )

    try:
        client.calls(call_sid).update(
            twiml=twiml_dial_conference(conference, end_on_exit=False)
        )
    except Exception:
        # Compensate: drop the supervisor rather than leave them ringing into a
        # conference the customer will never reach.
        logger.exception(
            "Twilio warm transfer: customer redirect failed call_sid=%s — "
            "cancelling supervisor leg %s",
            call_sid,
            agent_call.sid,
        )
        try:
            client.calls(agent_call.sid).update(status="completed")
        except Exception:
            logger.exception(
                "Twilio warm transfer: could not cancel supervisor leg %s", agent_call.sid
            )
        raise
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
        suffix = "".join(ch for ch in str(phone or "") if ch.isdigit())[-4:]
        logger.exception("caller CRM lookup failed for ***%s", suffix or "?")
        return None
