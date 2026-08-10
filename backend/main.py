"""Collections Agent — CRM backend API.

Run:  .venv/Scripts/python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
Serves read/query endpoints from the normalized Postgres data layer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import Depends, Header, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import BaseHTTPMiddleware

import actor_context
import azure_openai
import circuit_breaker
import db
import flow_graph
import kb_rate_limit
import kb_retrieve
import ops_screens
import sandbox_runtime
import storage
import whatsapp
from schemas import (
    BillingOverviewResponse,
    BillingBudgetRuleResponse,
    BotAnalyticsResponse,
    OfferHealthResponse,
    TurnTraceResponse,
    InteractionCostResponse,
    FlowGraph,
    FlowToolResponse,
    FlowValidation,
    BotDeploymentResponse,
    BudgetRuleUpsertRequest,
    CallResponse,
    CallbackCreateRequest,
    CallbackListResponse,
    CallbackPatchRequest,
    CannedResponseItem,
    ConsentListResponse,
    ConsentPatchRequest,
    ConversationListResponse,
    ConversationMessageCreateRequest,
    ConversationSuggestionsRefreshRequest,
    ConversationSuggestionsRefreshResponse,
    CustomerNoteCreateRequest,
    CustomerInsightsResponse,
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
    FloorSnapshotResponse,
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
    PersonaPresetResponse,
    ProductResponse,
    PromptVersionCreateRequest,
    PromptVersionPatchRequest,
    PromptVersionPublishRequest,
    PromptVersionResponse,
    PromiseCreateRequest,
    PromiseListResponse,
    PromisePatchRequest,
    PromiseResponse,
    ProviderEnabledPatchRequest,
    ReminderCreateRequest,
    RedactionRecordListResponse,
    RedactionRuleResponse,
    RedactionRecordPatchRequest,
    RedactionRulePatchRequest,
    RedactionAudioMuteRequest,
    PiiFindingPatchRequest,
    PiiFindingPatchResponse,
    ExportJobResponse,
    ExportJobCreateRequest,
    ExportJobPatchRequest,
    RoutingRuleExecutionResponse,
    RoutingRuleListResponse,
    RoutingRuleCreateRequest,
    RoutingRulePatchRequest,
    RoutingReorderRequest,
    RoutingAuditEntryResponse,
    RubricResponse,
    CoachingActionResponse,
    CoachingActionCreateRequest,
    CoachingActionPatchRequest,
    CalibrationSessionResponse,
    CalibrationSessionPatchRequest,
    SandboxRunCreateRequest,
    SandboxRunDetailResponse,
    SandboxRunResponse,
    SandboxScenarioResponse,
    SandboxTurnCreateRequest,
    SandboxTurnResponse,
    SupervisorActionRequest,
    TtsPreviewRequest,
    SttTranscribeResponse,
    PromptLintRequest,
    PromptLintResponse,
    PromptTokenEstimateRequest,
    PromptTokenEstimateResponse,
    ScorecardCreateRequest,
    ScorecardListResponse,
    ScorecardPatchRequest,
    MeResponse,
    PresencePatchRequest,
    PresenceResponse,
    StaffResponse,
    TeamResponse,
    TtsVoiceResponse,
    TtsCatalogListResponse,
    TtsCatalogVoiceItem,
    TtsPriceTierResponse,
    TtsSyncRunResponse,
    TtsVoiceWarning,
    ViolationListResponse,
    ViolationNoteCreateRequest,
    ViolationPatchRequest,
    VoiceSandboxStartRequest,
    VoiceSandboxTuneRequest,
    WebhookEndpointPatchRequest,
    WebhookEndpointUpsertRequest,
    WorkItemResponse,
    WorkspaceSummaryResponse,
    KbChunkResponse,
    KbDeleteDocumentResponse,
    KbDocumentPatchRequest,
    KbDocumentResponse,
    KbFaqCreateRequest,
    KbFaqPatchRequest,
    KbFaqResponse,
    KbGapLinkRequest,
    KbGapResponse,
    KbIndexJobResponse,
    KbIngestSourceDbResponse,
    KbPurgeRequest,
    KbPurgeResponse,
    KbReindexResponse,
    KbRetrieveRequest,
    KbRetrieveResponse,
    KbSnapshotCreateRequest,
    KbSnapshotResponse,
    KbStatsResponse,
    KbUploadResponse,
)


logger = logging.getLogger(__name__)

# APP_ENV=production (or prod) enables fail-closed auth + disabled OpenAPI docs.
_APP_ENV = (os.getenv("APP_ENV") or "dev").strip().lower()
_IS_PROD = _APP_ENV in {"prod", "production"}

# Cap multipart uploads (STT / KB) — reject before buffering unbounded bytes.
_MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES") or str(25 * 1024 * 1024))


async def _read_upload_capped(file: UploadFile, *, max_bytes: int | None = None) -> bytes:
    limit = max_bytes if max_bytes is not None else _MAX_UPLOAD_BYTES
    buf = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(status_code=413, detail="upload_too_large")
    return bytes(buf)

try:
    from voice.host import embedded_host_enabled as _embedded_host_enabled

    _EMBEDDED_VOICE_HOST = _embedded_host_enabled()
except Exception:  # pragma: no cover - optional voice extras
    _EMBEDDED_VOICE_HOST = False

# Public paths that skip API-key auth (webhooks use their own HMAC).
# Docs/OpenAPI are NOT exempt — when API_KEY is set they require the key;
# in production the docs URLs themselves are disabled below.
_AUTH_EXEMPT_PREFIXES = (
    "/health",
    "/ready",
    "/webhooks/whatsapp",
    "/webhook/whatsapp",
    # No trailing slash — matching uses `path == p or path.startswith(p + "/")`.
    # ONLY the inbound webhook is exempt, and it enforces X-Twilio-Signature
    # itself. Exempting all of /twilio left POST /twilio/voice/outbound open to
    # the internet — anyone could dial arbitrary PSTN numbers on our account —
    # and leaked the phone number / media-stream URL via /twilio/voice/status.
    "/twilio/voice/incoming",
    # Signature-validated Twilio callbacks (not control-plane /outbound|/status).
    "/twilio/voice/fallback",
    "/twilio/voice/stream-status",
    "/twilio/voice/call-status",
    "/ws",
    # SmallWebRTC signalling. The WebRTC client cannot attach our API-key
    # header to its offer POST, and the standalone runner it replaces has no
    # auth at all — so this is parity, not a downgrade. Only present when the
    # embedded host is actually serving these routes.
    *(("/api/offer", "/voice-rtc") if _EMBEDDED_VOICE_HOST else ()),
)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """API-key gate + request-scoped actor binding.

    CORS preflight (OPTIONS) must never be gated — browsers do not send
    custom headers on preflight, and this middleware must run *inside*
    CORSMiddleware so even 401 responses carry CORS headers.

    Actor resolution (see ``actor_context``):
      - ``API_KEY_MAP`` JSON maps each secret → ``users.id``
      - shared ``API_KEY`` → ``ACTOR_USER_ID``, or ``X-Actor-User-Id`` when
        ``ALLOW_ACTOR_HEADER`` is on (default: non-prod only)
    """

    async def dispatch(self, request: Request, call_next: Callable):
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if any(path == p or path.startswith(p + "/") for p in _AUTH_EXEMPT_PREFIXES):
            return await call_next(request)

        provided = (request.headers.get("x-api-key") or "").strip()
        if not provided:
            auth = (request.headers.get("authorization") or "").strip()
            if auth.lower().startswith("bearer "):
                provided = auth[7:].strip()

        actor_header = (request.headers.get("x-actor-user-id") or "").strip() or None
        key_map = actor_context.parse_api_key_map()
        single = (os.getenv("API_KEY") or "").strip()
        auth_required = bool(single or key_map)

        if auth_required and not provided:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)

        ok, actor_id, err = actor_context.resolve_authenticated_actor(
            provided_key=provided if auth_required else (provided or ""),
            actor_header=actor_header,
        )
        if not ok or not actor_id:
            # actor_not_found is a client config error; wrong/missing key is 401.
            status = 400 if err == "actor_not_found" else 401
            # Serialised, not interpolated: hand-building the JSON meant any
            # future error string containing a quote or backslash would emit a
            # malformed body from the auth middleware.
            return JSONResponse({"detail": err or "unauthorized"}, status_code=status)

        request.state.actor_user_id = actor_id
        token = actor_context.set_actor_user_id(actor_id)
        try:
            return await call_next(request)
        finally:
            actor_context.reset_actor_user_id(token)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Propagate/assign X-Request-Id for log correlation."""

    # Client-supplied ids are echoed into a response header and into every log
    # line for the request, so they are constrained to a safe alphabet and a
    # sane length rather than reflected verbatim.
    _SAFE_REQUEST_ID = re.compile(r"[^A-Za-z0-9-]")

    async def dispatch(self, request: Request, call_next: Callable):
        import uuid

        raw = (request.headers.get("x-request-id") or "").strip()
        rid = self._SAFE_REQUEST_ID.sub("", raw)[:64] or uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response


# Controls whose enforcement is still deferred (see DATA_MODEL.md, "Scope of
# this build pass"): RLS tenant isolation, PII column encryption, and
# append-only audit enforcement. Until those land, this build must not be run
# against real customer data — so a non-local deployment fails closed unless an
# operator has explicitly acknowledged the gap.
_DEFERRED_HARDENING_CONTROLS = (
    "RLS tenant isolation",
    "PII column encryption / Vault secret refs",
    "append-only enforcement on audit tables",
)


def _assert_hardening_gate() -> None:
    """Refuse to boot outside a trusted local environment while controls are off."""
    if not _IS_PROD:
        return
    ack = (os.getenv("ALLOW_UNHARDENED_PRODUCTION") or "").strip().lower()
    if ack in {"1", "true", "yes", "on"}:
        logger.error(
            "Booting with APP_ENV=production while deferred controls are still "
            "inactive (%s) — ALLOW_UNHARDENED_PRODUCTION is set. This deployment "
            "must not receive real customer data.",
            ", ".join(_DEFERRED_HARDENING_CONTROLS),
        )
        return
    raise RuntimeError(
        "APP_ENV=production but the data layer's deferred controls are not active: "
        + "; ".join(_DEFERRED_HARDENING_CONTROLS)
        + ". Run this build locally, or set ALLOW_UNHARDENED_PRODUCTION=1 to "
        "explicitly accept the risk."
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _assert_hardening_gate()
    # Mirror FE mock fail-closed: prod without credentials must not boot.
    has_auth = bool((os.getenv("API_KEY") or "").strip() or actor_context.parse_api_key_map())
    if _IS_PROD and not has_auth:
        raise RuntimeError("API_KEY or API_KEY_MAP must be set when APP_ENV=production")
    if not has_auth:
        logger.warning(
            "API_KEY / API_KEY_MAP unset — CRM routes are public. "
            "Set credentials (required when APP_ENV=production)."
        )

    try:
        await asyncio.to_thread(db.init_and_seed)
        await asyncio.to_thread(storage.ensure_bucket)
        try:
            await asyncio.to_thread(actor_context.validate_configured_actors)
        except RuntimeError:
            if _IS_PROD:
                raise
            logger.warning("actor identity config invalid (non-prod): continuing", exc_info=True)
        try:
            import usage_meter

            await asyncio.to_thread(usage_meter.sync_price_book)
        except Exception:
            logger.warning("usage_meter.sync_price_book failed", exc_info=True)
        try:
            from tts_catalog_sync import ensure_catalog_seeded

            await asyncio.to_thread(ensure_catalog_seeded, db.engine)
        except Exception:
            logger.warning("tts catalog boot seed failed", exc_info=True)
        yield
    finally:
        # Before the DB engine goes away: live calls write CRM rows on teardown.
        try:
            from voice.host import shutdown as voice_host_shutdown

            await voice_host_shutdown()
        except Exception:
            logger.warning("voice host shutdown failed", exc_info=True)
        # Drain buffered usage before the engine goes away, otherwise the last
        # few seconds of billable calls are lost on every deploy.
        try:
            import usage_meter

            # shutdown(), not flush(): stop the background flusher first so the
            # final drain cannot race an in-flight batch.
            await asyncio.to_thread(usage_meter.shutdown)
        except Exception:
            logger.warning("usage_meter.shutdown on app shutdown failed", exc_info=True)
        db.dispose_engine()


app = FastAPI(
    title="Collections Agent API",
    version="0.1.0",
    lifespan=lifespan,
    # Prod: do not publish the OpenAPI schema unauthenticated.
    docs_url=None if _IS_PROD else "/docs",
    redoc_url=None if _IS_PROD else "/redoc",
    openapi_url=None if _IS_PROD else "/openapi.json",
)

# Starlette inserts each add_middleware at index 0 → last added is OUTERMOST.
# Desired order (outer → inner): CORS → RequestId → ApiKey → GZip → route
# so (1) preflight/401s always get CORS headers, (2) RequestId wraps ApiKey so
# the 401/400 responses auth generates still carry X-Request-Id (previously
# rejected requests were unattributable in the logs), and (3) ApiKey sees
# OPTIONS only after CORS has claimed it — still pass OPTIONS through ApiKey.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(ApiKeyMiddleware)
app.add_middleware(RequestIdMiddleware)

_cors_origins = [o.strip() for o in (os.getenv("CORS_ORIGINS") or "").split(",") if o.strip()]
if _cors_origins:
    # Prod: explicit allowlist + credentials (required for cookie auth).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    # Dev: any localhost port (Vite may fall back to 8081…). Credentials
    # enabled so cookie auth does not silently fail when added.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# VOICE_EMBEDDED_HOST=true: serve SmallWebRTC signalling here instead of
# requiring a second `python -m voice.bot` process on :7860 (Phase E1).
if _EMBEDDED_VOICE_HOST:
    from voice.host import register_routes as _register_voice_routes

    _register_voice_routes(app)


# Azure concurrency saturation / circuit open → shed load fast.
@app.exception_handler(azure_openai.AzureBusyError)
async def _azure_busy_handler(_request: Request, exc: azure_openai.AzureBusyError):
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc) or "azure_concurrency_saturated"},
    )


@app.exception_handler(circuit_breaker.CircuitOpenError)
async def _circuit_open_handler(_request: Request, exc: circuit_breaker.CircuitOpenError):
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc) or "circuit_open"},
    )


def _handle_write(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        # A bad foreign key (unknown productId / teamId / ownerUserId) is a
        # client error, not a server fault. It used to escape as an unhandled
        # 500 with a psycopg traceback in the response body.
        logger.warning("write rejected by a database constraint: %s", exc.orig)
        raise HTTPException(status_code=409, detail="constraint_violation") from exc


def require_admin() -> None:
    """Fail closed when API-key auth is on and the actor is not Admin.

    Local/dev with auth unset stays open (same as the previous inline check).
    """
    auth_required = bool(
        (os.getenv("API_KEY") or "").strip() or actor_context.parse_api_key_map()
    )
    if auth_required and not db.actor_is_admin():
        raise HTTPException(status_code=403, detail="admin_required")


@app.get("/health")
def health():
    """Process liveness — no dependency checks."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Readiness: DB ping + pool headroom (+ optional MinIO ping).

    Exhausted pool or hard DB failure → 503 so LBs shed load.
    MinIO unconfigured is OK (KB upload routes fail separately).
    """
    result = db.readiness()
    minio = storage.ping()
    result = {**result, "minio": minio, "circuits": circuit_breaker.snapshots()}
    # Only fail readiness on MinIO when it is configured but unreachable.
    if minio.get("configured") and not minio.get("ok"):
        result = {
            **result,
            "ok": False,
            "detail": result.get("detail") or f"minio:{minio.get('detail')}",
        }
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result)
    return result


@app.get("/customers", response_model=list[CustomerResponse])
def list_customers():
    return db.list_customers()


@app.get("/customers/{customer_id}", response_model=CustomerResponse)
def get_customer(customer_id: str):
    customer = db.get_customer(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@app.get("/customers/{customer_id}/insights", response_model=CustomerInsightsResponse)
def get_customer_insights(customer_id: str):
    insights = db.get_customer_insights(customer_id)
    if insights is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return insights


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


@app.get("/offers/health", response_model=OfferHealthResponse)
def get_offer_health(
    window: str = Query("30d", description="24h | 7d | 30d | 90d"),
    includeSimulated: bool = Query(
        False,
        description="Include synthetic rows from scripts/simulate_offer_decisions.py",
    ),
):
    """Offer-engine observability — coverage, funnel, latency, guardrails.

    Synthetic decisions are excluded unless asked for, so nobody makes a call
    on a number that came out of the simulator.
    """
    from agent_core.reco import observability

    return observability.offer_health(window, include_simulated=includeSimulated)


@app.get("/billing", response_model=BillingOverviewResponse)
def get_billing(
    period: str = Query("mtd"),
    tenantId: str = Query("all"),
    env: str = Query("production"),
):
    """Billing & Usage Analytics — filtered spend, budgets, invoices."""
    try:
        return db.billing_overview(period, tenantId, env)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/interactions/{interaction_id}/export")
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
                )
            },
        )
    return Response(
        content=json.dumps(bundle, indent=2, default=str),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="call-{interaction_id}.json"'
        },
    )


@app.get("/billing/export.csv")
def export_billing_csv(
    period: str = Query("mtd"),
    tenantId: str = Query("all"),
    env: str = Query("production"),
):
    try:
        csv_body = db.billing_export_csv(period, tenantId, env)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="billing-usage.csv"'},
    )


@app.post("/billing/budgets/{budget_id}/rules", response_model=BillingBudgetRuleResponse)
def create_budget_rule(budget_id: str, payload: BudgetRuleUpsertRequest):
    try:
        return db.upsert_budget_rule(budget_id, payload.model_dump())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/billing/budgets/{budget_id}/rules/{rule_id}", response_model=BillingBudgetRuleResponse)
def patch_budget_rule(budget_id: str, rule_id: str, payload: BudgetRuleUpsertRequest):
    try:
        return db.upsert_budget_rule(budget_id, payload.model_dump(), rule_id=rule_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/billing/budgets/{budget_id}/rules/{rule_id}", status_code=204)
def delete_budget_rule(budget_id: str, rule_id: str):
    try:
        db.delete_budget_rule(budget_id, rule_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@app.get("/calls", response_model=list[CallResponse])
def list_calls():
    return db.list_calls()


@app.get("/interactions/{interaction_id}/cost", response_model=InteractionCostResponse)
def get_interaction_cost(interaction_id: str):
    """What this call cost, split by service and model.

    Assembled from usage_events attributed to the interaction. ``attributed`` is
    False when the call carries no events — every call that predates pipeline
    metering is in that state, and it must not be shown as a genuine ₹0.00.
    """
    return db.interaction_cost(interaction_id)


@app.get("/interactions/{interaction_id}/trace", response_model=list[TurnTraceResponse])
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


@app.get("/products", response_model=list[ProductResponse])
def list_products(includeInactive: bool = Query(False)):
    """Offer catalog — the single source of truth for product ids.

    Both the UI pickers and the recommender read this. Anything that hardcodes
    a product list drifts from what check_product_eligibility will accept.
    """
    return db.list_products(include_inactive=includeInactive)


@app.get("/leads", response_model=list[LeadResponse])
def list_leads():
    return db.list_leads()


@app.get("/me", response_model=MeResponse)
def get_me():
    try:
        return db.get_current_user()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/me/presence", response_model=PresenceResponse)
def get_me_presence():
    """Agent availability for My Workspace — reads agent_presence for ACTOR_USER_ID."""
    return db.get_agent_presence()


@app.patch("/me/presence", response_model=PresenceResponse)
def patch_me_presence(payload: PresencePatchRequest):
    try:
        return db.patch_agent_presence(payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/work-items", response_model=list[WorkItemResponse])
def list_work_items(assignee: str | None = Query("me")):
    """Assigned queue from the work_items view. Default assignee=me is viewer-relative."""
    return db.list_work_items(assignee=assignee)


@app.get("/workspace/summary", response_model=WorkspaceSummaryResponse)
def get_workspace_summary(assignee: str | None = Query("me")):
    """Rolling-window StatsStrip + RightRail (next callback / SLA / outside-window)."""
    return db.workspace_summary(assignee=assignee)


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


@app.get("/floor", response_model=FloorSnapshotResponse)
def get_floor():
    return ops_screens.get_floor_snapshot()


@app.post("/supervisor-actions")
def post_supervisor_action(payload: SupervisorActionRequest):
    try:
        return ops_screens.create_supervisor_action(payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/floor/alerts/{alert_id}/ack")
def ack_floor_alert(alert_id: str):
    try:
        return ops_screens.ack_floor_alert(alert_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/event-types")
def list_event_types():
    return ops_screens.list_event_types()


@app.get("/webhook-endpoints")
def list_webhook_endpoints():
    return ops_screens.list_webhook_endpoints()


@app.post("/webhook-endpoints")
def create_webhook_endpoint(payload: WebhookEndpointUpsertRequest):
    try:
        return ops_screens.create_webhook_endpoint(payload.model_dump(mode="json"))
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/webhook-endpoints/{endpoint_id}")
def patch_webhook_endpoint(endpoint_id: str, payload: WebhookEndpointPatchRequest):
    try:
        return ops_screens.patch_webhook_endpoint(
            endpoint_id, payload.model_dump(mode="json", exclude_unset=True)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/webhook-endpoints/{endpoint_id}")
def delete_webhook_endpoint(endpoint_id: str):
    try:
        ops_screens.delete_webhook_endpoint(endpoint_id)
        return {"ok": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/webhook-endpoints/{endpoint_id}/rotate-secret")
def rotate_webhook_secret(endpoint_id: str):
    try:
        return ops_screens.rotate_webhook_secret(endpoint_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/webhook-endpoints/{endpoint_id}/test")
def test_webhook_endpoint(endpoint_id: str, event: str | None = Query(default=None)):
    try:
        return ops_screens.test_fire_webhook(endpoint_id, event)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/webhook-deliveries")
def list_webhook_deliveries(endpointId: str | None = Query(default=None)):
    return ops_screens.list_webhook_deliveries(endpointId)


@app.post("/webhook-deliveries/{delivery_id}/retry")
def retry_webhook_delivery(delivery_id: str):
    try:
        return ops_screens.retry_webhook_delivery(delivery_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/providers")
def list_providers(env: str = Query(default="sandbox")):
    return ops_screens.list_providers(env)


@app.patch("/providers/{provider_id}/configs/{environment}")
def patch_provider_config(
    provider_id: str, environment: str, payload: ProviderEnabledPatchRequest
):
    try:
        return ops_screens.patch_provider_enabled(
            provider_id, environment, payload.enabled
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/providers/{provider_id}/test")
def test_provider(provider_id: str, env: str = Query(default="sandbox")):
    try:
        return ops_screens.test_provider(provider_id, env)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/providers/{provider_id}/test-logs")
def list_provider_test_logs(provider_id: str):
    return ops_screens.list_provider_test_logs(provider_id)


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
def create_lead(payload: LeadCreateRequest, idempotency_key: str | None = Header(default=None)):
    body = payload.model_dump(exclude_none=True)
    allow_duplicate = bool(body.pop("allowDuplicate", False))
    return _handle_write(
        db.create_lead, body, idempotency_key, allow_duplicate=allow_duplicate
    )


@app.patch("/leads/{lead_id}", response_model=LeadResponse)
def patch_lead(lead_id: str, payload: LeadPatchRequest):
    # exclude_unset, not exclude_none: the state machine distinguishes "field
    # not sent" from "field explicitly cleared". exclude_none collapsed both
    # into absent, so lossReason could be set but never removed.
    return _handle_write(db.patch_lead, lead_id, payload.model_dump(exclude_unset=True))


@app.post("/leads/{lead_id}/revalidate")
def revalidate_lead(lead_id: str, channel: str | None = Query(default=None)):
    """Re-check a lead's eligibility against today's consent and account facts."""
    return _handle_write(db.revalidate_lead_eligibility, lead_id, channel)


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


@app.get("/rubric", response_model=RubricResponse)
def get_rubric():
    """Active Collections Interaction Rubric (screen defaultRubric shape)."""
    try:
        return db.get_rubric()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/scorecards", response_model=list[ScorecardListResponse])
def list_scorecards():
    return db.list_scorecards()


@app.post("/scorecards", response_model=ScorecardListResponse)
def create_scorecard(payload: ScorecardCreateRequest):
    return _handle_write(db.create_scorecard, payload.model_dump(exclude_unset=True))


@app.patch("/scorecards/{scorecard_id}", response_model=ScorecardListResponse)
def patch_scorecard(scorecard_id: str, payload: ScorecardPatchRequest):
    # exclude_unset (not exclude_none) so present keys are intentional.
    return _handle_write(db.patch_scorecard, scorecard_id, payload.model_dump(exclude_unset=True))


@app.get("/coaching-actions", response_model=list[CoachingActionResponse])
def list_coaching_actions():
    return db.list_coaching_actions()


@app.post("/coaching-actions", response_model=CoachingActionResponse)
def create_coaching_action(payload: CoachingActionCreateRequest):
    return _handle_write(db.create_coaching_action, payload.model_dump(exclude_unset=True))


@app.patch("/coaching-actions/{action_id}", response_model=CoachingActionResponse)
def patch_coaching_action(action_id: str, payload: CoachingActionPatchRequest):
    return _handle_write(
        db.patch_coaching_action, action_id, payload.model_dump(exclude_unset=True)
    )


@app.get("/calibration-sessions", response_model=list[CalibrationSessionResponse])
def list_calibration_sessions():
    return db.list_calibration_sessions()


@app.patch(
    "/calibration-sessions/{session_id}",
    response_model=CalibrationSessionResponse,
)
def patch_calibration_session(session_id: str, payload: CalibrationSessionPatchRequest):
    return _handle_write(
        db.patch_calibration_session, session_id, payload.model_dump(exclude_unset=True)
    )


@app.get("/redaction-records", response_model=list[RedactionRecordListResponse])
def list_redaction_records():
    """Redaction Hub queue — nested findings + audio segments. Masked PII only for non-Admin."""
    return db.list_redaction_records()


@app.get("/redaction-records/{redaction_id}", response_model=RedactionRecordListResponse)
def get_redaction_record(redaction_id: str):
    try:
        return db.get_redaction_record(redaction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/redaction-rules", response_model=list[RedactionRuleResponse])
def list_redaction_rules():
    return db.list_redaction_rules()


@app.patch("/redaction-records/{redaction_id}", response_model=RedactionRecordListResponse)
def patch_redaction_record(redaction_id: str, payload: RedactionRecordPatchRequest):
    return _handle_write(
        db.patch_redaction_record, redaction_id, payload.model_dump(exclude_unset=True)
    )


@app.patch("/pii-findings/{finding_id}", response_model=PiiFindingPatchResponse)
def patch_pii_finding(finding_id: str, payload: PiiFindingPatchRequest):
    return _handle_write(
        db.patch_pii_finding, finding_id, payload.model_dump(exclude_unset=True)
    )


@app.patch("/redaction-records/{redaction_id}/audio-mute")
def patch_redaction_audio_mute(redaction_id: str, payload: RedactionAudioMuteRequest):
    return _handle_write(
        db.patch_audio_segment_mute,
        redaction_id,
        payload.findingId,
        payload.muted,
    )


@app.patch("/redaction-rules/{pii_type}", response_model=RedactionRuleResponse)
def patch_redaction_rule(pii_type: str, payload: RedactionRulePatchRequest):
    return _handle_write(
        db.patch_redaction_rule, pii_type, payload.model_dump(exclude_unset=True)
    )


@app.get("/export-jobs", response_model=list[ExportJobResponse])
def list_export_jobs():
    return db.list_export_jobs()


@app.post("/export-jobs", response_model=ExportJobResponse)
def create_export_job(payload: ExportJobCreateRequest):
    return _handle_write(db.create_export_job, payload.model_dump(exclude_unset=True))


@app.patch("/export-jobs/{job_id}", response_model=ExportJobResponse)
def patch_export_job(job_id: str, payload: ExportJobPatchRequest):
    return _handle_write(db.patch_export_job, job_id, payload.model_dump(exclude_unset=True))


@app.get("/routing-rules", response_model=list[RoutingRuleListResponse])
def list_routing_rules():
    """Priority-ordered routing library with matched-execution aggregates."""
    return db.list_routing_rules()


@app.get(
    "/routing-rules/{rule_id}/executions",
    response_model=list[RoutingRuleExecutionResponse],
)
def list_routing_rule_executions(rule_id: str):
    try:
        return db.list_routing_rule_executions(rule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/routing-rules", response_model=RoutingRuleListResponse)
def create_routing_rule(payload: RoutingRuleCreateRequest):
    return _handle_write(db.create_routing_rule, payload.model_dump(exclude_unset=True))


@app.patch("/routing-rules/{rule_id}", response_model=RoutingRuleListResponse)
def patch_routing_rule(rule_id: str, payload: RoutingRulePatchRequest):
    return _handle_write(
        db.patch_routing_rule, rule_id, payload.model_dump(exclude_unset=True)
    )


@app.post("/routing-rules/reorder", response_model=list[RoutingRuleListResponse])
def reorder_routing_rules(payload: RoutingReorderRequest):
    return _handle_write(db.reorder_routing_rules, payload.orderedIds)


@app.delete("/routing-rules/{rule_id}")
def delete_routing_rule(rule_id: str):
    return _handle_write(db.delete_routing_rule, rule_id)


@app.get("/routing-audit", response_model=list[RoutingAuditEntryResponse])
def list_routing_audit():
    return db.list_routing_audit()


@app.get("/prompt-versions", response_model=list[PromptVersionResponse])
def list_prompt_versions():
    """Prompt Studio version history (newest first)."""
    return db.list_prompt_versions()


@app.get("/prompt-versions/published", response_model=PromptVersionResponse)
def get_published_prompt_version():
    """Editor live badge — single published row (kept in sync with active prod deployment)."""
    row = db.get_published_prompt_version()
    if row is None:
        raise HTTPException(status_code=404, detail="published_prompt_not_found")
    return row


@app.get("/prompt-versions/{version_id}", response_model=PromptVersionResponse)
def get_prompt_version(version_id: str):
    row = db.get_prompt_version(version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="prompt_version_not_found")
    return row


@app.get("/flow/tools", response_model=list[FlowToolResponse])
def list_flow_tools():
    """Tools an authored flow node may call.

    Introspected from the live registry rather than listed here, so the editor
    cannot drift from what the runtime will actually accept.
    """
    return flow_graph.tool_catalog()


@app.get("/flow/reserved-keys", response_model=dict[str, str])
def list_flow_reserved_keys():
    """Node keys the built-in tools transition to by name.

    A graph is free to ignore them; using one wires up that built-in hop. The
    editor surfaces these so the choice is visible rather than a trap.
    """
    return flow_graph.RESERVED_NODE_KEYS


@app.post("/flow/validate", response_model=FlowValidation)
def validate_flow(graph: FlowGraph):
    """Structural check. Errors block publish; warnings are advisory.

    The editor calls this as you draw, so a graph is never published with a
    dangling edge or two nodes sharing a transition key.
    """
    return flow_graph.validate_graph(
        graph, known_tools=[t["key"] for t in flow_graph.tool_catalog()]
    )


@app.get("/persona-presets", response_model=list[PersonaPresetResponse])
def list_persona_presets():
    return db.list_persona_presets()


@app.get("/tts-voices", response_model=list[TtsVoiceResponse])
def list_tts_voices():
    return db.list_tts_voices()


@app.get("/tts-voices/catalog", response_model=TtsCatalogListResponse)
def list_tts_voice_catalog(
    q: str | None = Query(default=None),
    locale: str | None = Query(default=None),
    gender: str | None = Query(default=None),
    status: str | None = Query(default="GA"),
    price_tier: str | None = Query(default=None),
    include_premium: bool = Query(default=False),
    include_removed: bool = Query(default=False),
    limit: int = Query(default=60, ge=1, le=200),
    cursor: str | None = Query(default=None),
):
    """Synced Azure TTS catalog — primary source for Voice picker."""
    return db.list_tts_voice_catalog(
        q=q,
        locale=locale,
        gender=gender,
        status=status,
        price_tier=price_tier,
        include_premium=include_premium,
        include_removed=include_removed,
        limit=limit,
        cursor=cursor,
    )


@app.get("/tts-voices/catalog/sync-runs", response_model=list[TtsSyncRunResponse])
def list_tts_sync_runs(limit: int = Query(default=20, ge=1, le=100)):
    """Recent catalog sync runs for the Voice Studio freshness strip."""
    return db.list_tts_sync_runs(limit=limit)


@app.get("/tts-voices/catalog/{short_name}", response_model=TtsCatalogVoiceItem)
def get_tts_voice_catalog_entry(short_name: str):
    row = db.get_tts_voice_catalog_entry(short_name)
    if not row:
        raise HTTPException(status_code=404, detail="voice_not_found")
    return row


@app.get("/tts-voices/pricing", response_model=list[TtsPriceTierResponse])
def list_tts_pricing():
    return db.list_tts_price_tiers()


@app.get("/tts-voices/catalog-warning", response_model=TtsVoiceWarning | None)
def tts_voice_warning(shortName: str = Query(...)):
    return db.get_tts_voice_warning(shortName)


@app.post("/tts-voices/catalog/sync", response_model=TtsSyncRunResponse)
def sync_tts_voice_catalog(_admin: None = Depends(require_admin)):
    """Admin refresh — pull Azure voices/list (JSON fallback).

    When API-key auth is configured, require Admin / perm-admin-write so
    arbitrary keys cannot hammer Azure. Local/dev with auth off stays open.
    """
    from tts_catalog_sync import run_sync

    return run_sync(db.engine, source="admin")


@app.post("/tts/preview")
def tts_preview(payload: TtsPreviewRequest):
    """Azure Speech TTS preview — returns audio/mpeg (cached by synthesis params)."""
    import azure_speech

    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text_required")
    if len(text) > 500:
        text = text[:500].rstrip() + "…"

    short = (payload.shortName or payload.azureVoiceName or "").strip()
    voice_id = (payload.voiceId or "").strip()
    azure_name: str | None = short or None
    if not azure_name and voice_id:
        if azure_speech.looks_like_azure_short_name(voice_id):
            azure_name = voice_id
        else:
            for v in db.list_tts_voices():
                if v["id"] == voice_id:
                    azure_name = v.get("azureVoiceName")
                    break
    try:
        resolved = azure_speech.resolve_azure_voice_name(
            voice_id or short or None, db_azure_name=azure_name
        )
        # Stale / removed voice → fall back for preview without failing the UI.
        warning = db.get_tts_voice_warning(resolved)
        if warning and warning.get("fallbackVoice"):
            resolved = warning["fallbackVoice"]
        result = azure_speech.synthesize(
            text,
            voice_name=resolved,
            speed=payload.speed,
            pitch=payload.pitch,
            warmth=payload.warmth,
            pause_ms=payload.pauseMs,
        )
    except azure_speech.AzureSpeechConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    headers = {
        "X-TTS-Cache": "HIT" if result["cacheHit"] else "MISS",
        "X-TTS-Voice": result["voiceName"],
        "X-TTS-Latency-Ms": str(result["latencyMs"]),
        "Cache-Control": "private, max-age=3600",
    }
    return Response(content=result["audio"], media_type=result["contentType"], headers=headers)


@app.get("/bot-deployments", response_model=list[BotDeploymentResponse])
def list_bot_deployments(
    environment: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    """Runtime deployments — authoritative for what runs (Sandbox / live)."""
    return db.list_bot_deployments(environment=environment, status=status)


@app.get("/bot-deployments/active", response_model=BotDeploymentResponse)
def get_active_bot_deployment(
    environment: str = Query(default="production"),
    botId: str | None = Query(default=None),
):
    """Thin wrapper over get_active_deployment — 404 if none active."""
    row = db.get_active_deployment(bot_id=botId, environment=environment)
    if row is None:
        raise HTTPException(status_code=404, detail="active_deployment_not_found")
    return row


@app.post("/prompt-versions", response_model=PromptVersionResponse)
def create_prompt_version(payload: PromptVersionCreateRequest):
    """Create a draft — jsonb validated by nested Pydantic models."""
    return _handle_write(db.create_prompt_version, payload.model_dump())


@app.patch("/prompt-versions/{version_id}", response_model=PromptVersionResponse)
def patch_prompt_version(version_id: str, payload: PromptVersionPatchRequest):
    """Update draft only — 409 if the version is published/archived."""
    body = payload.model_dump(exclude_unset=True)
    return _handle_write(db.patch_prompt_version, version_id, body)


@app.post("/prompt-versions/{version_id}/publish", response_model=PromptVersionResponse)
def publish_prompt_version(version_id: str, payload: PromptVersionPublishRequest):
    """Publish draft + swap active prod deployment atomically.

    Optional kbSnapshotId / tuning from Sandbox Promote pin the deployment bundle.
    Concurrent publish that loses the unique published index returns 409.
    """
    return _handle_write(
        db.publish_prompt_version,
        version_id,
        payload.summary,
        kb_snapshot_id=payload.kbSnapshotId,
        tuning=payload.tuning,
    )


@app.post("/prompt-versions/lint", response_model=PromptLintResponse)
def lint_prompt_version(payload: PromptLintRequest):
    """Deterministic prompt lint (unknown vars, disclosure, prohibited words).

    Optional includeLlm=true runs an Azure checklist pass — never auto-edits.
    """
    import prompt_lint

    findings = prompt_lint.lint_prompt(
        payload.prompt,
        payload.guardrails.model_dump(),
        include_llm=payload.includeLlm,
    )
    return {"findings": findings}


@app.post("/prompt-versions/estimate-tokens", response_model=PromptTokenEstimateResponse)
def estimate_prompt_tokens(payload: PromptTokenEstimateRequest):
    """Tiktoken (cl100k_base) prompt token count + input-$ estimate for Studio.

    Cost uses AZURE_OPENAI_INPUT_USD_PER_1M (default 2.50) — prompt-input only,
    not a full turn (completion / RAG context excluded).
    """
    from kb_chunking import count_tokens

    text = payload.prompt or ""
    if len(text) > 200_000:
        raise HTTPException(status_code=400, detail="prompt_too_large")
    tokens = count_tokens(text)
    try:
        usd_per_1m = float(os.getenv("AZURE_OPENAI_INPUT_USD_PER_1M") or "2.5")
    except ValueError:
        usd_per_1m = 2.5
    if usd_per_1m < 0:
        usd_per_1m = 0.0
    cost_usd = round(tokens * usd_per_1m / 1_000_000.0, 6)
    return {
        "tokens": tokens,
        "encoding": "cl100k_base",
        "usdPer1M": usd_per_1m,
        "costUsd": cost_usd,
        "source": "tiktoken",
    }


@app.post("/prompt-versions/{version_id}/restore-as-draft", response_model=PromptVersionResponse)
def restore_prompt_version_as_draft(version_id: str):
    """Copy archived/published → new draft; never overwrites live."""
    return _handle_write(db.restore_prompt_version_as_draft, version_id)


@app.post("/prompt-versions/{version_id}/discard", response_model=PromptVersionResponse)
def discard_prompt_version(version_id: str):
    """Archive a draft — editor discard path. 409 if not a draft."""
    return _handle_write(db.discard_prompt_version, version_id)


@app.post("/bot-deployments/{deployment_id}/rollback", response_model=BotDeploymentResponse)
def rollback_bot_deployment(deployment_id: str):
    """Activate prior deployment and re-publish its prompt version (invariant)."""
    return _handle_write(db.rollback_bot_deployment, deployment_id)


@app.post("/sandbox/runs", response_model=SandboxRunResponse)
def create_sandbox_run(payload: SandboxRunCreateRequest):
    """Start a sandbox session bound to a prompt version (or active deployment)."""
    body = payload.model_dump()
    if body.get("context") is None:
        body.pop("context", None)
    else:
        body["context"] = {k: v for k, v in body["context"].items() if v is not None}
    try:
        return sandbox_runtime.create_sandbox_run(body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith("kb_snapshot_not_found"):
            raise HTTPException(status_code=400, detail=msg) from exc
        raise HTTPException(status_code=409, detail=msg) from exc


@app.post("/stt/transcribe", response_model=SttTranscribeResponse)
async def stt_transcribe(
    file: UploadFile = File(...),
    language: str = Form(default="en-IN"),
):
    """Azure Speech STT — multipart audio (webm/wav/mp3). Audio is not persisted.

    File read is async; sync Azure Speech REST runs in a worker thread so this
    async route does not block the event loop.
    """
    import azure_speech

    audio = await _read_upload_capped(file)
    if not audio:
        raise HTTPException(status_code=400, detail="empty_audio")
    content_type = (file.content_type or "application/octet-stream").split(";")[0].strip()
    lang = (language or "en-IN").strip() or "en-IN"
    try:
        result = await asyncio.to_thread(
            azure_speech.transcribe,
            audio,
            content_type=content_type,
            language=lang,
        )
    except azure_speech.AzureSpeechConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result


@app.get("/sandbox/scenarios", response_model=list[SandboxScenarioResponse])
def list_sandbox_scenarios():
    """Scripted personas + customer turns for the sandbox picker."""
    return db.list_sandbox_scenarios()


@app.get("/sandbox/runs/{run_id}", response_model=SandboxRunDetailResponse)
def get_sandbox_run(run_id: str):
    """Run + persisted turns (ascending turnIndex) with grounded chunk titles."""
    try:
        return db.get_sandbox_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/sandbox/runs/{run_id}/turns", response_model=SandboxTurnResponse)
def append_sandbox_turn(run_id: str, payload: SandboxTurnCreateRequest):
    """Customer turn → KB retrieve + Azure chat → persisted bot reply."""
    body = payload.model_dump()
    if body.get("context") is None:
        body.pop("context", None)
    else:
        body["context"] = {k: v for k, v in body["context"].items() if v is not None}
    try:
        return sandbox_runtime.append_sandbox_turn(run_id, body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/sandbox/runs/{run_id}/complete")
def complete_sandbox_run(run_id: str):
    return _handle_write(sandbox_runtime.complete_sandbox_run, run_id)


@app.get("/sandbox/tuning/presets")
def list_sandbox_tuning_presets():
    from agent_core.tuning import list_presets

    return list_presets()


@app.get("/voice/status")
def get_voice_status():
    import voice_sandbox

    return voice_sandbox.voice_status()


@app.post("/voice/sandbox/start")
def start_voice_sandbox_session(payload: VoiceSandboxStartRequest):
    import voice_sandbox

    try:
        return voice_sandbox.start_voice_sandbox(payload.model_dump(exclude_none=True))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/voice/sandbox/{session_id}/stop")
def stop_voice_sandbox_session(session_id: str):
    import voice_sandbox

    return _handle_write(voice_sandbox.stop_voice_sandbox, session_id)


@app.post("/voice/sandbox/{session_id}/tune")
def tune_voice_sandbox_session(session_id: str, payload: VoiceSandboxTuneRequest):
    import voice_sandbox

    delta = payload.tuning if isinstance(payload.tuning, dict) else payload.model_dump(exclude_none=True)
    return _handle_write(voice_sandbox.tune_voice_sandbox, session_id, delta)


def _twilio_signature_ok(request: Request, form: dict[str, Any]) -> bool:
    """Validate X-Twilio-Signature.

    Production fail-closed: missing ``TWILIO_AUTH_TOKEN`` or missing signature → reject.
    Non-prod may omit the token for local ngrok smoke tests.
    """
    from voice import twilio_ops

    token = twilio_ops.auth_token()
    if not token:
        if _IS_PROD:
            logger.error("TWILIO_AUTH_TOKEN unset in production — rejecting Twilio request")
            return False
        return True
    signature = (request.headers.get("x-twilio-signature") or "").strip()
    if not signature:
        # Local ngrok tests sometimes omit; allow only outside production.
        return not _IS_PROD
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
    if not a or not b or len(a) != len(b):
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
    Production fails closed without a valid secret.
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
    # upgrade does not carry X-Twilio-Signature. Outside production we allow
    # the upgrade so local ngrok/dev runs work.
    #
    # Production fails closed. A configured TWILIO_AUTH_TOKEN is *not* an
    # authorization signal for this socket — nothing on the upgrade proves the
    # peer holds it, so treating token presence as sufficient left the media
    # stream open to anyone who learned the URL. Prod therefore requires
    # VOICE_WS_PROXY_SECRET to be configured *and* supplied; a deployment with
    # no secret configured is a misconfiguration, not an open door.
    if _IS_PROD:
        if not shared:
            logger.error(
                "Voice WS proxy rejected: VOICE_WS_PROXY_SECRET is not configured in production"
            )
        else:
            logger.warning("Voice WS proxy rejected: missing/invalid proxy secret")
        return False
    return True


@app.post("/twilio/voice/incoming")
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


@app.post("/twilio/voice/fallback")
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


@app.post("/twilio/voice/stream-status")
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


@app.post("/twilio/voice/call-status")
async def twilio_voice_call_status(request: Request):
    """Incoming Phone Number StatusCallback — dial/ring/answer/complete."""
    form = dict(await request.form())
    if not _twilio_signature_ok(request, form):
        raise HTTPException(status_code=403, detail="invalid_twilio_signature")

    call_sid = str(form.get("CallSid") or "")
    status = str(form.get("CallStatus") or form.get("CallStatusCallbackEvent") or "")
    duration = str(form.get("CallDuration") or form.get("Duration") or "")
    logger.info(
        "Twilio call status CallSid=%s status=%s duration=%s",
        call_sid or None,
        status or None,
        duration or None,
    )
    return Response(status_code=204)


@app.post("/twilio/voice/outbound")
async def twilio_voice_outbound(payload: dict[str, Any]):
    """Start an outbound PSTN call that connects into the same Media Stream bot."""
    from voice import twilio_ops

    if not twilio_ops.configured():
        raise HTTPException(status_code=503, detail="twilio_not_configured")
    to = str(payload.get("to") or payload.get("phone") or "").strip()
    if not to:
        raise HTTPException(status_code=400, detail="to_required")
    custom = {
        k: str(v)
        for k, v in (payload.get("custom") or {}).items()
        if v is not None
    }
    if payload.get("customerId"):
        custom["customer_id"] = str(payload["customerId"])
    try:
        return twilio_ops.start_outbound_call(to=to, custom=custom or None)
    except Exception as exc:
        logger.exception("Twilio outbound failed")
        raise HTTPException(status_code=502, detail="twilio_outbound_failed") from exc


@app.get("/twilio/voice/status")
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
    from voice.host import embedded_host_enabled, run_websocket_session
    from voice.ws_proxy import proxy_voice_websocket, ws_proxy_enabled

    embedded = embedded_host_enabled()
    if not embedded and not ws_proxy_enabled():
        await websocket.close(code=1008)
        return
    # The upgrade gate applies to both modes — hosting the pipeline in-process
    # makes an unauthenticated socket more dangerous, not less.
    if not _voice_ws_upgrade_authorized(websocket, path_secret=path_secret):
        await websocket.close(code=1008, reason="unauthorized")
        return
    if embedded:
        await run_websocket_session(websocket)
        return
    await proxy_voice_websocket(websocket)


@app.websocket("/ws")
async def voice_media_stream_proxy(websocket: WebSocket):
    await _voice_media_stream_entry(websocket)


@app.websocket("/ws/{proxy_secret}")
async def voice_media_stream_proxy_with_secret(
    websocket: WebSocket, proxy_secret: str
):
    await _voice_media_stream_entry(websocket, path_secret=proxy_secret)


@app.get("/conversations", response_model=list[ConversationListResponse])
def list_conversations(updatedAfter: str | None = None):
    try:
        return db.list_conversations(updated_after=updatedAfter)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/conversations/{conversation_id}", response_model=ConversationListResponse)
def get_conversation(conversation_id: str):
    conversation = db.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    return conversation


@app.post("/conversations/{conversation_id}/takeover", response_model=ConversationListResponse)
def takeover_conversation(conversation_id: str):
    return _handle_write(db.takeover_conversation, conversation_id)


@app.post("/conversations/{conversation_id}/return-to-bot", response_model=ConversationListResponse)
def return_conversation_to_bot(conversation_id: str):
    return _handle_write(db.return_conversation_to_bot, conversation_id)


@app.post("/conversations/{conversation_id}/messages", response_model=ConversationListResponse)
def send_conversation_message(conversation_id: str, payload: ConversationMessageCreateRequest):
    return _handle_write(
        db.send_conversation_message,
        conversation_id,
        payload.model_dump(),
    )


@app.get("/canned-responses", response_model=list[CannedResponseItem])
def list_canned_responses():
    return db.list_canned_responses()


@app.post("/kb/retrieve", response_model=KbRetrieveResponse)
def kb_retrieve_endpoint(payload: KbRetrieveRequest):
    """Test / runtime retrieval against embedded kb_chunks + faq_pairs."""
    try:
        return kb_retrieve.retrieve(
            query=payload.query,
            top_k=payload.topK,
            include_draft_answer=payload.includeDraftAnswer,
            source=payload.source,
        )
    except kb_rate_limit.RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.exception("kb_retrieve_failed")
        raise HTTPException(status_code=502, detail="kb_retrieve_failed") from None


@app.get("/kb/stats", response_model=KbStatsResponse)
def kb_stats():
    return db.get_kb_stats()


@app.get("/kb/documents", response_model=list[KbDocumentResponse])
def kb_list_documents():
    return db.list_kb_documents()


@app.get("/kb/documents/{document_id}", response_model=KbDocumentResponse)
def kb_get_document(document_id: str):
    doc = db.get_kb_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="kb_document_not_found")
    return doc


@app.get("/kb/documents/{document_id}/chunks", response_model=list[KbChunkResponse])
def kb_list_chunks(document_id: str):
    if not db.get_kb_document(document_id):
        raise HTTPException(status_code=404, detail="kb_document_not_found")
    return db.list_kb_chunks(document_id)


@app.patch("/kb/documents/{document_id}", response_model=KbUploadResponse)
def kb_patch_document(document_id: str, payload: KbDocumentPatchRequest):
    try:
        result = db.patch_kb_document(document_id, payload.model_dump(exclude_none=True))
        return {"document": result["document"], "jobId": result.get("jobId")}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        # A DB/storage outage is not a client error, and str(exc) on a driver
        # exception leaks connection details into the response body.
        logger.exception("kb_patch_document_failed document=%s", document_id)
        raise HTTPException(status_code=502, detail="kb_patch_failed") from None


@app.post("/kb/documents/{document_id}/reindex", response_model=KbReindexResponse)
def kb_reindex_document(document_id: str):
    try:
        return db.reindex_kb_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/kb/documents/{document_id}", response_model=KbDeleteDocumentResponse)
def kb_delete_document(document_id: str):
    try:
        return db.delete_kb_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/kb/documents/purge", response_model=KbPurgeResponse)
def kb_purge_documents(payload: KbPurgeRequest):
    try:
        return db.purge_kb_documents(scope=payload.scope, confirm=payload.confirm)
    except ValueError as exc:
        msg = str(exc)
        if msg == "confirm_required":
            raise HTTPException(status_code=400, detail="confirm must be true") from exc
        raise HTTPException(status_code=400, detail=msg) from exc


@app.post("/kb/ingest/source-db", response_model=KbIngestSourceDbResponse)
def kb_ingest_source_db(product: str | None = Query(default=None)):
    """Re-ingest policy/benefits/FAQs from disk source_db/ (same as CLI)."""
    try:
        return db.ingest_kb_from_source_db(product=product)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        # Static detail: the underlying exception carries DSNs, file paths and
        # Azure error bodies that must not reach an API client.
        logger.exception("kb_ingest_source_db failed product=%s", product)
        raise HTTPException(status_code=502, detail="kb_ingest_failed") from exc


@app.post("/kb/reindex-all")
def kb_reindex_all():
    result = db.reindex_all_kb_documents()
    # Snapshot hook — freeze post-queue corpus pointer for sandbox readiness.
    try:
        snap = db.create_kb_snapshot(label=f"After reindex-all ({result.get('count', 0)} jobs)")
        result["snapshot"] = snap
    except Exception:
        # Reindex itself succeeded; a missing snapshot only costs sandbox
        # reproducibility — but it must not disappear silently.
        logger.warning(
            "kb_snapshot_after_reindex_failed jobs=%s", result.get("count", 0), exc_info=True
        )
        result["snapshot"] = None
    return result


@app.get("/kb/index-jobs/{job_id}", response_model=KbIndexJobResponse)
def kb_get_index_job(job_id: str):
    job = db.get_kb_index_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="kb_index_job_not_found")
    return job


@app.post("/kb/documents", response_model=KbUploadResponse)
async def kb_upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    type: str = Form("policy"),
    chunkSize: int = Form(512),
    overlap: int = Form(64),
    indexNow: bool = Form(True),
    tags: str = Form("[]"),
):
    try:
        tag_list = json.loads(tags) if tags else []
        if not isinstance(tag_list, list):
            raise ValueError("tags must be a JSON array")
        data = await _read_upload_capped(file)
        # Sync MinIO + DB off the event loop.
        result = await asyncio.to_thread(
            db.create_kb_document_from_upload,
            filename=file.filename or "upload.txt",
            data=data,
            content_type=file.content_type or "application/octet-stream",
            title=title,
            doc_type=type,
            chunk_size=chunkSize,
            overlap=overlap,
            index_now=indexNow,
            tags=[str(t) for t in tag_list],
        )
        return result
    except storage.StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.exception("kb_upload_failed")
        raise HTTPException(status_code=502, detail="kb_upload_failed") from None


@app.post("/kb/documents/{document_id}/versions", response_model=KbUploadResponse)
async def kb_new_version(document_id: str, file: UploadFile = File(...)):
    try:
        data = await _read_upload_capped(file)
        return await asyncio.to_thread(
            db.create_kb_document_version,
            document_id,
            filename=file.filename or "upload.txt",
            data=data,
            content_type=file.content_type or "application/octet-stream",
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except storage.StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.exception("kb_version_failed")
        raise HTTPException(status_code=502, detail="kb_version_failed") from None


@app.get("/kb/faqs", response_model=list[KbFaqResponse])
def kb_list_faqs():
    return db.list_kb_faqs()


@app.post("/kb/faqs", response_model=KbFaqResponse)
def kb_create_faq(payload: KbFaqCreateRequest):
    try:
        return db.create_kb_faq(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/kb/faqs/{faq_id}", response_model=KbFaqResponse)
def kb_patch_faq(faq_id: str, payload: KbFaqPatchRequest):
    try:
        return db.patch_kb_faq(faq_id, payload.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/kb/faqs/{faq_id}", status_code=204)
def kb_delete_faq(faq_id: str):
    try:
        db.delete_kb_faq(faq_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@app.get("/kb/gaps", response_model=list[KbGapResponse])
def kb_list_gaps():
    return db.list_kb_gaps()


@app.post("/kb/gaps/{gap_id}/link", response_model=KbGapResponse)
def kb_link_gap(gap_id: str, payload: KbGapLinkRequest):
    """Link a gap to exactly one of FAQ / KB doc / prompt version."""
    try:
        return db.link_kb_gap(gap_id, payload.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        if msg == "gap_link_exactly_one_target":
            raise HTTPException(status_code=409, detail=msg) from exc
        raise HTTPException(status_code=400, detail=msg) from exc


@app.get("/kb/snapshots", response_model=list[KbSnapshotResponse])
def kb_list_snapshots():
    return db.list_kb_snapshots()


@app.post("/kb/snapshots", response_model=KbSnapshotResponse)
def kb_create_snapshot(payload: KbSnapshotCreateRequest | None = None):
    label = payload.label if payload else None
    return db.create_kb_snapshot(label=label)


@app.post(
    "/conversations/{conversation_id}/suggestions/refresh",
    response_model=ConversationSuggestionsRefreshResponse,
)
def refresh_conversation_suggestions(
    conversation_id: str,
    payload: ConversationSuggestionsRefreshRequest | None = None,
):
    """Debounced Inbox consumer: shared retrieve() → ai_response_suggestions chips."""
    body = payload or ConversationSuggestionsRefreshRequest()
    try:
        return db.refresh_conversation_suggestions(
            conversation_id,
            top_k=body.topK,
            include_draft_answer=body.includeDraftAnswer,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except kb_rate_limit.RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("inbox rag refresh failed conversation=%s", conversation_id)
        raise HTTPException(status_code=502, detail="inbox_rag_failed") from exc


@app.get("/webhooks/whatsapp")
@app.get("/webhook/whatsapp")  # Meta UI sometimes omits the plural "s"
def whatsapp_webhook_verify(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification challenge."""
    cfg = whatsapp.config()
    expected = cfg.get("verify_token")
    if hub_mode == "subscribe" and expected and hub_verify_token == expected and hub_challenge is not None:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="whatsapp_verify_failed")


@app.post("/webhooks/whatsapp")
@app.post("/webhook/whatsapp")
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
