"""Payments: pay links, plans, promises.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import db

from fastapi import APIRouter
from fastapi import (
    HTTPException,
    Header,
    Query,
    Request,
)
from fastapi.responses import HTMLResponse
from schemas import (
    PaymentPlanCreateRequest,
    PaymentPlanResponse,
    PromiseCreateRequest,
    PromiseListResponse,
    PromisePatchRequest,
    PromiseResponse,
)

from api_support import _handle_write, Utf8JSONResponse, ROUTER_DEPENDENCIES

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.get("/pay/{token}", response_class=HTMLResponse)
def hosted_pay_page(token: str):
    """Public hosted checkout for a payment intent. No app shell."""
    import payments

    with db.engine.begin() as conn:
        intent = payments.load_intent_by_token(conn, token)
        if intent is None:
            raise HTTPException(status_code=404, detail="pay_link_not_found")
        payments.mark_opened(conn, intent["id"])
        intent["status"] = "opened" if intent["status"] in {"created", "sent"} else intent["status"]
        return HTMLResponse(payments.render_pay_page(intent))

@router.post("/pay/{token}/complete")
def hosted_pay_complete(token: str, request: Request):
    """Sandbox-only: post a payment against a hosted intent."""
    import payments

    if payments.is_production() or payments.provider() != "hosted":
        raise HTTPException(status_code=403, detail="hosted_complete_disabled")
    with db.engine.begin() as conn:
        intent = payments.load_intent_by_token(conn, token)
        if intent is None:
            raise HTTPException(status_code=404, detail="pay_link_not_found")
        try:
            result = payments.record_payment(
                conn,
                public_token=token,
                amount=intent["amount"],
                provider_ref=f"hosted:{token[:8]}",
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    accept = (request.headers.get("accept") or "").lower()
    if "text/html" in accept or request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
        with db.engine.connect() as conn:
            refreshed = payments.load_intent_by_token(conn, token) or intent
        return HTMLResponse(payments.render_pay_page(refreshed))
    return result

@router.get("/promises", response_model=list[PromiseListResponse])
def list_promises(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_promises(limit=limit, offset=offset)

@router.get("/payment-plans", response_model=list[PaymentPlanResponse])
def list_payment_plans(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_payment_plans(limit=limit, offset=offset)

@router.post("/promises", response_model=PromiseResponse)
def create_promise(payload: PromiseCreateRequest, idempotency_key: str | None = Header(default=None)):
    return _handle_write(db.create_promise, payload.model_dump(exclude_none=True), idempotency_key)

@router.patch("/promises/{promise_id}", response_model=PromiseResponse)
def patch_promise(promise_id: str, payload: PromisePatchRequest):
    return _handle_write(db.patch_promise, promise_id, payload.model_dump(exclude_none=True))

@router.post("/promises/{promise_id}/resend-confirm")
def resend_promise_confirm(promise_id: str):
    return _handle_write(db.resend_promise_confirm, promise_id)

@router.post("/payment-plans")
def create_payment_plan(payload: PaymentPlanCreateRequest):
    return _handle_write(db.create_payment_plan, payload.model_dump())

