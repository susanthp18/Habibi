"""Webhook endpoints, deliveries, event types.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import asyncio
import db
import json
import ops_screens
import whatsapp

from fastapi import APIRouter

from api_support import Utf8JSONResponse, ROUTER_DEPENDENCIES
from fastapi import (
    HTTPException,
    Header,
    Query,
    Request,
    Response,
)
from fastapi.responses import PlainTextResponse
from schemas import (
    EventTypeResponse,
    OkResponse,
    PaymentEventWebhookResponse,
    PaymentWebhookResponse,
    WebhookDeliveryResponse,
    WebhookEndpointPatchRequest,
    WebhookEndpointResponse,
    WebhookEndpointUpsertRequest,
    WhatsAppWebhookResponse,
)

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.post(
    "/webhooks/payments/{provider}",
    response_model=PaymentWebhookResponse,
    response_model_exclude_unset=True,
)
async def payment_provider_webhook(provider: str, request: Request):
    """HMAC-verified PSP webhook → ledger + PTP allocate."""
    import payments

    raw = await request.body()
    sig = request.headers.get("X-Payment-Signature") or request.headers.get("X-Razorpay-Signature")
    if not payments.verify_webhook_signature(provider_name=provider, raw_body=raw, header=sig):
        raise HTTPException(status_code=401, detail="invalid_signature")
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    parsed = payments.parse_webhook_payload(provider, body if isinstance(body, dict) else {})
    amount = parsed.get("amount")
    if amount is None:
        raise HTTPException(status_code=400, detail="amount_required")

    try:
        return await asyncio.to_thread(payments.record_provider_payment, parsed)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post(
    "/webhooks/collections/payment-events",
    response_model=PaymentEventWebhookResponse,
    response_model_exclude_unset=True,
)
async def payment_events_webhook(request: Request):
    """HMAC-verified CBS bounce ingest → case + statutory pay-link."""
    import payment_events as pe

    raw = await request.body()
    sig = (
        request.headers.get("X-Payment-Events-Signature")
        or request.headers.get("X-Payment-Signature")
    )
    if not pe.verify_webhook_signature(raw_body=raw, header=sig):
        raise HTTPException(status_code=401, detail="invalid_signature")
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid_json")
    # Off the event loop: the ingest holds row locks and the delivery talks to
    # the carrier, and neither belongs on the thread every other request shares.
    try:
        return await asyncio.to_thread(pe.ingest_and_deliver, db.engine, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/event-types", response_model=list[EventTypeResponse])
def list_event_types():
    return ops_screens.list_event_types()

@router.get("/webhook-endpoints", response_model=list[WebhookEndpointResponse])
def list_webhook_endpoints():
    return ops_screens.list_webhook_endpoints()

@router.post("/webhook-endpoints", response_model=WebhookEndpointResponse)
def create_webhook_endpoint(payload: WebhookEndpointUpsertRequest):
    try:
        return ops_screens.create_webhook_endpoint(payload.model_dump(mode="json"))
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.patch("/webhook-endpoints/{endpoint_id}", response_model=WebhookEndpointResponse)
def patch_webhook_endpoint(endpoint_id: str, payload: WebhookEndpointPatchRequest):
    try:
        return ops_screens.patch_webhook_endpoint(
            endpoint_id, payload.model_dump(mode="json", exclude_unset=True)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.delete("/webhook-endpoints/{endpoint_id}", response_model=OkResponse)
def delete_webhook_endpoint(endpoint_id: str):
    try:
        ops_screens.delete_webhook_endpoint(endpoint_id)
        return {"ok": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/webhook-endpoints/{endpoint_id}/rotate-secret", response_model=WebhookEndpointResponse)
def rotate_webhook_secret(endpoint_id: str):
    try:
        return ops_screens.rotate_webhook_secret(endpoint_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/webhook-endpoints/{endpoint_id}/test", response_model=WebhookDeliveryResponse)
def test_webhook_endpoint(endpoint_id: str, event: str | None = Query(default=None)):
    try:
        return ops_screens.test_fire_webhook(endpoint_id, event)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.get("/webhook-deliveries", response_model=list[WebhookDeliveryResponse])
def list_webhook_deliveries(endpointId: str | None = Query(default=None)):
    return ops_screens.list_webhook_deliveries(endpointId)

@router.post("/webhook-deliveries/{delivery_id}/retry", response_model=WebhookDeliveryResponse)
def retry_webhook_delivery(delivery_id: str):
    try:
        return ops_screens.retry_webhook_delivery(delivery_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

# text/plain by design: Meta expects hub.challenge echoed back verbatim. Listed
# in tests/test_route_structure.py::_UNTYPED_BY_DESIGN.
@router.get("/webhooks/whatsapp", response_class=PlainTextResponse)
@router.get("/webhook/whatsapp", response_class=PlainTextResponse)  # Meta UI sometimes omits the plural "s"
def whatsapp_webhook_verify(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification challenge."""
    import hmac

    cfg = whatsapp.config()
    expected = cfg.get("verify_token")
    if (
        hub_mode == "subscribe"
        and expected
        and hmac.compare_digest(str(hub_verify_token or ""), str(expected))
        and hub_challenge is not None
    ):
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="whatsapp_verify_failed")

@router.post("/webhooks/whatsapp", response_model=WhatsAppWebhookResponse, response_model_exclude_unset=True)
@router.post("/webhook/whatsapp", response_model=WhatsAppWebhookResponse, response_model_exclude_unset=True)
async def whatsapp_webhook_receive(
    request: Request,
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
):
    """Inbound WhatsApp messages + delivery status callbacks from Meta."""
    import json as _json

    raw = await request.body()
    cfg = whatsapp.config()
    if not whatsapp.verify_signature(cfg.get("app_secret"), raw, x_hub_signature_256):
        raise HTTPException(status_code=403, detail="invalid_signature")
    try:
        payload = _json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    # Sync DB + enqueue off the event loop (this route is async def).
    return await asyncio.to_thread(db.process_whatsapp_webhook, payload)

