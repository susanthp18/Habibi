"""CRM: customers, interactions, callbacks, disputes, documents, leads.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import asyncio

import logging

import db
import json

from fastapi import APIRouter
from fastapi import (
    File,
    Form,
    HTTPException,
    Header,
    Query,
    Response,
    UploadFile,
)
from schemas import (
    CallResponse,
    CallbackCreateRequest,
    CallbackListResponse,
    CallbackPatchRequest,
    ContactPolicyResponse,
    CustomerInsightsResponse,
    CustomerNoteCreateRequest,
    CustomerResponse,
    DisputeCreateRequest,
    DisputeEvidenceWriteResponse,
    DisputeListResponse,
    DisputeNoteCreateRequest,
    DisputeNoteWriteResponse,
    DisputePatchRequest,
    DisputeResponse,
    DocumentDeliveryAttemptCreateRequest,
    DocumentDeliveryAttemptResponse,
    DocumentIngestResponse,
    DocumentListResponse,
    DocumentPatchRequest,
    DocumentRequestCreateRequest,
    DocumentRequestResponse,
    EvidenceCreateRequest,
    FollowupPatchRequest,
    IdStatusResponse,
    InteractionCostResponse,
    InteractionCreateRequest,
    InteractionWrapUpRequest,
    LeadCreateRequest,
    LeadMetricsResponse,
    LeadPatchRequest,
    LeadResponse,
    LeadRevalidateResponse,
    OutboundHourResponse,
    ProductResponse,
    ReminderCreateRequest,
    TurnTraceResponse,
    WrapUpResponse,
)

from api_support import _handle_write, _read_upload_capped, Utf8JSONResponse, ROUTER_DEPENDENCIES

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.get("/customers", response_model=list[CustomerResponse])
def list_customers(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """Bounded list. Omitting ``limit`` yields the default page, not everything."""
    return db.list_customers(limit=limit, offset=offset)

@router.get("/customers/{customer_id}", response_model=CustomerResponse)
def get_customer(customer_id: str):
    customer = db.get_customer(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer

@router.get("/customers/{customer_id}/insights", response_model=CustomerInsightsResponse)
def get_customer_insights(customer_id: str):
    insights = db.get_customer_insights(customer_id)
    if insights is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return insights

@router.get("/customers/{customer_id}/contact-policy", response_model=ContactPolicyResponse)
def get_contact_policy(
    customer_id: str,
    channel: str = Query(default="whatsapp"),
    purpose: str = Query(default="outreach"),
):
    try:
        return db.get_contact_policy(customer_id, channel=channel, purpose=purpose)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

# A download by design (JSON or Markdown with Content-Disposition), not a JSON
# body a model could describe. Listed in tests/test_route_structure.py::_UNTYPED_BY_DESIGN.
@router.get("/interactions/{interaction_id}/export", response_class=Response)
def export_interaction(
    interaction_id: str,
    format: str = Query("json", pattern="^(json|md)$"),
):
    """Everything about one call, as a download.

    Reviewing a call used to mean reading the container log by hand against
    five Postgres tables. This is the same material in one file: transcript with
    per-turn intent and sentiment, the stage-by-stage latency split, every tool
    call and its arguments, KB retrievals, guardrail flags and the tuning that
    was actually in force. ``format=md`` renders it for pasting into a model.
    """
    from voice import call_export

    bundle = call_export.build_bundle(interaction_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="unknown_interaction")
    if format == "md":
        return Response(
            content=call_export.render_markdown(bundle),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="call-{interaction_id}.md"'
                ),
                # A transcript with the borrower's words in it is never cached
                # by a proxy or served to the next session from disk.
                "Cache-Control": "private, no-store",
            },
        )
    return Response(
        content=json.dumps(bundle, indent=2, default=str),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="call-{interaction_id}.json"',
            "Cache-Control": "private, no-store",
        },
    )

@router.get("/interactions/{interaction_id}/cost", response_model=InteractionCostResponse)
def get_interaction_cost(interaction_id: str):
    """What this call cost, split by service and model.

    Assembled from usage_events attributed to the interaction. ``attributed`` is
    False when the call carries no events — every call that predates pipeline
    metering is in that state, and it must not be shown as a genuine ₹0.00.
    """
    return db.interaction_cost(interaction_id)

@router.get("/interactions/{interaction_id}/trace", response_model=list[TurnTraceResponse])
def get_turn_trace(interaction_id: str):
    """Per-turn timeline: tool calls, retrievals and the latency breakdown.

    Assembles what were three non-joinable grains (bot_tool_calls by job_id,
    retrieval_logs by interaction_id, latency on interaction_transcript) into
    one view keyed by transcript turn. Tool args and result previews are
    redacted on the way out — see db._trace_redact.
    """
    try:
        return db.get_turn_trace(interaction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.get("/products", response_model=list[ProductResponse])
def list_products(includeInactive: bool = Query(False)):
    """Offer catalog — the single source of truth for product ids.

    Both the UI pickers and the recommender read this. Anything that hardcodes
    a product list drifts from what check_product_eligibility will accept.
    """
    return db.list_products(include_inactive=includeInactive)

def _lead_filters(
    stage: str | None,
    owner: str | None,
    team: str | None,
    productId: str | None,
    source: str | None,
    priority: str | None,
    sentiment: str | None,
    q: str | None,
) -> dict[str, str | None]:
    return {
        "stage": stage,
        "owner": owner,
        "team": team,
        "productId": productId,
        "source": source,
        "priority": priority,
        "sentiment": sentiment,
        "q": q,
    }

@router.get("/leads", response_model=list[LeadResponse])
def list_leads(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
    stage: str | None = Query(default=None),
    owner: str | None = Query(default=None, description="Owner display name, or 'all'"),
    team: str | None = Query(default=None),
    productId: str | None = Query(default=None),
    source: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    sentiment: str | None = Query(default=None),
    q: str | None = Query(default=None, description="Free text over id, customer, account, product, snippet"),
):
    return db.list_leads(
        limit=limit,
        offset=offset,
        filters=_lead_filters(stage, owner, team, productId, source, priority, sentiment, q),
    )

@router.get("/leads/metrics", response_model=LeadMetricsResponse)
def get_lead_metrics(
    stage: str | None = Query(default=None),
    owner: str | None = Query(default=None),
    team: str | None = Query(default=None),
    productId: str | None = Query(default=None),
    source: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    sentiment: str | None = Query(default=None),
    q: str | None = Query(default=None),
):
    """Pipeline KPIs over the whole book, not over one page of it.

    Declared before /leads/{lead_id} would be — there is no such route today,
    but "metrics" is a legal lead id as far as a path parameter is concerned,
    and the ordering is what keeps it that way.
    """
    return db.lead_metrics(
        _lead_filters(stage, owner, team, productId, source, priority, sentiment, q)
    )

@router.get("/disputes", response_model=list[DisputeListResponse])
def list_disputes(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_disputes(limit=limit, offset=offset)

@router.get("/callbacks", response_model=list[CallbackListResponse])
def list_callbacks(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_callbacks(limit=limit, offset=offset)

@router.post("/interactions", response_model=CallResponse)
def create_interaction(payload: InteractionCreateRequest, idempotency_key: str | None = Header(default=None)):
    return _handle_write(db.create_interaction, payload.model_dump(), idempotency_key)

@router.post(
    "/interactions/{interaction_id}/wrap-up",
    response_model=WrapUpResponse,
    response_model_exclude_unset=True,
)
def wrap_up_interaction(interaction_id: str, payload: InteractionWrapUpRequest, idempotency_key: str | None = Header(default=None)):
    return _handle_write(db.wrap_up_interaction, interaction_id, payload.model_dump(exclude_none=True), idempotency_key)

@router.post("/disputes", response_model=DisputeResponse)
def create_dispute(payload: DisputeCreateRequest, idempotency_key: str | None = Header(default=None)):
    return _handle_write(db.create_dispute, payload.model_dump(exclude_none=True), idempotency_key)

@router.patch("/disputes/{dispute_id}", response_model=DisputeResponse)
def patch_dispute(dispute_id: str, payload: DisputePatchRequest):
    # exclude_unset (not exclude_none) so an explicit null clears the assignee.
    return _handle_write(db.patch_dispute, dispute_id, payload.model_dump(exclude_unset=True))

@router.post("/disputes/{dispute_id}/notes", response_model=DisputeNoteWriteResponse)
def add_dispute_note(dispute_id: str, payload: DisputeNoteCreateRequest):
    return _handle_write(db.add_dispute_note, dispute_id, payload.model_dump())

@router.post(
    "/disputes/{dispute_id}/evidence",
    response_model=DisputeEvidenceWriteResponse,
    response_model_exclude_unset=True,
)
def add_dispute_evidence(dispute_id: str, payload: EvidenceCreateRequest):
    return _handle_write(db.add_dispute_evidence, dispute_id, payload.model_dump(exclude_none=True))

@router.post("/callbacks", response_model=IdStatusResponse)
def create_callback(payload: CallbackCreateRequest, idempotency_key: str | None = Header(default=None)):
    return _handle_write(db.create_callback, payload.model_dump(exclude_none=True), idempotency_key)

@router.patch("/callbacks/{callback_id}", response_model=IdStatusResponse)
def patch_callback(callback_id: str, payload: CallbackPatchRequest):
    # exclude_unset (not exclude_none) so an explicit null clears the assignee.
    return _handle_write(db.patch_callback, callback_id, payload.model_dump(exclude_unset=True))

@router.post("/callbacks/{callback_id}/reminders", response_model=IdStatusResponse)
def add_callback_reminder(callback_id: str, payload: ReminderCreateRequest):
    return _handle_write(db.add_callback_reminder, callback_id, payload.model_dump(exclude_none=True))

@router.post("/leads", response_model=LeadResponse)
def create_lead(payload: LeadCreateRequest, idempotency_key: str | None = Header(default=None)):
    body = payload.model_dump(exclude_none=True)
    allow_duplicate = bool(body.pop("allowDuplicate", False))
    return _handle_write(
        db.create_lead, body, idempotency_key, allow_duplicate=allow_duplicate
    )

@router.patch("/leads/{lead_id}", response_model=LeadResponse)
def patch_lead(lead_id: str, payload: LeadPatchRequest):
    # exclude_unset, not exclude_none: the state machine distinguishes "field
    # not sent" from "field explicitly cleared". exclude_none collapsed both
    # into absent, so lossReason could be set but never removed.
    return _handle_write(db.patch_lead, lead_id, payload.model_dump(exclude_unset=True))

@router.post(
    "/leads/{lead_id}/revalidate",
    response_model=LeadRevalidateResponse,
    response_model_exclude_unset=True,
)
def revalidate_lead(lead_id: str, channel: str | None = Query(default=None)):
    """Re-check a lead's eligibility against today's consent and account facts."""
    return _handle_write(db.revalidate_lead_eligibility, lead_id, channel)

@router.post("/leads/{lead_id}/followups", response_model=IdStatusResponse)
def add_lead_followup(lead_id: str, payload: ReminderCreateRequest):
    return _handle_write(db.add_lead_followup, lead_id, payload.model_dump(exclude_none=True))

@router.patch("/followups/{followup_id}", response_model=IdStatusResponse)
def patch_followup(followup_id: str, payload: FollowupPatchRequest):
    return _handle_write(db.patch_followup, followup_id, payload.model_dump(exclude_none=True))

@router.post("/document-requests", response_model=DocumentRequestResponse)
def create_document_request(
    payload: DocumentRequestCreateRequest, idempotency_key: str | None = Header(default=None)
):
    return _handle_write(db.create_document_request, payload.model_dump(exclude_none=True), idempotency_key)

@router.post("/document-requests/ingest", response_model=DocumentIngestResponse)
async def ingest_document_request(
    customer_id: str = Form(...),
    conversation_id: str | None = Form(None),
    interaction_id: str | None = Form(None),
    file: UploadFile = File(...),
):
    from agent_core.vision import ingest_customer_document
    from agent_core.tools.gates import interaction_identity_verified

    raw = await _read_upload_capped(file, max_bytes=8 * 1024 * 1024)
    # A vision call and a DB write, off the loop like kb_upload_document.
    result = await asyncio.to_thread(
        ingest_customer_document,
        customer_id=customer_id,
        filename=file.filename or "receipt.jpg",
        mime_type=file.content_type or "image/jpeg",
        identity_verified=interaction_identity_verified(
            interaction_id=interaction_id,
            customer_id=customer_id,
        ),
        interaction_id=interaction_id,
        requested_via="inbox",
        size_bytes=len(raw),
    )
    if not result.ok:
        code = 403 if result.error == "identity_not_verified" else 400
        if result.error == "vision_ingest_disabled":
            code = 404
        raise HTTPException(status_code=code, detail=result.error)
    return result.data

@router.get("/document-requests", response_model=list[DocumentListResponse])
def list_document_requests(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_documents(limit=limit, offset=offset)

@router.patch("/document-requests/{document_id}", response_model=DocumentRequestResponse)
def patch_document_request(document_id: str, payload: DocumentPatchRequest):
    # exclude_unset (not exclude_none) so explicit nulls clear assignee / failedReason.
    return _handle_write(db.patch_document_request, document_id, payload.model_dump(exclude_unset=True))

@router.post(
    "/document-requests/{document_id}/delivery-attempts",
    response_model=DocumentDeliveryAttemptResponse,
)
def add_document_delivery_attempt(document_id: str, payload: DocumentDeliveryAttemptCreateRequest):
    return _handle_write(
        db.add_document_delivery_attempt, document_id, payload.model_dump(exclude_none=True)
    )

@router.post("/customers/{customer_id}/notes", response_model=CustomerResponse)
def add_customer_note(customer_id: str, payload: CustomerNoteCreateRequest):
    return _handle_write(db.add_customer_note, customer_id, payload.model_dump())

@router.get("/customers/{customer_id}/outbound/hours", response_model=list[OutboundHourResponse])
def outbound_hourly(customer_id: str, days: int = Query(default=90, ge=1, le=365)):
    """Per-hour answer rate for one borrower, in their own local time.

    This is what ``treatment/features.responsive_hours`` should eventually read:
    unlike the connect-only version, it has a denominator.
    """
    import db_outbound

    return db_outbound.hourly_reach(customer_id, days=days)

