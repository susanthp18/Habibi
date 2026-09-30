"""Telephony: calls, Twilio webhooks, and the operator's outbound dial.

Voice Studio (the engine) carries every call's audio. What is left here is
the call record, a number's inbound webhook handed to the engine, the voice
fallback, SMS delivery receipts, and the operator's gated outbound dial.
"""

from __future__ import annotations

import asyncio
import db
import logging
import os

from fastapi import APIRouter
from fastapi import (
    HTTPException,
    Query,
    Request,
    Response,
)
from schemas import (
    CallResponse,
    TwilioOutboundCallRequest,
    TwilioOutboundCallResponse,
)
from typing import Any

from api_support import Utf8JSONResponse, ROUTER_DEPENDENCIES

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


@router.get("/calls/{interaction_id}", response_model=CallResponse)
def get_call(interaction_id: str):
    """One call, for a deep link (Compliance "Open in Audit") outside the loaded page."""
    rows = db.list_calls(limit=1, interaction_id=interaction_id)
    if not rows:
        raise HTTPException(status_code=404, detail="call_not_found")
    return rows[0]

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

# The Twilio webhooks below answer in TwiML or with an empty 204, never
# JSON — listed in tests/test_route_structure.py::_UNTYPED_BY_DESIGN.
@router.post("/twilio/voice/incoming", response_class=TwiMLResponse)
async def twilio_voice_incoming(request: Request):
    """Twilio Voice webhook -- hand the call to the Voice Studio engine."""
    from voice import twilio_ops

    form = dict(await request.form())
    if not _twilio_signature_ok(request, form):
        raise HTTPException(status_code=403, detail="invalid_twilio_signature")

    # Voice Studio answers every call: a number still pointed at this webhook
    # is handed to the engine.
    import voice_studio

    handoff = voice_studio.inbound_handoff_twiml()
    if handoff is None:
        logger.error("Twilio inbound CallSid=%s: AGENTSTUDIO_PUBLIC_URL unset; refusing", form.get("CallSid"))
        return Response(
            content=twilio_ops.twiml_say_hangup("We're sorry, the voice agent is temporarily unavailable."),
            media_type="application/xml",
        )
    return Response(content=handoff, media_type="application/xml")

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
        customer_id=request.query_params.get("c"),
        related_id=request.query_params.get("r"),
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
    """Start an operator's outbound call, answered by the Voice Studio agent.

    The order here is the design's, not a convenience: the attempt row is
    written and committed **before** the contact gate runs, so a refusal has
    something to attach to. That is what turns the eleven ``contact_policy``
    denial reasons into a queryable denial rate instead of a log line, and it
    is the record that answers "why did nobody call this borrower on Tuesday".

    The path says Twilio for wire compatibility; Voice Studio places the call.
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
