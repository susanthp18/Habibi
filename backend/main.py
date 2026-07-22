"""Collections Agent — CRM backend API.

Run:  .venv/Scripts/python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
Serves read/query endpoints from the normalized Postgres data layer.
"""

from contextlib import asynccontextmanager

from fastapi import Header, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import db
from schemas import (
    BotAnalyticsResponse,
    CallResponse,
    CallbackCreateRequest,
    CallbackListResponse,
    CallbackPatchRequest,
    ConsentListResponse,
    ConsentPatchRequest,
    CustomerNoteCreateRequest,
    CustomerResponse,
    DashboardResponse,
    DisputeCreateRequest,
    DisputeListResponse,
    DisputeNoteCreateRequest,
    DisputePatchRequest,
    DisputeResponse,
    DocumentListResponse,
    DocumentPatchRequest,
    DocumentRequestCreateRequest,
    DocumentRequestResponse,
    EvidenceCreateRequest,
    FollowupPatchRequest,
    HandoffResponse,
    InteractionCreateRequest,
    InteractionWrapUpRequest,
    LeadCreateRequest,
    LeadPatchRequest,
    LeadResponse,
    OptOutCreateRequest,
    PaymentPlanCreateRequest,
    PaymentPlanResponse,
    PromiseCreateRequest,
    PromiseListResponse,
    PromisePatchRequest,
    PromiseResponse,
    ReminderCreateRequest,
    ScorecardCreateRequest,
    ScorecardPatchRequest,
    MeResponse,
    StaffResponse,
    TeamResponse,
    ViolationListResponse,
    ViolationNoteCreateRequest,
    ViolationPatchRequest,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_and_seed()
    yield


app = FastAPI(title="Collections Agent API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # Any localhost port in dev (Vite may fall back to 8081, 8082, ...).
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


def _handle_write(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/customers", response_model=list[CustomerResponse])
def list_customers():
    return db.list_customers()


@app.get("/customers/{customer_id}", response_model=CustomerResponse)
def get_customer(customer_id: str):
    customer = db.get_customer(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@app.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(range: str = "30d", segment: str = "all", team: str = "all"):
    return db.get_dashboard(range, segment, team)


@app.get("/bot-analytics", response_model=BotAnalyticsResponse)
def get_bot_analytics(range: str = "30d", channel: str = "all"):
    """Live aggregates from interactions — not the stub analytics_* tables."""
    try:
        return db.bot_analytics(range, channel)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/calls", response_model=list[CallResponse])
def list_calls():
    return db.list_calls()


@app.get("/leads", response_model=list[LeadResponse])
def list_leads():
    return db.list_leads()


@app.get("/me", response_model=MeResponse)
def get_me():
    try:
        return db.get_current_user()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/staff", response_model=list[StaffResponse])
def list_staff():
    return db.list_staff()


@app.get("/teams", response_model=list[TeamResponse])
def list_teams():
    return db.list_teams()


@app.get("/promises", response_model=list[PromiseListResponse])
def list_promises():
    return db.list_promises()


@app.get("/payment-plans", response_model=list[PaymentPlanResponse])
def list_payment_plans():
    return db.list_payment_plans()


@app.get("/disputes", response_model=list[DisputeListResponse])
def list_disputes():
    return db.list_disputes()


@app.get("/callbacks", response_model=list[CallbackListResponse])
def list_callbacks():
    return db.list_callbacks()


@app.get("/consent", response_model=list[ConsentListResponse])
def list_consent():
    return db.list_consent()


@app.get("/handoff/active", response_model=HandoffResponse)
def get_handoff_session():
    session = db.get_handoff_session()
    if session is None:
        raise HTTPException(status_code=404, detail="No interactions seeded")
    return session


@app.post("/interactions", response_model=CallResponse)
def create_interaction(payload: InteractionCreateRequest, idempotency_key: str | None = Header(default=None)):
    return _handle_write(db.create_interaction, payload.model_dump(), idempotency_key)


@app.post("/interactions/{interaction_id}/wrap-up")
def wrap_up_interaction(interaction_id: str, payload: InteractionWrapUpRequest, idempotency_key: str | None = Header(default=None)):
    return _handle_write(db.wrap_up_interaction, interaction_id, payload.model_dump(exclude_none=True), idempotency_key)


@app.post("/promises", response_model=PromiseResponse)
def create_promise(payload: PromiseCreateRequest, idempotency_key: str | None = Header(default=None)):
    return _handle_write(db.create_promise, payload.model_dump(exclude_none=True), idempotency_key)


@app.patch("/promises/{promise_id}", response_model=PromiseResponse)
def patch_promise(promise_id: str, payload: PromisePatchRequest):
    return _handle_write(db.patch_promise, promise_id, payload.model_dump(exclude_none=True))


@app.post("/payment-plans")
def create_payment_plan(payload: PaymentPlanCreateRequest):
    return _handle_write(db.create_payment_plan, payload.model_dump())


@app.post("/disputes", response_model=DisputeResponse)
def create_dispute(payload: DisputeCreateRequest, idempotency_key: str | None = Header(default=None)):
    return _handle_write(db.create_dispute, payload.model_dump(exclude_none=True), idempotency_key)


@app.patch("/disputes/{dispute_id}", response_model=DisputeResponse)
def patch_dispute(dispute_id: str, payload: DisputePatchRequest):
    # exclude_unset (not exclude_none) so an explicit null clears the assignee.
    return _handle_write(db.patch_dispute, dispute_id, payload.model_dump(exclude_unset=True))


@app.post("/disputes/{dispute_id}/notes")
def add_dispute_note(dispute_id: str, payload: DisputeNoteCreateRequest):
    return _handle_write(db.add_dispute_note, dispute_id, payload.model_dump())


@app.post("/disputes/{dispute_id}/evidence")
def add_dispute_evidence(dispute_id: str, payload: EvidenceCreateRequest):
    return _handle_write(db.add_dispute_evidence, dispute_id, payload.model_dump(exclude_none=True))


@app.post("/callbacks")
def create_callback(payload: CallbackCreateRequest):
    return _handle_write(db.create_callback, payload.model_dump(exclude_none=True))


@app.patch("/callbacks/{callback_id}")
def patch_callback(callback_id: str, payload: CallbackPatchRequest):
    # exclude_unset (not exclude_none) so an explicit null clears the assignee.
    return _handle_write(db.patch_callback, callback_id, payload.model_dump(exclude_unset=True))


@app.post("/callbacks/{callback_id}/reminders")
def add_callback_reminder(callback_id: str, payload: ReminderCreateRequest):
    return _handle_write(db.add_callback_reminder, callback_id, payload.model_dump(exclude_none=True))


@app.post("/leads", response_model=LeadResponse)
def create_lead(payload: LeadCreateRequest):
    return _handle_write(db.create_lead, payload.model_dump(exclude_none=True))


@app.patch("/leads/{lead_id}", response_model=LeadResponse)
def patch_lead(lead_id: str, payload: LeadPatchRequest):
    return _handle_write(db.patch_lead, lead_id, payload.model_dump(exclude_none=True))


@app.post("/leads/{lead_id}/followups")
def add_lead_followup(lead_id: str, payload: ReminderCreateRequest):
    return _handle_write(db.add_lead_followup, lead_id, payload.model_dump(exclude_none=True))


@app.patch("/followups/{followup_id}")
def patch_followup(followup_id: str, payload: FollowupPatchRequest):
    return _handle_write(db.patch_followup, followup_id, payload.model_dump(exclude_none=True))


@app.post("/document-requests", response_model=DocumentRequestResponse)
def create_document_request(payload: DocumentRequestCreateRequest):
    return _handle_write(db.create_document_request, payload.model_dump(exclude_none=True))


@app.get("/document-requests", response_model=list[DocumentListResponse])
def list_document_requests():
    return db.list_documents()


@app.patch("/document-requests/{document_id}", response_model=DocumentRequestResponse)
def patch_document_request(document_id: str, payload: DocumentPatchRequest):
    # exclude_unset (not exclude_none) so explicit nulls clear assignee / failedReason.
    return _handle_write(db.patch_document_request, document_id, payload.model_dump(exclude_unset=True))


@app.post("/document-requests/{document_id}/delivery-attempts")
def add_document_delivery_attempt(document_id: str, payload: dict):
    return _handle_write(db.add_document_delivery_attempt, document_id, payload)


@app.post("/customers/{customer_id}/notes", response_model=CustomerResponse)
def add_customer_note(customer_id: str, payload: CustomerNoteCreateRequest):
    return _handle_write(db.add_customer_note, customer_id, payload.model_dump())


@app.patch("/consent/{customer_id}", response_model=CustomerResponse)
def patch_consent(customer_id: str, payload: ConsentPatchRequest):
    # exclude_unset (not exclude_none) so an explicit null can clear/renew fields.
    return _handle_write(db.patch_consent, customer_id, payload.model_dump(exclude_unset=True))


@app.post("/consent/{customer_id}/opt-out", response_model=CustomerResponse)
def opt_out(customer_id: str, payload: OptOutCreateRequest):
    return _handle_write(db.opt_out, customer_id, payload.model_dump(exclude_unset=True))


@app.get("/violations", response_model=list[ViolationListResponse])
def list_violations():
    return db.list_violations()


@app.patch("/violations/{violation_id}", response_model=ViolationListResponse)
def patch_violation(violation_id: str, payload: ViolationPatchRequest):
    # exclude_unset (not exclude_none) so explicit null clears assignee.
    return _handle_write(db.patch_violation, violation_id, payload.model_dump(exclude_unset=True))


@app.post("/violations/{violation_id}/notes")
def add_violation_note(violation_id: str, payload: ViolationNoteCreateRequest):
    return _handle_write(db.add_violation_note, violation_id, payload.model_dump())


@app.post("/scorecards")
def create_scorecard(payload: ScorecardCreateRequest):
    return _handle_write(db.create_scorecard, payload.model_dump(exclude_none=True))


@app.patch("/scorecards/{scorecard_id}")
def patch_scorecard(scorecard_id: str, payload: ScorecardPatchRequest):
    return _handle_write(db.patch_scorecard, scorecard_id, payload.model_dump(exclude_none=True))
