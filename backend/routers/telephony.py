"""Telephony: Twilio webhooks, voice sessions, calls, websockets.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import asyncio
import db
import logging
import os
import secrets

from fastapi import APIRouter
from fastapi import (
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
)
from schemas import (
    CallResponse,
    TwilioOutboundCallRequest,
    TwilioOutboundCallResponse,
    TwilioVoiceStatusResponse,
    VoiceSandboxStartRequest,
    VoiceSandboxStartResponse,
    VoiceSandboxStopResponse,
    VoiceSandboxTuneRequest,
    VoiceSandboxTuneResponse,
    VoiceStatusResponse,
)
from typing import Any

from api_support import EMBEDDED_VOICE_HOST as _EMBEDDED_VOICE_HOST, _handle_write, Utf8JSONResponse, ROUTER_DEPENDENCIES

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


class TwiMLResponse(Response):
    """Declared on the Twilio webhook routes so the OpenAPI document says XML.
    The handlers still build their own ``Response`` bodies."""

    media_type = "application/xml"


@router.get("/calls", response_model=list[CallResponse])
def list_calls(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """Bounded list. Each row carries its full transcript, so the default page
    is deliberately smaller than for flat lists."""
    return db.list_calls(limit=limit, offset=offset)

@router.get("/voice/status", response_model=VoiceStatusResponse)
def get_voice_status():
    import voice_sandbox

    return voice_sandbox.voice_status()

@router.post("/voice/sandbox/start", response_model=VoiceSandboxStartResponse)
def start_voice_sandbox_session(payload: VoiceSandboxStartRequest):
    import voice_sandbox

    try:
        return voice_sandbox.start_voice_sandbox(payload.model_dump(exclude_none=True))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.post("/voice/sandbox/{session_id}/stop", response_model=VoiceSandboxStopResponse)
def stop_voice_sandbox_session(session_id: str):
    import voice_sandbox

    return _handle_write(voice_sandbox.stop_voice_sandbox, session_id)

@router.post("/voice/sandbox/{session_id}/tune", response_model=VoiceSandboxTuneResponse)
def tune_voice_sandbox_session(session_id: str, payload: VoiceSandboxTuneRequest):
    import voice_sandbox

    delta = payload.tuning if isinstance(payload.tuning, dict) else payload.model_dump(exclude_none=True)
    return _handle_write(voice_sandbox.tune_voice_sandbox, session_id, delta)

def _twilio_signature_ok(request: Request, form: dict[str, Any]) -> bool:
    """Validate X-Twilio-Signature.

    Fail-closed in every environment: missing ``TWILIO_AUTH_TOKEN`` or missing
    signature → reject. A configured token is not a mode switch, and an unset
    token is a misconfiguration, not an open door.
    """
    from voice import twilio_ops

    token = twilio_ops.auth_token()
    if not token:
        logger.error("TWILIO_AUTH_TOKEN unset — rejecting Twilio request")
        return False
    signature = (request.headers.get("x-twilio-signature") or "").strip()
    if not signature:
        return False
    try:
        from twilio.request_validator import RequestValidator

        validator = RequestValidator(token)
        # Reconstruct the public URL Twilio signed (ngrok HTTPS). Twilio signs
        # the full URL *including* the query string — dropping it makes every
        # signature check on a query-bearing callback fail.
        public = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
        query = request.url.query
        suffix = f"{request.url.path}?{query}" if query else request.url.path
        url = f"{public}{suffix}" if public else str(request.url)
        return bool(validator.validate(url, form, signature))
    except Exception:
        logger.exception("Twilio signature validation failed open=false")
        return False

def _voice_ws_secrets_equal(a: str, b: str) -> bool:
    # No length short-circuit: compare_digest is constant-time only when it
    # runs, and an early `len(a) != len(b)` return told a caller the length.
    if not a or not b:
        return False
    return secrets.compare_digest(a.encode(), b.encode())

def _redact_voice_ws_url(url: str) -> str:
    """Strip path/query proxy secret from logs and status payloads."""
    shared = (os.getenv("VOICE_WS_PROXY_SECRET") or "").strip()
    if not url:
        return url
    if shared and shared in url:
        url = url.replace(shared, "***")
    from urllib.parse import quote

    encoded = quote(shared, safe="") if shared else ""
    if encoded and encoded in url:
        url = url.replace(encoded, "***")
    # Query form (legacy) — drop any remaining proxy_secret value.
    if "proxy_secret=" in url:
        from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

        parts = urlparse(url)
        q = [(k, "***" if k == "proxy_secret" else v) for k, v in parse_qsl(parts.query)]
        url = urlunparse(parts._replace(query=urlencode(q)))
    return url

def _voice_ws_upgrade_authorized(
    websocket: WebSocket, *, path_secret: str | None = None
) -> bool:
    """Gate the Media Streams WS proxy.

    Requires a shared ``VOICE_WS_PROXY_SECRET`` matching (in order):
    path ``/ws/{secret}``, ``X-Voice-Proxy-Secret``, or legacy ``?proxy_secret=``.
    Twilio ``<Stream url>`` cannot use query strings (error 31920) — prefer path.
    Fail-closed in every environment: an unset secret or a missing/invalid
    supplied secret refuses the upgrade.
    """
    shared = (os.getenv("VOICE_WS_PROXY_SECRET") or "").strip()
    provided = (
        (path_secret or "").strip()
        or (websocket.headers.get("x-voice-proxy-secret") or "").strip()
        or (websocket.query_params.get("proxy_secret") or "").strip()
    )
    if shared and provided and _voice_ws_secrets_equal(shared, provided):
        return True

    # Twilio Media Streams authenticate at the HTTP webhook layer; the WS
    # upgrade does not carry X-Twilio-Signature. The proxy secret is the only
    # credential on this socket. A configured TWILIO_AUTH_TOKEN is *not* an
    # authorization signal here — nothing on the upgrade proves the peer holds
    # it. An unset secret is a misconfiguration, not an open door.
    if not shared:
        logger.error(
            "Voice WS proxy rejected: VOICE_WS_PROXY_SECRET is not configured"
        )
    else:
        logger.warning("Voice WS proxy rejected: missing/invalid proxy secret")
    return False

# The five Twilio webhooks below answer in TwiML or with an empty 204, never
# JSON — listed in tests/test_route_structure.py::_UNTYPED_BY_DESIGN.
@router.post("/twilio/voice/incoming", response_class=TwiMLResponse)
async def twilio_voice_incoming(request: Request):
    """Twilio Voice webhook — return TwiML that streams audio to the Pipecat runner."""
    from voice import twilio_ops

    form = dict(await request.form())
    if not _twilio_signature_ok(request, form):
        raise HTTPException(status_code=403, detail="invalid_twilio_signature")

    if not twilio_ops.configured():
        return Response(
            content=twilio_ops.twiml_say_hangup(
                "We're sorry, the voice agent is not configured. Please try again later."
            ),
            media_type="application/xml",
        )

    # At capacity, say so and hang up rather than <Connect><Stream> into a
    # process that will refuse the socket — the caller would otherwise get a
    # connected line and silence. Only meaningful when the pipeline runs in
    # THIS process: with a separate `voice` container the counter here is always
    # zero, and the socket-level refusal in voice.bot is the only backstop.
    if _EMBEDDED_VOICE_HOST:
        from voice import admission

        if not admission.has_capacity():
            logger.warning(
                "Twilio inbound refused at capacity CallSid=%s %s",
                form.get("CallSid"), admission.snapshot(),
            )
            return Response(
                content=twilio_ops.twiml_say_hangup(
                    "All our agents are busy right now. Please call back in a few minutes."
                ),
                media_type="application/xml",
            )

    try:
        stream_url = twilio_ops.media_stream_wss_url()
    except RuntimeError as exc:
        logger.error("Twilio Stream URL unavailable: %s", exc)
        return Response(
            content=twilio_ops.twiml_say_hangup(
                "We're sorry, the voice agent is temporarily unavailable."
            ),
            media_type="application/xml",
        )

    call_sid = str(form.get("CallSid") or "")
    from_number = str(form.get("From") or "")
    to_number = str(form.get("To") or "")
    custom = {
        "call_type": "inbound",
        "from": from_number,
        "to": to_number,
        "call_sid": call_sid,
    }
    xml = twilio_ops.twiml_connect_stream(custom=custom)
    logger.info(
        "Twilio inbound CallSid=%s From=%s → Stream %s",
        call_sid,
        from_number,
        _redact_voice_ws_url(stream_url),
    )
    return Response(content=xml, media_type="application/xml")

@router.post("/twilio/voice/fallback", response_class=TwiMLResponse)
async def twilio_voice_fallback(request: Request):
    """VoiceFallbackUrl — primary webhook failed or timed out."""
    from voice import twilio_ops

    form = dict(await request.form())
    if not _twilio_signature_ok(request, form):
        raise HTTPException(status_code=403, detail="invalid_twilio_signature")

    call_sid = str(form.get("CallSid") or "")
    error_code = str(form.get("ErrorCode") or form.get("errorCode") or "")
    logger.error(
        "Twilio voice fallback CallSid=%s ErrorCode=%s",
        call_sid,
        error_code or None,
    )
    return Response(
        content=twilio_ops.twiml_say_hangup(
            "We're sorry, we could not connect your call. Please try again shortly."
        ),
        media_type="application/xml",
    )

@router.post("/twilio/voice/stream-status", status_code=204, response_class=Response)
async def twilio_voice_stream_status(request: Request):
    """``<Stream statusCallback>`` — stream-started / stopped / error."""
    form = dict(await request.form())
    if not _twilio_signature_ok(request, form):
        raise HTTPException(status_code=403, detail="invalid_twilio_signature")

    event = str(form.get("StreamEvent") or form.get("Event") or "")
    stream_sid = str(form.get("StreamSid") or "")
    call_sid = str(form.get("CallSid") or "")
    error_code = str(form.get("ErrorCode") or "")
    error_message = str(form.get("ErrorMessage") or "")
    level = logging.ERROR if "error" in event.lower() or error_code else logging.INFO
    logger.log(
        level,
        "Twilio Stream status event=%s CallSid=%s StreamSid=%s error=%s %s",
        event or "unknown",
        call_sid or None,
        stream_sid or None,
        error_code or None,
        error_message or "",
    )
    return Response(status_code=204)

@router.post("/twilio/voice/call-status", status_code=204, response_class=Response)
async def twilio_voice_call_status(request: Request):
    """Call StatusCallback — dial / ring / answer / complete.

    This endpoint used to log and return 204. Everything the product could not
    say about outbound calling followed from that: an unanswered dial produced
    no row anywhere, because ``interactions`` is created from
    ``on_client_connected`` and a call that never connects never gets there.
    Answer rate, right-party-contact rate, best-time-to-call and cost per
    connect were all uncomputable from what we kept.

    Now it drives the ``call_attempts`` state machine. Three properties matter:

    * **Idempotent.** Twilio retries callbacks; ``apply_provider_status`` locks
      the row and refuses to re-stamp a terminal state.
    * **Order-insensitive.** Callbacks are not ordered, so a late ``ringing``
      cannot overwrite a ``completed`` that already landed.
    * **Silent on unknown call ids.** Inbound calls have no attempt row, and a
      status endpoint that 4xx'd on them would earn a retry storm.
    """
    form = dict(await request.form())
    if not _twilio_signature_ok(request, form):
        raise HTTPException(status_code=403, detail="invalid_twilio_signature")

    call_sid = str(form.get("CallSid") or "").strip()
    status = str(form.get("CallStatus") or form.get("CallStatusCallbackEvent") or "").strip()
    raw_duration = str(form.get("CallDuration") or form.get("Duration") or "").strip()
    try:
        duration = int(raw_duration) if raw_duration else None
    except ValueError:
        duration = None
    answered_by = str(form.get("AnsweredBy") or "").strip() or None
    error_code = str(form.get("ErrorCode") or "").strip() or None

    logger.info(
        "Twilio call status CallSid=%s status=%s duration=%s answeredBy=%s",
        call_sid or None,
        status or None,
        duration,
        answered_by,
    )
    if not call_sid or not status:
        return Response(status_code=204)

    import db_outbound

    try:
        row = await asyncio.to_thread(
            db_outbound.apply_provider_status,
            provider_call_id=call_sid,
            status=status,
            duration_sec=duration,
            error_code=error_code,
            answered_by=answered_by,
        )
    except Exception:
        # A 500 here makes Twilio retry, which is the right behaviour for a
        # transient database blip and the reason this is not swallowed silently.
        logger.exception("call-status: attempt update failed sid=%s", call_sid)
        raise HTTPException(status_code=500, detail="attempt_update_failed")

    if row is None:
        # Inbound, or a call placed before this table existed. Not an error.
        logger.debug("call-status for unknown attempt sid=%s", call_sid)
    return Response(status_code=204)

@router.post("/twilio/sms/status", status_code=204, response_class=Response)
async def twilio_sms_status(request: Request):
    """SMS StatusCallback — queued / sent / delivered / undelivered / failed.

    Appends one row per transition to the delivery-receipt log. That log is what
    lets the reach estimator answer "does an SMS to this borrower actually
    arrive", which until now had no evidence at all on this channel: the SID was
    logged and dropped, so a delivered message and a dead number looked
    identical.

    The borrower is resolved from the receipt written at send time rather than
    from the phone number in the callback. Matching on the number would attribute
    a delivery to whichever borrower shares it — households and re-issued
    numbers both do — and would work perfectly right up until it silently did
    not.
    """
    form = dict(await request.form())
    if not _twilio_signature_ok(request, form):
        raise HTTPException(status_code=403, detail="invalid_twilio_signature")

    import delivery_receipts

    sid = str(form.get("MessageSid") or form.get("SmsSid") or "").strip()
    state = delivery_receipts.normalise_twilio(
        str(form.get("MessageStatus") or form.get("SmsStatus") or "")
    )
    if not sid or not state:
        # 204 rather than 4xx: an unrecognised status is not something Twilio
        # can fix by retrying, and a retry storm against a status endpoint is
        # how a receipt log becomes an incident.
        return Response(status_code=204)

    known = await asyncio.to_thread(
        delivery_receipts.record_twilio_sms_status,
        sid=sid,
        state=state,
        reason=str(form.get("ErrorCode") or "") or None,
    )
    if not known:
        logger.info("twilio sms status for unknown sid=%s state=%s", sid, state)
    return Response(status_code=204)

@router.post(
    "/twilio/voice/outbound",
    response_model=TwilioOutboundCallResponse,
    response_model_exclude_unset=True,
)
async def twilio_voice_outbound(payload: TwilioOutboundCallRequest, request: Request):
    """Start an outbound PSTN call that connects into the same Media Stream bot.

    The order here is the design's, not a convenience: the attempt row is
    written and committed **before** the contact gate runs, so a refusal has
    something to attach to. That is what turns the eleven ``contact_policy``
    denial reasons into a queryable denial rate instead of a log line, and it
    is the record that answers "why did nobody call this borrower on Tuesday".

    The path says Twilio for wire compatibility; the dial goes to whichever
    provider ``TELEPHONY_PROVIDER`` selects.
    """
    from voice import telephony

    if not telephony.configured():
        raise HTTPException(status_code=503, detail="telephony_not_configured")
    to = payload.to.strip()
    if not to:
        raise HTTPException(status_code=400, detail="to_required")
    customer_id = (payload.customerId or "").strip()
    objective = payload.objective.strip() or "manual_outbound"
    account_id = (payload.accountId or "").strip() or None

    import db_outbound
    import outbound

    # An operator's double-click, or a client that retried a 502, must not ring
    # the borrower twice. The header is the key when the client sends one; a
    # client that does not gets one dial per request, as before.
    idem = (request.headers.get("Idempotency-Key") or "").strip() or None
    bot_id = str(payload.botId or db.DEFAULT_BOT_ID)

    # Reservation and gate run in persistence's own transaction; the handler
    # only dials what the gate allowed.
    gated = await asyncio.to_thread(
        db_outbound.reserve_operator_attempt,
        idempotency_key=f"operator:{idem}" if idem else None,
        customer_id=customer_id,
        to_phone=to,
        objective=objective,
        account_id=account_id,
        bot_id=bot_id,
    )
    attempt = gated.attempt
    if gated.existing:
        # Same key, same answer: the attempt this key already made.
        return {"placed": True, "attemptId": attempt["id"], "state": attempt.get("state"),
                "idempotent": True}
    if not gated.allowed:
        raise HTTPException(status_code=409, detail=gated.reason or "contact_policy")

    custom = {
        k: str(v)
        for k, v in (payload.custom or {}).items()
        if v is not None
    }
    if customer_id:
        custom["customer_id"] = customer_id

    # An ad-hoc dial to a bare number with no customer on file keeps the old
    # path: there is no borrower to attribute an attempt to, and inventing a
    # customer row to satisfy a foreign key would be worse than the gap.
    if attempt is None:
        try:
            return await asyncio.to_thread(telephony.originate, to=to, custom=custom or None)
        except Exception as exc:
            logger.exception("outbound dial failed")
            raise HTTPException(status_code=502, detail="dial_failed") from exc

    result = await asyncio.to_thread(
        outbound.place, db.engine, attempt, to_phone=to, custom=custom or None
    )
    if not result.get("placed"):
        reason = result.get("reason") or "dial_failed"
        raise HTTPException(
            status_code=503 if reason in outbound.UNAVAILABLE_REASONS else 502, detail=reason
        )
    return result

@router.get("/twilio/voice/status", response_model=TwilioVoiceStatusResponse)
def twilio_voice_status():
    from voice import twilio_ops
    from voice.ws_proxy import voice_ws_upstream, ws_proxy_enabled

    raw_stream = (
        twilio_ops.media_stream_wss_url()
        if (twilio_ops.voice_public_base_url() and twilio_ops.configured())
        else None
    )
    return {
        "configured": twilio_ops.configured(),
        "phoneNumber": twilio_ops.twilio_phone() or None,
        "handoffMode": twilio_ops.handoff_mode(),
        "wsViaApi": ws_proxy_enabled(),
        "wsUpstream": voice_ws_upstream() if ws_proxy_enabled() else None,
        "streamUrl": _redact_voice_ws_url(raw_stream) if raw_stream else None,
        "fallbackUrl": twilio_ops.voice_fallback_url(),
        "callStatusCallbackUrl": twilio_ops.call_status_callback_url(),
        "streamStatusCallbackUrl": twilio_ops.stream_status_callback_url(),
        "supervisorPhone": twilio_ops.supervisor_phone() or None,
        "hint": (
            "Same ngrok as WhatsApp (PUBLIC_BASE_URL→:8000). "
            "Voice webhook: POST {PUBLIC_BASE_URL}/twilio/voice/incoming. "
            "Media Stream uses wss://{same-host}/ws[/{VOICE_WS_PROXY_SECRET}] "
            "(no query string — Twilio error 31920). "
            "Start voice: python -m voice.bot -t twilio --host 0.0.0.0 --port 7860"
        ),
    }

async def _voice_media_stream_entry(
    websocket: WebSocket, *, path_secret: str | None = None
) -> None:
    """Twilio Media Streams entry point (shared by ``/ws`` and ``/ws/{secret}``).

    ``VOICE_EMBEDDED_HOST=true`` serves the call here in-process; otherwise the
    socket is bridged to the standalone Pipecat runner on :7860.
    """
    from voice.call_trace import event
    from voice.host import embedded_host_enabled, run_websocket_session
    from voice.ws_proxy import proxy_voice_websocket, ws_proxy_enabled
    import time as _time

    # First line of the socket's story. Without it, "Twilio never connected" and
    # "we refused Twilio" are the same absence of a log line — and they were,
    # for two answered calls that played silence.
    peer = getattr(getattr(websocket, "client", None), "host", None)
    arrived = _time.monotonic()
    event(
        "ws.arrived",
        peer=peer,
        secret="path" if path_secret else "header-or-query",
    )
    try:
        websocket.state.ws_arrived_at = arrived
    except Exception:
        pass

    embedded = embedded_host_enabled()
    if not embedded and not ws_proxy_enabled():
        event("ws.refused", reason="no_host_and_proxy_disabled")
        await websocket.close(code=1008)
        return
    # The upgrade gate applies to both modes — hosting the pipeline in-process
    # makes an unauthenticated socket more dangerous, not less.
    if not _voice_ws_upgrade_authorized(websocket, path_secret=path_secret):
        event("ws.refused", reason="unauthorized", peer=peer)
        await websocket.close(code=1008, reason="unauthorized")
        return
    event("ws.authorized", mode="embedded" if embedded else "proxy")
    if embedded:
        await run_websocket_session(websocket)
        return
    await proxy_voice_websocket(websocket)

@router.websocket("/ws")
async def voice_media_stream_proxy(websocket: WebSocket):
    await _voice_media_stream_entry(websocket)

@router.websocket("/ws/{proxy_secret}")
async def voice_media_stream_proxy_with_secret(
    websocket: WebSocket, proxy_secret: str
):
    await _voice_media_stream_entry(websocket, path_secret=proxy_secret)

