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
import time
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import Depends, Header, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import HTTPConnection
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import BaseHTTPMiddleware

import actor_context
import authz
import azure_openai
import circuit_breaker
import db
import observability
import request_context
import flow_graph
from agent_core.cards.compile import CompileError
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
    ContactPolicyResponse,
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
    HandoffDisclosureRequest,
    HandoffQueueResponse,
    HandoffSessionResponse,
    InteractionCreateRequest,
    InteractionWrapUpRequest,
    LeadCreateRequest,
    LeadPatchRequest,
    LeadMetricsResponse,
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
    ProviderBindingInput,
    ProviderBindingItem,
    ProviderModelItem,
    ProviderPoolStatus,
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
    TreatmentHoldCreateRequest,
    TreatmentHoldReleaseRequest,
    AuthorityApplyRequest,
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
    "/pay",
    "/webhooks/payments",
    "/ws",
    "/.well-known/agent-card.json",
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
        if request.method == "POST" and path == "/a2a":
            return await call_next(request)
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
        # Separate binding for logs. Deliberately not read back into identity:
        # see request_context's module docstring.
        log_token = request_context.set_actor(actor_id)
        try:
            return await call_next(request)
        finally:
            request_context.reset_actor(log_token)
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
        # Also bind to a ContextVar: request.state is reachable only by code
        # holding the Request, which is almost nothing — db, voice and worker
        # threads all logged without it. See request_context for why.
        token = request_context.set_request_id(rid)
        try:
            response = await call_next(request)
        finally:
            request_context.reset_request_id(token)
        response.headers["X-Request-Id"] = rid
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """Count and time every request, labelled by ROUTE TEMPLATE.

    Placed outside ApiKeyMiddleware so 401s and 403s are counted too — an auth
    failure spike is exactly the thing worth alerting on, and instrumenting
    inside the gate would make it invisible.

    The route is resolved after ``call_next``, because Starlette only populates
    ``scope["route"]`` once routing has happened. A request that matched no
    route is labelled ``<unmatched>`` rather than by its raw path: 404 scans are
    the classic way an unbounded label set gets into a metrics backend.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        started = time.perf_counter()
        observability.http_in_flight.inc()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            # An unhandled exception still becomes a 500 to the client, so it
            # must appear in the metric as one rather than vanishing.
            raise
        finally:
            observability.http_in_flight.dec()
            route = request.scope.get("route")
            template = getattr(route, "path", None) or "<unmatched>"
            try:
                observability.observe_request(
                    method=request.method,
                    route=template,
                    status_code=status_code,
                    seconds=time.perf_counter() - started,
                )
            except Exception:
                # Instrumentation must never be the reason a request fails.
                logger.debug("request metric failed", exc_info=True)


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
    # Before anything else logs: converting handlers after startup has already
    # emitted its lines leaves the boot sequence in the old format, which is
    # exactly the part you want structured when a deploy fails.
    observability.setup_logging()
    observability.setup_error_tracking()
    observability.register_collectors()
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
            # Catalog rows only, never grants — so the permissions an operator
            # can assign exist in a fresh database without re-granting anything
            # they previously revoked.
            await asyncio.to_thread(authz.ensure_permission_catalog)
        except Exception:
            logger.warning("authz.ensure_permission_catalog failed", exc_info=True)
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
        try:
            from agent_core.skills.persist import ensure_first_party_skills

            await asyncio.to_thread(ensure_first_party_skills)
        except Exception:
            logger.warning("skill catalog boot seed failed", exc_info=True)
        try:
            # The capability matrix lives in agent_core/providers/registry.py and
            # reaches the database only through this upsert. Without it, the sole
            # writer was migration 0092's static INSERT, so every later edit —
            # a new model, a corrected service_class, a params_schema entry —
            # needed its own migration or silently never shipped.
            from agent_core.providers.persist import sync_seed as sync_provider_seed

            await asyncio.to_thread(sync_provider_seed)
        except Exception:
            logger.warning("provider registry boot seed failed", exc_info=True)
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


async def _authz_guard(conn: HTTPConnection) -> None:
    """Per-route permission check, applied to every route in the app.

    Registered as a global dependency rather than 180 per-route ``Depends``
    arguments so the policy is one reviewable table (``authz.ROUTE_PERMISSIONS``)
    and so ``tests/test_authz.py`` can prove it covers the whole route table — a
    forgotten ``Depends`` is silent, a missing registry row is a test failure.

    Dependencies resolve after routing, so ``scope["route"].path`` is the path
    *template* (``/customers/{customer_id}``), which is what the registry keys
    on. Falling back to the raw path would mean a parameterised route never
    matches and is therefore denied — the safe direction, but useless.

    The parameter is an ``HTTPConnection`` — the base class of both ``Request``
    and ``WebSocket`` — because "every route in the app" includes the two
    websocket ones. Annotated ``Request``, this did not quietly skip sockets:
    FastAPI cannot build a ``Request`` from a websocket scope, so the dependency
    solver raised ``TypeError`` and rejected the upgrade with a 500. Twilio's
    Media Stream never connected, the customer heard silence, and every status
    callback still reported a healthy call.
    """
    # A socket has no method, and the registry is keyed on one. The two
    # websocket routes authorise themselves with ``VOICE_WS_PROXY_SECRET``
    # (`_voice_ws_upgrade_authorized`, fail-closed in production) — that is the
    # design, not an oversight. ``tests/test_voice_ws_authz.py`` pins the route
    # list so a websocket added later cannot inherit this exemption in silence.
    if conn.scope.get("type") != "http":
        return

    route = conn.scope.get("route")
    path_template = getattr(route, "path", None) or conn.url.path
    method = conn.scope.get("method", "")
    # Only an actor the auth middleware actually authenticated counts. Not
    # actor_context.get_actor_user_id(), which falls back to the process default
    # — that would hand an unauthenticated caller the default user's grants.
    actor = getattr(conn.state, "actor_user_id", None)
    try:
        authz.check(method, path_template, actor)
    except authz.PermissionDenied as exc:
        logger.warning(
            "authz denied actor=%s %s %s (needs %s)",
            actor, method, path_template, exc.permission,
        )
        observability.observe_authz_denial(route=path_template, permission=exc.permission)
        raise HTTPException(status_code=403, detail=f"forbidden:{exc.permission}") from exc


class Utf8JSONResponse(JSONResponse):
    """JSON responses that state their encoding instead of assuming it is obvious.

    Starlette only appends ``charset`` to ``text/*`` media types, so every
    response here went out as a bare ``application/json``. RFC 8259 makes UTF-8
    mandatory for JSON exchanged between systems, so that is not *wrong* — but a
    charset nobody states is a charset every client is free to guess, and a
    significant number of them guess ISO-8859-1.

    That is not hypothetical. Windows PowerShell 5.1's ``Invoke-RestMethod`` —
    the default HTTP client on the machines this is operated from — decodes a
    charset-less response as ISO-8859-1, which turns the three correct UTF-8
    bytes of an em dash into the three characters U+00E2 U+0080 U+0094. An audit
    of the skill catalog did exactly that and reported permanent mojibake inside
    a signed first-party pack, with the contentHash and signature said to cover
    the corrupt bytes. Two rounds of investigation went into a repair migration
    for data that was never damaged: the database, the disk and the wire all
    held U+2014 the whole time, and only the reader disagreed.

    For a product whose content is largely Hindi, Tamil, Telugu, Kannada,
    Marathi and Bengali, a client that silently mangles every non-ASCII
    character is not a curiosity. Nine bytes of header removes the ambiguity.
    """

    media_type = "application/json; charset=utf-8"


app = FastAPI(
    title="Collections Agent API",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(_authz_guard)],
    default_response_class=Utf8JSONResponse,
    # Prod: do not publish the OpenAPI schema unauthenticated.
    docs_url=None if _IS_PROD else "/docs",
    redoc_url=None if _IS_PROD else "/redoc",
    openapi_url=None if _IS_PROD else "/openapi.json",
)

class StreamingAwareGZipMiddleware(GZipMiddleware):
    """GZip buffers StreamingResponse. SSE copilot (and any ``/stream``) must
    flush event-by-event or Handoff sees the whisper only after the call ends.
    """

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] == "http":
            path = str(scope.get("path") or "")
            if path.endswith("/stream"):
                await self.app(scope, receive, send)
                return
        await super().__call__(scope, receive, send)


# Starlette inserts each add_middleware at index 0 → last added is OUTERMOST.
# Desired order (outer → inner): CORS → RequestId → Metrics → ApiKey → GZip → route
# so (1) preflight/401s always get CORS headers, (2) RequestId wraps everything
# so the 401/400 responses auth generates still carry X-Request-Id (previously
# rejected requests were unattributable in the logs), (3) Metrics wraps ApiKey so
# auth failures are counted rather than invisible, and (4) ApiKey sees OPTIONS
# only after CORS has claimed it — still pass OPTIONS through ApiKey.
app.add_middleware(StreamingAwareGZipMiddleware, minimum_size=1024)
app.add_middleware(ApiKeyMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(RequestIdMiddleware)

#: Response headers a browser client is allowed to read.
#:
#: `allow_headers=["*"]` covers *request* headers and does nothing for these:
#: without an explicit expose list, `fetch().headers.get("X-Tts-Cache")` is
#: null on every cross-origin call, and the studio runs on :8080 against this
#: API on :8000. So the Voice tab's "cache hit · 240ms" line had been reading
#: three headers it could never see, and silently rendering nothing for them.
#:
#: X-Tts-Cache is now load-bearing rather than cosmetic — it is how the studio
#: tells the operator whether they are hearing the same take as last time.
#: Content-Disposition is on this list for exactly the reason above, one
#: endpoint later. The skill export sets a correct quoted filename and the
#: browser could not read it, so `apiGetBlob` saw a null header every time and
#: fell through to `${skill.id}.zip` — a file named after a row id rather than
#: the pack. The note about `allow_headers` not covering response headers was
#: already written here when export was added; the list was not extended.
_CORS_EXPOSE_HEADERS = [
    "X-Request-Id",
    "X-Tts-Cache",
    "X-Tts-Voice",
    "X-Tts-Latency-Ms",
    "X-Tts-Provider",
    "Content-Disposition",
]

_cors_origins = [o.strip() for o in (os.getenv("CORS_ORIGINS") or "").split(",") if o.strip()]
if _cors_origins:
    # Prod: explicit allowlist + credentials (required for cookie auth).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=_CORS_EXPOSE_HEADERS,
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
        expose_headers=_CORS_EXPOSE_HEADERS,
    )

# VOICE_EMBEDDED_HOST=true: serve SmallWebRTC signalling here instead of
# requiring a second `python -m voice.bot` process on :7860 (Phase E1).
if _EMBEDDED_VOICE_HOST:
    from voice.host import register_routes as _register_voice_routes

    _register_voice_routes(app)


# Error bodies are JSON too, and `default_response_class` does not reach them.
#
# FastAPI builds HTTPException and validation responses with its own
# `JSONResponse`, so those went out as bare `application/json` even after the
# app default was set — leaving exactly the charset-less responses that started
# this, on the path most likely to carry a non-ASCII detail string (a customer
# name, a Hindi KB title, a skill slug echoed back in a 409).
#
# Delegating to the stock handler and rewriting one header keeps FastAPI's
# status codes, bodies and headers (including the WWW-Authenticate a 401 must
# carry) exactly as they were.
async def _json_charset(response: Response) -> Response:
    media = response.headers.get("content-type", "")
    if media.startswith("application/json") and "charset=" not in media.lower():
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response


@app.exception_handler(StarletteHTTPException)
async def _http_exception_charset(request: Request, exc: StarletteHTTPException):
    return await _json_charset(await http_exception_handler(request, exc))


@app.exception_handler(RequestValidationError)
async def _validation_exception_charset(request: Request, exc: RequestValidationError):
    return await _json_charset(await request_validation_exception_handler(request, exc))


# Azure concurrency saturation / circuit open → shed load fast.
@app.exception_handler(azure_openai.AzureBusyError)
async def _azure_busy_handler(_request: Request, exc: azure_openai.AzureBusyError):
    return Utf8JSONResponse(
        status_code=503,
        content={"detail": str(exc) or "azure_concurrency_saturated"},
    )


@app.exception_handler(circuit_breaker.CircuitOpenError)
async def _circuit_open_handler(_request: Request, exc: circuit_breaker.CircuitOpenError):
    return Utf8JSONResponse(
        status_code=503,
        content={"detail": str(exc) or "circuit_open"},
    )


def _handle_write(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        # `str(KeyError("x"))` is `"'x'"` — the repr, not the message. It reached
        # the UI verbatim, so an Archive that lost a race toasted the operator
        # `'agent_card_not_found_or_archived:sweep-probe'`, stray quotes and all.
        detail = str(exc.args[0]) if exc.args else str(exc)
        raise HTTPException(status_code=404, detail=detail) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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


@app.get("/pay/{token}", response_class=HTMLResponse)
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


@app.post("/pay/{token}/complete")
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


@app.post("/webhooks/payments/{provider}")
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
    with db.engine.begin() as conn:
        try:
            return payments.record_payment(
                conn,
                intent_id=parsed.get("intent_id"),
                public_token=parsed.get("public_token"),
                amount=amount,
                provider_ref=parsed.get("provider_ref"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/webhooks/collections/payment-events")
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
    with db.engine.begin() as conn:
        try:
            return pe.ingest(conn, body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/sandbox/payment-events")
def sandbox_payment_event(payload: dict[str, Any]):
    """Dev-only: same ingest() as the HMAC webhook, source defaults to sandbox."""
    import payment_events as pe
    import payments

    if payments.is_production():
        raise HTTPException(status_code=403, detail="sandbox_payment_events_disabled")
    body = dict(payload or {})
    body.setdefault("source", "sandbox")
    if not body.get("sourceRef") and not body.get("source_ref"):
        body["sourceRef"] = f"sandbox-{secrets.token_hex(8)}"
    with db.engine.begin() as conn:
        try:
            return pe.ingest(conn, body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/twins")
def list_simulation_twins():
    from agent_core.twin import ensure_default_twin, list_twins

    ensure_default_twin()
    return list_twins()


@app.post("/twins/{twin_id}/run")
def run_simulation_twin(twin_id: str, payload: dict[str, Any] | None = None):
    from agent_core.twin import replay_bounce_ladder

    state = (payload or {}).get("state") if isinstance(payload, dict) else None
    return replay_bounce_ladder(twin_id, state=state)


@app.get("/work-runtime/jobs/{job_id}")
def get_work_runtime_job(job_id: str):
    from work_runtime import query

    row = query(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="work_job_not_found")
    return row


@app.get("/metrics", include_in_schema=False)
def metrics():
    """Prometheus exposition.

    Authenticated and permission-gated like every other route, rather than
    exempted the way ``/health`` is: this publishes pool occupancy, breaker
    state and call volume, which is reconnaissance for an attacker and
    commercially sensitive besides. A scraper gets its own ``API_KEY_MAP``
    entry pointing at a service user holding ``perm-observability-read``.
    """
    body, content_type = observability.render()
    return Response(content=body, media_type=content_type)


@app.get("/customers", response_model=list[CustomerResponse])
def list_customers(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """Bounded list. Omitting ``limit`` yields the default page, not everything."""
    return db.list_customers(limit=limit, offset=offset)


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


@app.get("/customers/{customer_id}/contact-policy", response_model=ContactPolicyResponse)
def get_contact_policy(
    customer_id: str,
    channel: str = Query(default="whatsapp"),
    purpose: str = Query(default="outreach"),
):
    try:
        return db.get_contact_policy(customer_id, channel=channel, purpose=purpose)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


@app.get("/offers/tuner-suggestions")
def get_tuner_suggestions(days: int = Query(14, ge=1, le=90)):
    from agent_core.tuner import suggestions

    return suggestions(days=days)


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
def list_calls(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """Bounded list. Each row carries its full transcript, so the default page
    is deliberately smaller than for flat lists."""
    return db.list_calls(limit=limit, offset=offset)


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


@app.get("/leads", response_model=list[LeadResponse])
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


@app.get("/leads/metrics", response_model=LeadMetricsResponse)
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
def list_work_items(
    assignee: str | None = Query("me"),
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """Assigned queue from the work_items view. Default assignee=me is viewer-relative."""
    return db.list_work_items(assignee=assignee, limit=limit, offset=offset)


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
def list_promises(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_promises(limit=limit, offset=offset)


@app.get("/payment-plans", response_model=list[PaymentPlanResponse])
def list_payment_plans(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_payment_plans(limit=limit, offset=offset)


@app.get("/disputes", response_model=list[DisputeListResponse])
def list_disputes(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_disputes(limit=limit, offset=offset)


@app.get("/callbacks", response_model=list[CallbackListResponse])
def list_callbacks(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_callbacks(limit=limit, offset=offset)


@app.get("/consent", response_model=list[ConsentListResponse])
def list_consent(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_consent(limit=limit, offset=offset)


def _handoff_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/handoff/queue", response_model=HandoffQueueResponse)
def get_handoff_queue(customerId: str | None = Query(default=None)):
    return db.list_handoff_queue(customer_id=customerId)


@app.get("/handoff/active", response_model=HandoffSessionResponse)
def get_handoff_active():
    session = db.get_active_handoff_session()
    if session is None:
        return Response(status_code=204)
    return session


@app.get("/handoff/{interaction_id}", response_model=HandoffSessionResponse)
def get_handoff_by_id(interaction_id: str):
    return _handoff_call(db.get_handoff_session, interaction_id)


@app.post("/handoff/{interaction_id}/claim", response_model=HandoffSessionResponse)
def claim_handoff(interaction_id: str):
    return _handoff_call(db.claim_handoff, interaction_id)


@app.post("/handoff/{interaction_id}/disclosures", response_model=HandoffSessionResponse)
def post_handoff_disclosure(interaction_id: str, payload: HandoffDisclosureRequest):
    return _handoff_call(
        db.record_handoff_disclosure,
        interaction_id,
        payload.model_dump(exclude_none=True),
    )


@app.post("/handoff/{interaction_id}/suggestions/{suggestion_id}/accept", response_model=HandoffSessionResponse)
def accept_handoff_suggestion(interaction_id: str, suggestion_id: str):
    return _handoff_call(db.accept_handoff_suggestion, interaction_id, suggestion_id)


@app.get("/floor", response_model=FloorSnapshotResponse)
def get_floor():
    return ops_screens.get_floor_snapshot()


@app.get("/floor/copilot/{interaction_id}")
def get_floor_copilot(interaction_id: str):
    from agent_core.copilot import build

    pack = build(interaction_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="interaction_not_found")
    return pack


@app.get("/floor/copilot/{interaction_id}/stream")
def stream_floor_copilot(interaction_id: str):
    import json

    from fastapi.responses import StreamingResponse
    from agent_core.copilot import iter_events

    events = iter_events(interaction_id)
    first = next(events, None)
    if first is None or first.get("type") == "error":
        raise HTTPException(status_code=404, detail="interaction_not_found")

    def _sse() -> Any:
        yield f"event: {first['type']}\ndata: {json.dumps(first, default=str)}\n\n"
        for event in events:
            name = str(event.get("type") or "message")
            yield f"event: {name}\ndata: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/floor/approvals")
def list_floor_approvals():
    from work_runtime.adapter_pg import list_jobs

    return list_jobs(status="input_required")


@app.post("/floor/approvals/{job_id}/signal")
def signal_floor_approval(job_id: str, payload: dict[str, Any]):
    from work_runtime import signal

    name = str(payload.get("name") or payload.get("signal") or "").strip()
    if name not in {"approve", "reject"}:
        raise HTTPException(status_code=422, detail="signal_must_be_approve_or_reject")
    try:
        return signal(job_id, name, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


@app.post("/promises/{promise_id}/resend-confirm")
def resend_promise_confirm(promise_id: str):
    return _handle_write(db.resend_promise_confirm, promise_id)


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


@app.post("/document-requests/ingest")
async def ingest_document_request(
    customer_id: str = Form(...),
    conversation_id: str | None = Form(None),
    interaction_id: str | None = Form(None),
    file: UploadFile = File(...),
):
    from agent_core.vision import ingest_customer_document

    raw = await _read_upload_capped(file, max_bytes=8 * 1024 * 1024)
    result = ingest_customer_document(
        customer_id=customer_id,
        filename=file.filename or "receipt.jpg",
        mime_type=file.content_type or "image/jpeg",
        identity_verified=bool(customer_id) and customer_id != "UNKNOWN-CALLER",
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


@app.get("/document-requests", response_model=list[DocumentListResponse])
def list_document_requests(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_documents(limit=limit, offset=offset)


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


@app.get("/compliance/rule-coverage")
def get_rule_coverage():
    """Per rule: does a detector exist, and what has it actually found?

    The Compliance Risk page could previously show a rule with no violations
    and a rule nobody is checking as the same thing — an empty row. Fifteen of
    the sixteen seeded rules were in the second category. `state` is the
    three-way answer: clean / breached / unverified.
    """
    from agent_core import compliance

    return compliance.detector_coverage()


@app.post("/compliance/rescan")
def rescan_compliance(
    limit: int = Query(200, ge=1, le=2000),
    all: bool = Query(False, description="Drain the whole queue, not one batch"),
):
    """Re-judge interactions the ledger has not evaluated at this rules version.

    The worker does this on a timer; this endpoint exists so a rule change can
    be applied to history on demand instead of waiting for the next tick.
    """
    from agent_core import compliance

    return compliance.backfill(batch=limit) if all else compliance.sweep(limit=limit)


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
def get_rubric(rubric_id: str | None = Query(default=None, alias="rubricId")):
    """Active Collections Interaction Rubric (screen defaultRubric shape)."""
    try:
        return db.get_rubric(rubric_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/scorecards", response_model=list[ScorecardListResponse])
def list_scorecards():
    return db.list_scorecards()


@app.get("/qa/coverage")
def qa_coverage(days: int = Query(default=7, ge=1, le=90)):
    return db.qa_coverage_stats(days=days)


@app.get("/qa/interactions/{interaction_id}/pack")
def qa_interaction_pack(interaction_id: str):
    from agent_core.live_qa.pack import build_pack

    pack = build_pack(interaction_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="interaction_not_found")
    return pack


@app.post("/scorecards", response_model=ScorecardListResponse)
def create_scorecard(payload: ScorecardCreateRequest):
    return _handle_write(db.create_scorecard, payload.model_dump(exclude_unset=True))


@app.patch("/scorecards/{scorecard_id}", response_model=ScorecardListResponse)
def patch_scorecard(scorecard_id: str, payload: ScorecardPatchRequest):
    # exclude_unset (not exclude_none) so present keys are intentional.
    return _handle_write(db.patch_scorecard, scorecard_id, payload.model_dump(exclude_unset=True))


@app.get("/coaching-actions", response_model=list[CoachingActionResponse])
def list_coaching_actions(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_coaching_actions(limit=limit, offset=offset)


@app.post("/coaching-actions", response_model=CoachingActionResponse)
def create_coaching_action(payload: CoachingActionCreateRequest):
    return _handle_write(db.create_coaching_action, payload.model_dump(exclude_unset=True))


@app.patch("/coaching-actions/{action_id}", response_model=CoachingActionResponse)
def patch_coaching_action(action_id: str, payload: CoachingActionPatchRequest):
    return _handle_write(
        db.patch_coaching_action, action_id, payload.model_dump(exclude_unset=True)
    )


@app.get("/calibration-sessions", response_model=list[CalibrationSessionResponse])
def list_calibration_sessions(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_calibration_sessions(limit=limit, offset=offset)


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
def list_export_jobs(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_export_jobs(limit=limit, offset=offset)


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
def list_prompt_versions(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
    botId: str | None = Query(default=None),
):
    """Prompt Studio version history (newest first)."""
    return db.list_prompt_versions(limit=limit, offset=offset, bot_id=botId)


@app.get("/prompt-versions/published", response_model=PromptVersionResponse)
def get_published_prompt_version(botId: str | None = Query(default=None)):
    """Editor live badge — published row for this bot (Collections by default)."""
    row = db.get_published_prompt_version(botId)
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


@app.get("/flow/built-in", response_model=FlowGraph)
def get_built_in_flow(graph: str | None = Query(default=None)):
    """The running built-in collections script, as an authored graph.

    Lets the Flow tab start from what the agent actually does today instead of
    a blank canvas. Derived from ``voice.flows.build_collections_flow`` on every
    request, so it cannot drift from the Python it mirrors. Loading it only
    fills the editor — the live agent keeps running the built-in script until
    the draft is published.
    """
    from voice.flow_export import built_in_collections_graph

    return built_in_collections_graph(graph=graph)


@app.get("/flow/transitions", response_model=dict[str, list[str]])
def get_flow_transitions():
    """tool key -> node keys that tool moves the conversation to.

    The built-in tools transition by node key, so a graph that uses reserved
    keys has real transitions with no authored edges — twelve nodes and zero
    lines on the canvas. The editor draws these as ghost edges so what leads
    where is visible without inventing edges the runtime would ignore.
    """
    return flow_graph.implicit_transitions()


@app.get("/flow/reserved-keys", response_model=dict[str, str])
def list_flow_reserved_keys():
    """Node keys the built-in tools transition to by name.

    A graph is free to ignore them; using one wires up that built-in hop. The
    editor surfaces these so the choice is visible rather than a trap.
    """
    return flow_graph.RESERVED_NODE_KEYS


@app.get("/agent-studio/cards")
def list_agent_studio_cards(includeArchived: bool = Query(default=False)):
    return db.list_agent_studio_cards(include_archived=includeArchived)


@app.get("/agent-studio/templates")
def list_agent_studio_templates():
    from agent_core.cards.templates import templates

    return templates()


@app.post("/agent-studio/cards/clone")
def clone_agent_studio_card(payload: dict[str, Any]):
    from agent_core.cards.clone import clone_card

    return _handle_write(
        clone_card,
        template_id=payload.get("templateId") or payload.get("template_id"),
        source_bot_id=payload.get("sourceBotId") or payload.get("source_bot_id"),
        name=payload.get("name"),
    )


@app.get("/agent-studio/cards/{bot_id}")
def get_agent_studio_card(bot_id: str):
    row = db.get_agent_studio_card(bot_id)
    if row is None:
        raise HTTPException(status_code=404, detail="agent_card_not_found")
    return row


@app.patch("/agent-studio/cards/{bot_id}")
def patch_agent_studio_card(bot_id: str, payload: dict[str, Any]):
    """Patch the latest draft for this bot, creating one from published if needed."""
    card = payload.get("agentCard") or payload.get("agent_card")
    versions = db.list_prompt_versions(bot_id=bot_id, limit=20)
    draft = next((v for v in versions if v["status"] == "draft"), None)
    if draft is None:
        published = db.get_published_prompt_version(bot_id)
        if published is None:
            raise HTTPException(status_code=404, detail="agent_card_not_found")
        draft = db.restore_prompt_version_as_draft(published["id"])
    body: dict[str, Any] = {}
    if isinstance(card, dict):
        body["agentCard"] = card
    if "flow" in payload:
        body["flow"] = payload["flow"]
    if not body:
        return draft
    return _handle_write(db.patch_prompt_version, draft["id"], body)


@app.post("/agent-studio/cards/{bot_id}/archive")
def archive_agent_studio_card(bot_id: str):
    """Retire a tenant card. Refuses first-party and the runtime entry bot.

    An active production deployment is retired here, not refused — this text
    used to say otherwise, and it was the description OpenAPI served long after
    the guard was removed for making the feature unreachable (publish always
    leaves an active deployment).
    """
    return _handle_write(db.archive_agent_studio_card, bot_id)


@app.post("/agent-studio/cards/{bot_id}/restore")
def restore_agent_studio_card(bot_id: str):
    """Put a retired card back on the roster. Does not redeploy it."""
    return _handle_write(db.restore_agent_studio_card, bot_id)


@app.get("/agent-studio/change-log")
def get_agent_change_log(
    botId: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
):
    """Who changed what an agent says, when, and what the compiler said then.

    Hash-chained: the response carries a `chain` verdict, so a rewritten or
    deleted historical entry is visible rather than merely absent.
    """
    return db.agent_change_log(botId, limit=limit)


@app.post("/agent-studio/cards/{bot_id}/compile")
def compile_agent_studio_card(bot_id: str, payload: dict[str, Any] | None = None):
    body = payload or {}
    pct = body.get("trafficPct", body.get("traffic_pct"))
    triggers = body.get("autoRollback", body.get("auto_rollback"))
    return db.compile_agent_studio_card(
        bot_id,
        card_raw=body.get("agentCard") or body.get("agent_card"),
        flow=body.get("flow"),
        # Preview what publish will ship, not what the card was authored with.
        traffic_pct=int(pct) if isinstance(pct, (int, float)) else None,
        auto_rollback=[str(t) for t in triggers] if isinstance(triggers, list) else None,
        # G15 reads the mouth columns, which the editor holds unsaved between
        # autosaves. Omitted, the preview gates the last saved voice rather than
        # the one the Publish button is about to ship.
        voice=body.get("voice") if isinstance(body.get("voice"), dict) else None,
        persona=body.get("persona") if isinstance(body.get("persona"), dict) else None,
    )


@app.post("/agent-studio/cards/{bot_id}/publish")
def publish_agent_studio_card(bot_id: str, payload: PromptVersionPublishRequest):
    """Publish one of this bot's drafts — the one the caller names, by preference.

    This used to take ``next(v for v in newest_20 if v["status"] == "draft")``:
    whichever draft happened to sort first inside an arbitrary window, with no
    way for the caller to say which draft it meant. A bot with two open drafts
    therefore published a version nobody selected, and the studio — which tracks
    the exact draft it is editing — could not express its choice through this
    endpoint at all.

    So: publish what was asked for; publish the only draft when there is exactly
    one; and refuse rather than guess when there is more than one and no
    instruction. Guessing here promotes text to production.
    """
    versions = db.list_prompt_versions(bot_id=bot_id)
    drafts = [v for v in versions if v["status"] == "draft"]
    if payload.versionId:
        chosen = next((v for v in drafts if v["id"] == payload.versionId), None)
        if chosen is None:
            # Distinguish "not a draft of this bot" from "not a draft", since the
            # caller can fix only one of those.
            exists = any(v["id"] == payload.versionId for v in versions)
            raise HTTPException(
                status_code=409 if exists else 404,
                detail="prompt_version_not_draft" if exists else "prompt_version_not_found",
            )
        return publish_prompt_version(chosen["id"], payload)
    if not drafts:
        raise HTTPException(status_code=409, detail="no_draft_to_publish")
    if len(drafts) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "ambiguous_draft_to_publish: this bot has "
                f"{len(drafts)} open drafts ({', '.join(v['id'] for v in drafts)}). "
                "Name one with versionId."
            ),
        )
    return publish_prompt_version(drafts[0]["id"], payload)


@app.post("/agent-studio/cards/{bot_id}/connectors")
def attach_agent_studio_connector(bot_id: str, payload: dict[str, Any]):
    from agent_core.cards.clone import attach_connector_to_card

    connector_id = str(payload.get("connectorId") or payload.get("connector_id") or "").strip()
    if not connector_id:
        raise HTTPException(status_code=422, detail="connector_id_required")
    prefixes = payload.get("allowPrefixes") or payload.get("allow_prefixes")
    return _handle_write(
        attach_connector_to_card,
        bot_id,
        connector_id=connector_id,
        allow_prefixes=prefixes,
    )


@app.get("/agent-studio/cards/{bot_id}/graph")
def get_agent_studio_graph(bot_id: str):
    card = db.get_agent_studio_card(bot_id)
    if card is None:
        raise HTTPException(status_code=404, detail="agent_card_not_found")
    raw = card.get("agentCard") or {}
    handoffs = raw.get("handoffs") if isinstance(raw, dict) else []
    return {
        "botId": bot_id,
        # Reachability rides along because list_agent_studio_cards already
        # computed it: the allowlist editor can then say whether a target takes
        # traffic today, and whether this card's own allowlist routes anything.
        "nodes": [
            {
                "id": c["botId"],
                "label": c["name"],
                "reachability": c["reachability"],
                "deploymentStatus": c["deploymentStatus"],
            }
            for c in db.list_agent_studio_cards()
        ],
        "edges": [
            {"from": bot_id, "to": h.get("to_bot_id")}
            for h in (handoffs or [])
            if isinstance(h, dict)
        ],
    }


@app.get("/agent-studio/skills")
def list_agent_studio_skills():
    from agent_core.skills.persist import list_skills

    return list_skills()


@app.get("/agent-studio/skills/scripts")
def list_agent_studio_scripts():
    """Allowlisted code-mode scripts. The editor's picker hardcoded this list, so
    a new script was invisible and a removed one was still offered.

    Declared above /skills/{skill_id} — FastAPI matches in definition order, and
    the parameterised route would otherwise swallow "scripts".
    """
    from agent_core.skills.scripts import SCRIPT_NAMES

    return [{"name": n} for n in SCRIPT_NAMES]


@app.get("/agent-studio/skills/{skill_id}")
def get_agent_studio_skill(skill_id: str):
    from agent_core.skills.persist import get_skill

    row = get_skill(skill_id)
    if row is None:
        raise HTTPException(status_code=404, detail="skill_not_found")
    return row


@app.post("/agent-studio/skills")
def create_agent_studio_skill(payload: dict[str, Any]):
    from agent_core.skills.persist import create_draft_skill

    return _handle_write(create_draft_skill, payload)


@app.patch("/agent-studio/skills/{skill_id}")
def patch_agent_studio_skill(skill_id: str, payload: dict[str, Any]):
    from agent_core.skills.persist import patch_skill

    return _handle_write(patch_skill, skill_id, payload)


@app.delete("/agent-studio/skills/{skill_id}")
def delete_agent_studio_skill(skill_id: str):
    """Delete an unsigned tenant/gardener skill that no card is using.

    First-party, signed, or attached skills are refused (409) rather than
    orphaning a published card's pinned pack.
    """
    from agent_core.skills.persist import delete_skill

    return _handle_write(delete_skill, skill_id)


@app.post("/agent-studio/skills/{skill_id}/sign")
def sign_agent_studio_skill(skill_id: str):
    from agent_core.skills.persist import sign_skill

    return _handle_write(sign_skill, skill_id)


@app.post("/agent-studio/skills/{skill_id}/revert")
def revert_agent_studio_skill(skill_id: str, payload: dict[str, Any] | None = None):
    from agent_core.skills.persist import revert_skill

    body = payload or {}
    return _handle_write(revert_skill, skill_id, body.get("versionId") or body.get("version_id"))


@app.post("/agent-studio/skills/{skill_id}/clone")
def clone_agent_studio_skill(skill_id: str, payload: dict[str, Any] | None = None):
    from agent_core.skills.persist import clone_skill

    body = payload or {}
    return _handle_write(clone_skill, skill_id, body.get("slug"))


@app.post("/agent-studio/skills/{skill_id}/attach")
def attach_agent_studio_skill(skill_id: str, payload: dict[str, Any]):
    from agent_core.skills.persist import attach_skill_to_prompt

    version_id = str(payload.get("promptVersionId") or payload.get("prompt_version_id") or "").strip()
    if not version_id:
        raise HTTPException(status_code=422, detail="prompt_version_id_required")
    _handle_write(attach_skill_to_prompt, version_id, skill_id)
    return {"ok": True}


@app.post("/agent-studio/skills/{skill_id}/detach")
def detach_agent_studio_skill(skill_id: str, payload: dict[str, Any]):
    from agent_core.skills.persist import detach_skill_from_prompt

    version_id = str(payload.get("promptVersionId") or payload.get("prompt_version_id") or "").strip()
    if not version_id:
        raise HTTPException(status_code=422, detail="prompt_version_id_required")
    _handle_write(detach_skill_from_prompt, version_id, skill_id)
    return {"ok": True}


@app.get("/agent-studio/skills/{skill_id}/export")
def export_agent_studio_skill(skill_id: str):
    import io
    import zipfile

    from fastapi.responses import StreamingResponse
    from agent_core.skills.persist import get_skill

    row = get_skill(skill_id)
    if row is None:
        raise HTTPException(status_code=404, detail="skill_not_found")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", row.get("markdown") or "")
        refs = (row.get("pack") or {}).get("references") or {}
        for name, body in refs.items():
            zf.writestr(f"references/{name}", body)
    buf.seek(0)
    filename = f"{row.get('slug') or skill_id}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/agent-studio/skills/import")
async def import_agent_studio_skill(file: UploadFile = File(...)):
    import io
    import zipfile

    from agent_core.skills.pack import parse_skill_md
    from agent_core.skills.persist import upsert_skill_from_pack

    raw = await _read_upload_capped(file, max_bytes=2_000_000)
    md = ""
    refs: dict[str, str] = {}
    if (file.filename or "").endswith(".md"):
        md = raw.decode("utf-8")
    else:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if name.endswith("SKILL.md"):
                    md = zf.read(name).decode("utf-8")
                elif "/references/" in name or name.startswith("references/"):
                    refs[name.split("references/", 1)[-1]] = zf.read(name).decode("utf-8")
    if not md:
        raise HTTPException(status_code=422, detail="skill_md_missing")
    pack = parse_skill_md(md)
    pack.references = refs
    pack.origin = "tenant"
    pack.signed = False
    return upsert_skill_from_pack(pack, origin="tenant", signed=False)


@app.post("/agent-studio/skills/run-script")
def run_agent_studio_script(payload: dict[str, Any]):
    from agent_core.skills.scripts import run_script

    name = str(payload.get("name") or "").strip()
    args = payload.get("payload")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        # Reject rather than coerce. This used to substitute `{}` for anything
        # that was not a dict, so posting `[1, 2]` ran the script against no
        # arguments at all and returned `numeric_required` — a verdict that
        # reads exactly like one computed from the input, on input that was
        # never looked at. The console tells the user the payload "must be a
        # JSON object"; this is the endpoint agreeing with it.
        raise HTTPException(
            status_code=422,
            detail="script_payload_must_be_an_object",
        )
    return run_script(name, args)


@app.post("/kb/gaps/{gap_id}/promote-skill")
def promote_kb_gap_to_skill(gap_id: str):
    from agent_core.skills.gardener import assert_unsigned, draft_from_gap
    from agent_core.skills.persist import create_draft_skill

    gaps = {g["id"]: g for g in db.list_kb_gaps()}
    gap = gaps.get(gap_id)
    if gap is None:
        raise HTTPException(status_code=404, detail="kb_gap_not_found")
    draft = draft_from_gap(
        question=str(gap.get("question") or gap.get("text") or ""),
        intent=gap.get("topIntent") or gap.get("top_intent") or gap.get("intent"),
        gap_id=gap_id,
    )
    assert_unsigned(draft)
    return create_draft_skill(
        {
            "slug": draft["slug"],
            "description": draft["frontmatter"].get("description"),
            "allowed_tools": draft["allowed_tools"],
            "body": draft["body"],
            "frontmatter": draft["frontmatter"],
            "origin": "gardener",
        }
    )


@app.get("/connectors")
def list_connectors_api():
    from agent_core.connectors.persist import list_connectors

    return list_connectors()


@app.post("/connectors")
def upsert_connector_api(payload: dict[str, Any]):
    from agent_core.connectors.persist import upsert_connector

    return _handle_write(upsert_connector, payload)


@app.get("/connectors/{connector_id}")
def get_connector_api(connector_id: str):
    from agent_core.connectors.persist import get_connector

    row = get_connector(connector_id)
    if row is None:
        raise HTTPException(status_code=404, detail="connector_not_found")
    return row


@app.post("/connectors/{connector_id}/approve")
def approve_connector_api(connector_id: str):
    from agent_core.connectors.persist import approve

    return _handle_write(approve, connector_id)


@app.post("/connectors/{connector_id}/test")
def test_connector_api(connector_id: str):
    from agent_core.connectors.persist import health_test

    return _handle_write(health_test, connector_id)


@app.post("/connectors/{connector_id}/cimd")
def cimd_connector_api(connector_id: str, payload: dict[str, Any]):
    from agent_core.connectors.persist import cimd_connect

    issuer = str(payload.get("issuer") or "").strip()
    return _handle_write(cimd_connect, connector_id, issuer)


@app.get("/vault/refs")
def list_vault_refs_api():
    from agent_core.vault.persist import list_refs

    return list_refs()


@app.post("/vault/refs")
def put_vault_ref_api(payload: dict[str, Any]):
    from agent_core.vault.persist import put_secret

    return _handle_write(
        put_secret,
        name=str(payload.get("name") or ""),
        purpose=str(payload.get("purpose") or "other"),
        secret=str(payload.get("secret") or ""),
    )


@app.post("/vault/refs/{ref_id}/rotate")
def rotate_vault_ref_api(ref_id: str, payload: dict[str, Any]):
    from agent_core.vault.persist import rotate

    return _handle_write(rotate, ref_id, str(payload.get("secret") or ""))


@app.get("/mcp/keys")
def list_mcp_keys_api():
    from agent_core.mcp_http.auth import list_keys

    return list_keys()


@app.post("/mcp/keys")
def mint_mcp_key_api(payload: dict[str, Any]):
    from agent_core.mcp_http.auth import mint_key

    scopes = payload.get("scopes") or []
    if not isinstance(scopes, list):
        raise HTTPException(status_code=422, detail="scopes_must_be_list")
    return _handle_write(mint_key, name=str(payload.get("name") or "key"), scopes=scopes)


@app.post("/mcp/keys/{key_id}/rotate")
def rotate_mcp_key_api(key_id: str):
    from agent_core.mcp_http.auth import rotate_key

    return _handle_write(rotate_key, key_id)


@app.post("/mcp/keys/{key_id}/revoke")
def revoke_mcp_key_api(key_id: str):
    from agent_core.mcp_http.auth import revoke_key

    _handle_write(revoke_key, key_id)
    return {"ok": True}


@app.get("/mcp/tasks")
def list_mcp_tasks_api(status: str | None = None):
    from agent_core.mcp_http.tasks import list_tasks

    return list_tasks(status=status)


@app.get("/mcp/tasks/{task_id}")
def get_mcp_task_api(task_id: str):
    from agent_core.mcp_http.tasks import get_task

    row = get_task(task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="mcp_task_not_found")
    return row


@app.get("/mcp/status")
def mcp_status_api():
    from agent_core.platform_flags import mcp_apps_enabled, mcp_http_enabled, mcp_tasks_enabled

    host = (os.getenv("MCP_HTTP_HOST") or "127.0.0.1").strip()
    port = os.getenv("MCP_HTTP_PORT") or "8081"
    return {
        "stdioCommand": "python -m mcp_server",
        "httpEnabled": mcp_http_enabled(),
        "httpUrl": f"http://{host}:{port}/mcp",
        "tasksEnabled": mcp_tasks_enabled(),
        "appsEnabled": mcp_apps_enabled(),
        "mtls": bool((os.getenv("MCP_TLS_CAFILE") or "").strip()),
        "resources": [
            "customer://{id}",
            "account://{id}/ledger",
            "kb://snapshot/{id}",
            "interaction://{id}/trace",
            "policy://authority-matrix",
        ],
    }


@app.get("/gateway/status")
def gateway_status_api():
    from agent_core.platform_flags import llm_gateway_enabled
    from llm_gateway import canary as gw_canary
    from llm_gateway.client import PROFILES, base_url, cap_inr

    profiles = {}
    for p in PROFILES:
        env_model = os.getenv(f"LLM_GATEWAY_{p.upper()}_MODEL")
        override = None
        try:
            override = gw_canary.model_for(p)
        except Exception:
            override = None
        profiles[p] = {
            "capInr": cap_inr(p),
            "model": override or env_model,
            "envModel": env_model,
            "canaryModel": override,
        }
    return {
        "enabled": llm_gateway_enabled(),
        "baseUrl": base_url() or None,
        "profiles": profiles,
        "canary": gw_canary.current(),
        "killSwitch": "azure_openai" if not llm_gateway_enabled() else None,
        "voiceSloMs": 800,
    }


@app.get("/.well-known/agent-card.json")
def a2a_well_known_card(request: Request, botId: str | None = Query(default=None)):
    from agent_core import a2a as a2a_mod

    try:
        a2a_mod.require_partner({k.lower(): v for k, v in request.headers.items()})
        return a2a_mod.agent_card_document(botId or db.DEFAULT_BOT_ID)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/a2a")
def a2a_protocol_task(request: Request, payload: dict[str, Any]):
    from agent_core import a2a as a2a_mod

    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        partner = a2a_mod.require_partner(headers)
        dn = a2a_mod.client_cert_dn(headers)
        inner = payload.get("input") if isinstance(payload.get("input"), dict) else {}
        if payload.get("inputRequired") and "inputRequired" not in inner:
            inner = {**inner, "inputRequired": True}
        return a2a_mod.create_task(
            partner=partner,
            skill_id=str(payload.get("skillId") or payload.get("skill_id") or ""),
            payload=inner or payload,
            bot_id=str(payload.get("botId") or payload.get("bot_id") or db.DEFAULT_BOT_ID),
            cert_dn=dn,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/a2a/partners")
def list_a2a_partners():
    from agent_core import a2a as a2a_mod

    return a2a_mod.list_partners()


@app.post("/a2a/partners")
def upsert_a2a_partner(payload: dict[str, Any]):
    from agent_core import a2a as a2a_mod

    return _handle_write(a2a_mod.upsert_partner, payload)


@app.get("/a2a/tasks")
def list_a2a_tasks(limit: int = Query(default=50, ge=1, le=200)):
    from agent_core import a2a as a2a_mod

    return a2a_mod.list_tasks(limit=limit)


@app.post("/a2a/tasks/{task_id}/signal")
def signal_a2a_task(task_id: str, payload: dict[str, Any] | None = None):
    from agent_core import a2a as a2a_mod

    name = str((payload or {}).get("name") or "approve")
    return _handle_write(a2a_mod.signal_task, task_id, name)


@app.get("/compliance/policy-export")
def export_policy_bundle(fmt: str = Query(default="opa")):
    from agent_core.policy_export import bundle

    try:
        return bundle(fmt=fmt)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/eval/suites/{suite_id}/run")
def run_eval_suite(suite_id: str, botId: str | None = Query(default=None)):
    """Run a suite. ``botId`` files the report against the card that launched it.

    Without it the report falls back to ``bot_id_for_suite``, which guesses from
    the suite name — so a run started from a cloned card's Evals tab was filed
    under kaia-v2-4 (or nothing), the tab kept reading "never run", and G7/G8
    could never find a report for that card.
    """
    from agent_core.eval.run import run_named_suite

    try:
        return run_named_suite(suite_id, origin="manual", bot_id=botId or None)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/eval/suites")
def list_eval_suites(kind: str | None = Query(default=None)):
    return db.list_eval_suites(kind=kind)


@app.get("/eval/reports")
def list_eval_reports(
    kind: str | None = Query(default=None),
    botId: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Eval history. botId scopes it to one card — the Studio's Evals tab needs
    this card's runs, not the whole tenant's."""
    return db.list_eval_reports(kind=kind, bot_id=botId, limit=limit)


@app.get("/eval/reports/{report_id}")
def get_eval_report(report_id: str):
    from sqlalchemy import text as _text

    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(_text("SELECT * FROM eval_reports WHERE id = :id"), {"id": report_id})
        )
    if row is None:
        raise HTTPException(status_code=404, detail="eval_report_not_found")
    return dict(row)


@app.post("/eval/schedule/run")
def run_eval_schedule():
    from agent_core.eval.schedule import run_continuous

    try:
        return run_continuous()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/eval/tasks/{task_id}/graduate")
def graduate_eval_task(task_id: str):
    from agent_core.eval.graduate import graduate_task

    try:
        return graduate_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/eval/critiques")
def list_skill_critiques(limit: int = Query(default=50, ge=1, le=200)):
    from agent_core.eval.critique import list_critiques

    return list_critiques(limit=limit)


@app.post("/eval/reports/{report_id}/critique")
def critique_eval_report(report_id: str):
    from agent_core.eval.critique import critique_from_report

    try:
        return critique_from_report(report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/eval/disagreements")
def list_qa_disagreements(limit: int = Query(default=50, ge=1, le=200)):
    from agent_core.eval.disagreement import disagreements

    return disagreements(limit=limit)


@app.get("/eval/twin-corpus")
def list_twin_corpus(limit: int = Query(default=50, ge=1, le=200)):
    from agent_core.eval.corpus import list_corpus

    return list_corpus(limit=limit)


@app.post("/eval/twin-corpus/grow")
def grow_twin_corpus(limit: int = Query(default=20, ge=1, le=100)):
    from agent_core.eval.corpus import grow_from_kept_promises

    try:
        return grow_from_kept_promises(limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/gateway/canary")
def get_gateway_canary():
    from llm_gateway import canary as gw_canary

    return {"current": gw_canary.current(), "history": gw_canary.list_canaries()}


@app.post("/gateway/canary")
def propose_gateway_canary(payload: dict[str, Any]):
    from llm_gateway import canary as gw_canary

    try:
        return gw_canary.propose(
            str(payload.get("candidateModel") or payload.get("candidate_model") or ""),
            skip_redteam=bool(payload.get("skipRedteam") or payload.get("skip_redteam")),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/gateway/canary/{canary_id}/promote")
def promote_gateway_canary(canary_id: str, payload: dict[str, Any] | None = None):
    from llm_gateway import canary as gw_canary

    body = payload or {}
    try:
        return gw_canary.promote(
            canary_id,
            skip_redteam=bool(body.get("skipRedteam") or body.get("skip_redteam")),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/roles")
def list_roles_catalog():
    """Roles page. Grants are writable via PATCH."""
    from sqlalchemy import text as _text

    catalog = [
        {"id": pid, "module": module, "action": action, "description": description}
        for pid, module, action, description in authz.PERMISSION_CATALOG
    ]
    with db.engine.connect() as conn:
        roles = db._rows(
            conn.execute(
                _text("SELECT id, name FROM roles WHERE tenant_id = :t ORDER BY name"),
                {"t": db.current_tenant()},
            )
        )
        grants = db._rows(
            conn.execute(
                _text(
                    """
                    SELECT r.id AS role_id, r.name AS role, rp.permission_id
                    FROM role_permissions rp
                    JOIN roles r ON r.id = rp.role_id
                    WHERE r.tenant_id = :t
                    ORDER BY r.name, rp.permission_id
                    """
                ),
                {"t": db.current_tenant()},
            )
        )
    by_role: dict[str, list[str]] = {}
    for g in grants:
        by_role.setdefault(g["role_id"], []).append(g["permission_id"])
    publishers = sorted({g["role"] for g in grants if g["permission_id"] == authz.AGENT_PUBLISH})
    return {
        "permissions": catalog,
        "agentPublishRoles": publishers,
        "grants": grants,
        "roles": [
            {"id": r["id"], "name": r["name"], "permissionIds": by_role.get(r["id"], [])}
            for r in roles
        ],
    }


@app.patch("/roles/{role_id}/permissions")
def patch_role_permissions(role_id: str, payload: dict[str, Any]):
    ids = payload.get("permissionIds") or payload.get("permission_ids") or []
    if not isinstance(ids, list):
        raise HTTPException(status_code=422, detail="permission_ids_required")
    return _handle_write(db.replace_role_permissions, role_id, [str(x) for x in ids])


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
    providerId: str | None = Query(default=None),
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
        provider_id=providerId,
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
    """TTS preview. Azure keeps its cached path; other vendors dispatch out.

    The catalog is multi-vendor now, so a preview request can name a
    Cartesia, Deepgram or OpenRouter voice. Those used to fall through to
    Azure resolution and surface an Azure error for a voice that was never
    Azure's — a picker that lists a voice it cannot play.

    Azure stays inline rather than moving into provider_tts because this
    path also carries the synthesis cache and the removed-voice fallback,
    neither of which the other providers have.
    """
    import azure_speech

    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text_required")
    if len(text) > 500:
        text = text[:500].rstrip() + "…"

    short = (payload.shortName or payload.azureVoiceName or "").strip()

    if short:
        import provider_tts

        provider = provider_tts.provider_for_voice(short)
        if provider != "azure":
            try:
                audio, mime, meta = provider_tts.synthesize(
                    short_name=short,
                    text_body=text,
                    # `params` last: a model-declared `speed` is the control the
                    # operator actually turned, and it must win over the
                    # Azure-shaped `speed` field that every request carries a
                    # default for.
                    params={"speed": payload.speed, **(payload.params or {})},
                    force_fresh=payload.fresh,
                )
            except provider_tts.PreviewUnavailable as exc:
                # 422 not 500: the request was well formed, this voice just
                # cannot be auditioned right now (no key, quota, vendor 4xx).
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return Response(
                content=audio,
                media_type=mime,
                headers={
                    "X-Tts-Provider": str(meta["provider"]),
                    "X-Tts-Voice": str(meta["voiceName"]),
                    "X-Tts-Latency-Ms": str(meta["latencyMs"]),
                    # Was the literal "miss" — there was no cache on this path
                    # at all, so the header was accurate and useless. Same
                    # HIT/MISS casing as the Azure branch below, because the
                    # client reads one header for both.
                    "X-Tts-Cache": "HIT" if meta["cacheHit"] else "MISS",
                },
            )
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
            force_fresh=payload.fresh,
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
    botId: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """Runtime deployments — authoritative for what runs (Sandbox / live)."""
    return db.list_bot_deployments(
        environment=environment, status=status, bot_id=botId, limit=limit, offset=offset
    )


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


@app.get("/bot-deployments/experiments")
def list_deployment_experiments(botId: str | None = Query(default=None)):
    from agent_core.canary import list_experiments

    return list_experiments(bot_id=botId)


@app.post("/bot-deployments/experiments/{experiment_id}/rollback")
def rollback_deployment_experiment(experiment_id: str, payload: dict[str, Any] | None = None):
    from agent_core.canary import rollback_experiment

    reason = str((payload or {}).get("reason") or "manual")
    try:
        return rollback_experiment(experiment_id, reason=reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
    An authored conversation graph with validation errors returns 422
    ``flow_invalid`` — drafts stay savable; publish is the compiler.
    """
    try:
        return db.publish_prompt_version(
            version_id,
            payload.summary,
            kb_snapshot_id=payload.kbSnapshotId,
            tuning=payload.tuning,
            traffic_pct=payload.trafficPct,
            shadow=payload.shadow,
            auto_rollback=payload.autoRollback,
        )
    except flow_graph.FlowInvalidError as exc:
        raise HTTPException(status_code=422, detail=exc.http_detail()) from exc
    except CompileError as exc:
        raise HTTPException(status_code=exc.report.http_status(), detail=exc.http_detail()) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        logger.warning("write rejected by a database constraint: %s", exc.orig)
        raise HTTPException(status_code=409, detail="constraint_violation") from exc


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

    Returns two figures. ``tokens`` is the authored text, which is what the
    editor shows a character count for. ``assembledTokens`` is the whole system
    message as the runtime builds it — authored prompt, generated guardrail
    rules, persona directions, tenant-local time and (on voice) the naturalness
    overlay — and is only present when the caller supplies guardrails, since
    without them the assembly would be a guess wearing the clothes of a
    measurement.

    The second figure is the one that bills. It is re-sent on every LLM call,
    2-3x per turn through Flows, so a card whose authored prompt is 100 tokens
    can be paying for 800.

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

    def _cost(count: int) -> float:
        return round(count * usd_per_1m / 1_000_000.0, 6)

    assembled_tokens: int | None = None
    if payload.guardrails is not None:
        # Assemble with the real builders rather than re-implementing the
        # concatenation here or in the browser. The generated sections are
        # several times the size of the authored text and they change whenever
        # a guardrail is toggled or the naturalness overlay is edited; a second
        # copy of that arithmetic would be wrong within a week.
        from agent_core.prompt import build_system_prompt, default_context
        from prompt_render import render_system_prompt, strip_unrendered_crm_tokens

        persona = payload.persona.model_dump() if payload.persona is not None else {}
        guardrails = payload.guardrails.model_dump()
        ctx = default_context({"language": persona["language"]} if persona else None)
        # Same two steps the runtimes take, so the count reflects the CRM lines
        # that get deleted rather than the ones that were typed.
        rendered = strip_unrendered_crm_tokens(render_system_prompt(text, ctx))
        if payload.channel == "voice":
            from voice.natural import build_voice_system_prompt

            assembled = build_voice_system_prompt(rendered, guardrails, persona=persona or None)
        else:
            assembled = build_system_prompt(
                rendered_prompt=rendered,
                persona=persona,
                guardrails=guardrails,
                context_blocks=[],
                channel="whatsapp",
            )
        assembled_tokens = count_tokens(assembled)

    return {
        "tokens": tokens,
        "encoding": "cl100k_base",
        "usdPer1M": usd_per_1m,
        "costUsd": _cost(tokens),
        "source": "tiktoken",
        "assembledTokens": assembled_tokens,
        "assembledCostUsd": None if assembled_tokens is None else _cost(assembled_tokens),
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

    import outbound

    def _apply() -> dict[str, Any] | None:
        with db.engine.begin() as conn:
            return outbound.apply_provider_status(
                conn,
                provider_call_id=call_sid,
                status=status,
                duration_sec=duration,
                error_code=error_code,
                answered_by=answered_by,
            )

    try:
        row = await asyncio.to_thread(_apply)
    except Exception:
        # A 500 here makes Twilio retry, which is the right behaviour for a
        # transient database blip and the reason this is not swallowed silently.
        logger.exception("call-status: attempt update failed sid=%s", call_sid)
        raise HTTPException(status_code=500, detail="attempt_update_failed")

    if row is None:
        # Inbound, or a call placed before this table existed. Not an error.
        logger.debug("call-status for unknown attempt sid=%s", call_sid)
    return Response(status_code=204)


@app.post("/twilio/sms/status")
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

    with db.engine.begin() as conn:
        origin = conn.execute(
            text(
                """
                SELECT tenant_id, customer_id, related_id
                FROM contact_delivery_events
                WHERE provider = 'twilio' AND provider_ref = :sid
                ORDER BY occurred_at ASC
                LIMIT 1
                """
            ),
            {"sid": sid},
        ).mappings().first()
        if origin is None:
            logger.info("twilio sms status for unknown sid=%s state=%s", sid, state)
            return Response(status_code=204)
        delivery_receipts.record(
            conn,
            tenant_id=str(origin["tenant_id"]),
            customer_id=str(origin["customer_id"]),
            channel="sms",
            provider="twilio",
            provider_ref=sid,
            related_id=origin["related_id"],
            state=state,
            reason=str(form.get("ErrorCode") or "") or None,
        )
    return Response(status_code=204)


@app.post("/twilio/voice/outbound")
async def twilio_voice_outbound(payload: dict[str, Any]):
    """Start an outbound PSTN call that connects into the same Media Stream bot.

    The order here is the design's, not a convenience: the attempt row is
    written and committed **before** the contact gate runs, so a refusal has
    something to attach to. That is what turns the eleven ``contact_policy``
    denial reasons into a queryable denial rate instead of a log line, and it
    is the record that answers "why did nobody call this borrower on Tuesday".
    """
    from voice import twilio_ops

    if not twilio_ops.configured():
        raise HTTPException(status_code=503, detail="twilio_not_configured")
    to = str(payload.get("to") or payload.get("phone") or "").strip()
    if not to:
        raise HTTPException(status_code=400, detail="to_required")
    customer_id = str(payload.get("customerId") or payload.get("customer_id") or "").strip()
    objective = str(payload.get("objective") or "manual_outbound").strip() or "manual_outbound"
    account_id = str(payload.get("accountId") or payload.get("account_id") or "").strip() or None

    import contact_policy
    import mission as mission_mod
    import outbound

    attempt: dict[str, Any] | None = None
    with db.engine.begin() as conn:
        if customer_id:
            bot_id = str(payload.get("botId") or db.DEFAULT_BOT_ID)
            built = mission_mod.build(
                conn,
                customer_id=customer_id,
                objective=objective,
                account_id=account_id,
                card=mission_mod.card_for_bot(bot_id),
                bot_id=bot_id,
            )
            attempt = outbound.reserve(
                conn,
                customer_id=customer_id,
                to_phone=to,
                objective=objective,
                account_id=account_id,
                bot_id=bot_id,
                context={"source": "manual_endpoint", "mission": built},
            )
        decision = contact_policy.admit(
            conn,
            customer_id=customer_id or None,
            channel="voice",
            purpose="outreach",
            session_key=customer_id or to,
            source="voice_outbound",
            related_id=attempt["id"] if attempt else to,
            actor_kind="human",
        )
        if not decision.allowed and attempt:
            outbound.suppress(conn, attempt["id"], decision.reason or "contact_policy")
    if not decision.allowed:
        raise HTTPException(status_code=409, detail=decision.reason or "contact_policy")

    custom = {
        k: str(v)
        for k, v in (payload.get("custom") or {}).items()
        if v is not None
    }
    if customer_id:
        custom["customer_id"] = customer_id

    # An ad-hoc dial to a bare number with no customer on file keeps the old
    # path: there is no borrower to attribute an attempt to, and inventing a
    # customer row to satisfy a foreign key would be worse than the gap.
    if attempt is None:
        try:
            return twilio_ops.start_outbound_call(to=to, custom=custom or None)
        except Exception as exc:
            logger.exception("Twilio outbound failed")
            raise HTTPException(status_code=502, detail="twilio_outbound_failed") from exc

    result = await asyncio.to_thread(
        outbound.place, db.engine, attempt, to_phone=to, custom=custom or None
    )
    if not result.get("placed"):
        reason = result.get("reason") or "dial_failed"
        raise HTTPException(
            status_code=503 if reason == "fleet_busy" else 502, detail=reason
        )
    return result


@app.get("/platform/switches")
def list_platform_switches():
    """Operator-flippable runtime switches and their current state.

    Every known switch is returned whether or not a row exists for it, because
    "no row" is a real state — off — and a screen that showed nothing until
    somebody flipped something would be lying about the default.
    """
    import platform_switches

    with db.engine.connect() as conn:
        return {"switches": platform_switches.get_all(conn)}


@app.patch("/platform/switches/{key}")
def patch_platform_switch(key: str, payload: dict[str, Any]):
    import platform_switches

    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail="enabled_must_be_boolean")
    note = payload.get("note")
    note = str(note).strip()[:200] if note else None
    try:
        with db.engine.begin() as conn:
            result = platform_switches.set_enabled(conn, key, enabled, note=note)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown_switch") from None
    logger.warning(
        "platform switch %s set to %s by %s", key, enabled, db._actor_user_id()
    )
    return result


#: The number the demo dials. A constant, not a request parameter: this button
#: exists so a rehearsed demo is one click, and an endpoint that accepts an
#: arbitrary number is a dialer, not a demo. Ad-hoc dialling already has a home
#: at POST /twilio/voice/outbound, behind the same switch.
DEMO_OUTBOUND_PHONE_DEFAULT = "919655282324"


def _demo_waivable_reasons() -> frozenset[str]:
    """Contact-policy refusals the demo switch may override.

    Every one is a rule about *timing or frequency* — when a borrower may be
    called and how often. None of them is a rule about whether the borrower
    consented to be called at all; those stay in force whatever the switch says,
    which is the line this set exists to draw.
    """
    import contact_policy

    return frozenset(
        {
            contact_policy.REASON_HOURS,    # statutory calling hours
            contact_policy.REASON_WINDOW,   # the borrower's narrower preference
            contact_policy.REASON_COOLING,  # gap between consecutive contacts
            contact_policy.REASON_DAILY,    # touches per day
            contact_policy.REASON_WEEKLY,   # touches per week
        }
    )


_DEMO_WAIVABLE_REASONS = _demo_waivable_reasons()


def _demo_outbound_phone() -> str:
    return (os.getenv("DEMO_OUTBOUND_PHONE") or DEMO_OUTBOUND_PHONE_DEFAULT).strip()


def _demo_outbound_bot_id() -> str:
    """The card that will speak, not always the tenant default."""
    import mission as mission_mod

    return mission_mod.resolve_outbound_bot_id(
        explicit=(os.getenv("DEMO_OUTBOUND_BOT_ID") or "").strip() or None,
        objective=(
            os.getenv("DEMO_OUTBOUND_OBJECTIVE") or DEMO_OUTBOUND_OBJECTIVE_DEFAULT
        ).strip(),
    )


#: The objective the demo runs under. It must be one the *card* declares, not a
#: label invented here: `entry_node`, the success criteria, the duration budget,
#: the voicemail policy and the cadence all come from the card's objective spec,
#: and `OBJECTIVE_BRIEF` — the paragraph telling the agent what this call is for
#: — is keyed by it. An unrecognised objective silently yields an empty brief
#: and no spec, which is a materially worse call that still connects.
DEMO_OUTBOUND_OBJECTIVE_DEFAULT = "dpd_reminder"


def _demo_outbound_objective(card: Any) -> str:
    """The demo objective, validated against the card that will run it."""
    wanted = (
        os.getenv("DEMO_OUTBOUND_OBJECTIVE") or DEMO_OUTBOUND_OBJECTIVE_DEFAULT
    ).strip()
    declared = [
        str(getattr(o, "key", "")) for o in (getattr(getattr(card, "outbound", None), "objectives", None) or [])
    ]
    if wanted in declared:
        return wanted
    if declared:
        logger.warning(
            "demo objective %r is not declared by the card (has %s) — using %s",
            wanted,
            declared,
            declared[0],
        )
        return declared[0]
    return wanted


@app.get("/demo/outbound-call")
def demo_outbound_target():
    """Who the demo button will call, and whether it can right now.

    The screen needs to say this *before* the click. "Dial and find out" is a
    poor design for a control whose side effect is a real phone ringing in
    somebody's hand.
    """
    import platform_switches
    from voice import twilio_ops

    phone = _demo_outbound_phone()
    digits = "".join(ch for ch in phone if ch.isdigit())
    customer: dict[str, Any] | None = None
    with db.engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, name, phone_primary, dnd
                FROM customers
                WHERE tenant_id = :t
                  AND regexp_replace(COALESCE(phone_primary, ''), '\\D', '', 'g') = :d
                LIMIT 1
                """
            ),
            {"t": db._tenant(), "d": digits},
        ).mappings().first()
        if row:
            customer = {
                "id": row["id"],
                "name": row["name"],
                "phone": row["phone_primary"],
                "dnd": bool(row["dnd"]),
            }
    # What the call will actually be authorised to do. `allowed_offers` is empty
    # on every objective this card declares, and `mission.build` turns that into
    # an explicit "do NOT mention any product, offer, top-up or upgrade" line in
    # the brief. Saying so here is the difference between a demo that surprises
    # the person running it and one that does not: whoever clicks this deserves
    # to know upsell is off *before* they promise a customer they will see it.
    import mission as mission_mod

    objective = ""
    offers_allowed = False
    try:
        card = mission_mod.card_for_bot(_demo_outbound_bot_id())
        objective = _demo_outbound_objective(card)
        for spec in getattr(getattr(card, "outbound", None), "objectives", None) or []:
            if str(getattr(spec, "key", "")) == objective:
                offers_allowed = bool(getattr(spec, "allowed_offers", None))
                break
    except Exception:
        logger.exception("demo target: could not resolve the objective")

    # Whether the call would be permitted *right now*, using the dry-run
    # evaluator so asking the question costs the borrower nothing — `admit`
    # increments the daily counter, `evaluate` does not.
    policy_reason: str | None = None
    #: Set when the waiver is what makes the call possible, so the screen can say
    #: "we are overriding this" rather than silently showing all-clear.
    policy_waived: str | None = None
    if customer:
        try:
            import contact_policy

            with db.engine.connect() as conn:
                verdict = contact_policy.evaluate(
                    conn, customer_id=customer["id"], channel="voice", purpose="outreach"
                )
            policy_reason = None if verdict.allowed else (verdict.reason or "contact_policy")
            # Report what the *button* will do, not what the raw engine said.
            # The POST applies the demo waiver, so a screen that showed the
            # unwaived refusal would tell the operator they are blocked and then
            # place the call anyway — the same class of confident-but-wrong
            # state this product keeps getting caught by.
            if (
                policy_reason in _DEMO_WAIVABLE_REASONS
                and platform_switches.demo_ignores_window()
            ):
                policy_waived = policy_reason
                policy_reason = None
        except Exception:
            logger.exception("demo target: contact policy dry-run failed")

    return {
        "phone": phone,
        "customer": customer,
        "objective": objective,
        "offersAllowed": offers_allowed,
        "outboundEnabled": platform_switches.outbound_enabled(),
        "demoIgnoresWindow": platform_switches.demo_ignores_window(),
        "policyReason": policy_reason,
        "policyWaived": policy_waived,
        "twilioConfigured": twilio_ops.configured(),
    }


@app.post("/demo/outbound-call")
async def demo_outbound_call():
    """Place the demo call: one number, the full mission, every real gate.

    Deliberately *not* a shortcut around the pipeline. It builds a mission from
    the live agent card, reserves an attempt, runs `contact_policy` and honours
    the outbound switch — so what the customer watches is the product, not a
    demo harness that resembles it. The compliance refusals are part of the
    demo: a call declined at 21:00 because the statutory window closed is a
    better thing to show than one that goes through.
    """
    import contact_policy
    import mission as mission_mod
    import outbound
    import platform_switches
    from voice import twilio_ops

    if not platform_switches.outbound_enabled():
        raise HTTPException(status_code=409, detail="outbound_disabled")
    if not twilio_ops.configured():
        raise HTTPException(status_code=503, detail="twilio_not_configured")

    phone = _demo_outbound_phone()
    digits = "".join(ch for ch in phone if ch.isdigit())

    with db.engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT id FROM customers
                WHERE tenant_id = :t
                  AND regexp_replace(COALESCE(phone_primary, ''), '\\D', '', 'g') = :d
                LIMIT 1
                """
            ),
            {"t": db._tenant(), "d": digits},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="demo_customer_not_found")
        customer_id = str(row["id"])
        account_id = conn.execute(
            text(
                "SELECT id FROM accounts WHERE customer_id = :c"
                " ORDER BY CASE WHEN id LIKE 'AC-%' THEN 0 ELSE 1 END, created_at, id LIMIT 1"
            ),
            {"c": customer_id},
        ).scalar()

        bot_id = _demo_outbound_bot_id()
        card = mission_mod.card_for_bot(bot_id)
        objective = _demo_outbound_objective(card)
        built = mission_mod.build(
            conn,
            customer_id=customer_id,
            objective=objective,
            account_id=account_id,
            card=card,
            bot_id=bot_id,
        )
        attempt = outbound.reserve(
            conn,
            customer_id=customer_id,
            to_phone=phone,
            objective=objective,
            account_id=account_id,
            bot_id=bot_id,
            context={"source": "demo_button", "mission": built},
        )
        decision = contact_policy.admit(
            conn,
            customer_id=customer_id,
            channel="voice",
            purpose="outreach",
            session_key=customer_id,
            source="voice_outbound",
            related_id=attempt["id"] if attempt else phone,
            actor_kind="human",
        )
        # The one override, and its limits.
        #
        # Waivable: *when* and *how often*. The calling hours, the borrower's
        # preferred window, the cooling-off gap and the daily and weekly caps
        # all exist to stop a borrower being rung repeatedly. The demo endpoint
        # takes no phone number — it dials one configured handset, the one the
        # operator running the demo is holding — so rehearsing on it is not the
        # harm any of those rules were written to prevent. Hitting `cooling_off`
        # after three rehearsal calls to your own phone is the rule working
        # correctly on the wrong subject.
        #
        # Not waivable, at any switch setting: consent, opt-out, DND, the
        # registry and the DPDP promotional-purpose basis. Those answer "may we
        # contact this person at all", which a demo does not get to re-answer —
        # and they are not what is blocking anyone here, so waiving them would
        # buy nothing and cost the one guarantee worth keeping.
        reason = decision.reason or "contact_policy"
        waivable_for_demo = reason in _DEMO_WAIVABLE_REASONS
        waived = (
            not decision.allowed
            and waivable_for_demo
            and platform_switches.demo_ignores_window()
        )
        if waived:
            logger.warning(
                "demo call: waiving %s for the demo number by operator switch", reason
            )
            db.record_activity(
                conn,
                "customer",
                customer_id,
                "demo_window_waived",
                f"Demo call placed despite {reason}",
                f"waived:{reason}",
                customer_id,
            )
        elif not decision.allowed and attempt:
            outbound.suppress(conn, attempt["id"], reason)

    if not decision.allowed and not waived:
        # 409 with the engine's own reason. `outside_allowed_window` here is the
        # calling window doing its job, not a bug in the button.
        raise HTTPException(status_code=409, detail=reason)

    result = await asyncio.to_thread(
        outbound.place,
        db.engine,
        attempt,
        to_phone=phone,
        custom={"customer_id": customer_id, "demo": "1"},
    )
    if not result.get("placed"):
        reason = result.get("reason") or "dial_failed"
        raise HTTPException(
            status_code=503 if reason in {"fleet_busy", "outbound_disabled"} else 502,
            detail=reason,
        )
    return {
        "placed": True,
        "customerId": customer_id,
        "phone": phone,
        "attemptId": result.get("attemptId"),
        "callSid": result.get("callSid"),
    }


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
    from voice.call_trace import event
    from voice.host import embedded_host_enabled, run_websocket_session
    from voice.ws_proxy import proxy_voice_websocket, ws_proxy_enabled

    # First line of the socket's story. Without it, "Twilio never connected" and
    # "we refused Twilio" are the same absence of a log line — and they were,
    # for two answered calls that played silence.
    peer = getattr(getattr(websocket, "client", None), "host", None)
    event(
        "ws.arrived",
        peer=peer,
        secret="path" if path_secret else "header-or-query",
    )

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
def kb_list_documents(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_kb_documents(limit=limit, offset=offset)


@app.get("/kb/documents/{document_id}", response_model=KbDocumentResponse)
def kb_get_document(document_id: str):
    doc = db.get_kb_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="kb_document_not_found")
    return doc


@app.get("/kb/documents/{document_id}/chunks", response_model=list[KbChunkResponse])
def kb_list_chunks(
    document_id: str,
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    if not db.get_kb_document(document_id):
        raise HTTPException(status_code=404, detail="kb_document_not_found")
    return db.list_kb_chunks(document_id, limit=limit, offset=offset)


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
def kb_list_faqs(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_kb_faqs(limit=limit, offset=offset)


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


# ---------------------------------------------------------------------------
# Next-best-treatment (P3)
# ---------------------------------------------------------------------------


@app.get("/treatment/next")
def treatment_next(
    customerId: str = Query(...),
    accountId: str | None = Query(default=None),
    trigger: str = Query(default="manual"),
):
    """What should happen to this account next, and when.

    Safe to call from a screen: outside ``TREATMENT_MODE=live`` the engine
    decides, logs and enacts nothing. The decision row is written either way —
    a supervisor asking "what would you do here?" is exactly the kind of
    question the shadow corpus should be built from.
    """
    return _handle_write(
        db.next_treatment, customer_id=customerId, account_id=accountId, trigger=trigger
    )


@app.get("/treatment/insights")
def treatment_insights(days: int = Query(default=14, ge=1, le=90)):
    """Coverage, suppression breakdown and action mix over a window.

    The report the roadmap's exit criterion is written against: two weeks of
    shadow logs with a suppression breakdown before any live auto-act.
    """
    return db.treatment_insights(days)


@app.get("/treatment/metrics")
def treatment_metrics(
    days: int = Query(default=28, ge=1, le=180),
    includeSimulated: bool = Query(default=False),
):
    """Section 17 in full: is the engine working, and what is it costing?

    ``/treatment/insights`` says whether it is safe to switch on. This says
    whether switching it on paid, measured against the randomised control arm.
    Where an arm is too thin to support a causal figure the field says so
    rather than degrading to a collections rate -- which is the number a
    response model wins on, and therefore the number this endpoint exists not
    to report.
    """
    return db.treatment_metrics(days, include_simulated=includeSimulated)


@app.get("/treatment/model-health")
def treatment_model_health(
    days: int = Query(default=14, ge=1, le=180),
    includeSimulated: bool = Query(default=False),
):
    """Feature drift, reach calibration, and predicted tau against measured ATE."""
    return db.treatment_model_health(days, include_simulated=includeSimulated)


@app.get("/treatment/models")
def treatment_models(
    target: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """The champion/challenger ledger, and whether it matches what is serving."""
    return db.treatment_models(target, limit)


@app.get("/treatment/holds")
def list_treatment_holds(
    customerId: str | None = Query(default=None),
    activeOnly: bool = Query(default=True),
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_treatment_holds(
        customer_id=customerId, active_only=activeOnly, limit=limit, offset=offset
    )


@app.post("/treatment/holds")
def create_treatment_hold(payload: TreatmentHoldCreateRequest):
    """Stop collections outreach for this borrower.

    Not idempotency-keyed: re-placing an active hold returns the existing one.
    A bot that hears "I lost my job" twice in one call and an agent who clicks
    twice must both end with exactly one hold, and a 409 would leave the caller
    deciding what to do about it.
    """
    return _handle_write(db.create_treatment_hold, payload.model_dump(exclude_none=True))


@app.post("/treatment/holds/{hold_id}/release")
def release_treatment_hold(hold_id: str, payload: TreatmentHoldReleaseRequest | None = None):
    return _handle_write(
        db.release_treatment_hold,
        hold_id,
        payload.model_dump(exclude_none=True) if payload else None,
    )


@app.get("/treatment/cases")
def list_treatment_cases(
    customerId: str | None = Query(default=None),
    openOnly: bool = Query(default=True),
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """One row per case, with the ladder it has already walked.

    ``GET /treatment/next`` answers "what does the engine say?". A floor lead's
    actual question is "what has been tried on this account, and what is left",
    which is a different query.
    """
    return db.list_treatment_cases(
        customer_id=customerId, open_only=openOnly, limit=limit, offset=offset
    )


# ---------------------------------------------------------------------------
# Outbound — the reach numbers that did not exist before call_attempts
# ---------------------------------------------------------------------------


@app.get("/outbound/stats")
def outbound_stats(days: int = Query(default=14, ge=1, le=90)):
    """Answer rate, right-party rate, attempts per connect, denial rate.

    Every one of these was uncomputable until an unanswered dial started
    leaving a row: ``interactions`` is created when media connects, so the
    denominator of "how often do we reach the people we call" was never
    recorded anywhere.

    Suppressed attempts are reported beside the reach figures rather than
    inside them. A call the contact gate refused is not a call the borrower
    ignored, and folding the two together would make a compliant week look like
    an unreachable book.
    """
    import outbound

    with db.engine.connect() as conn:
        return outbound.reach_stats(conn, tenant_id=db.current_tenant(), days=days)


@app.get("/outbound/attempts")
def outbound_attempts(
    customerId: str | None = Query(default=None),
    state: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """The dial log, newest first — including the ones that never connected."""
    clauses = ["a.tenant_id = :tenant"]
    params: dict[str, Any] = {"tenant": db.current_tenant(), "limit": limit, "offset": offset}
    if customerId:
        clauses.append("a.customer_id = :cid")
        params["cid"] = customerId
    if state:
        clauses.append("a.state = :state")
        params["state"] = state
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT a.id, a.customer_id, c.name AS customer_name, a.objective,
                       a.attempt_no, a.state, a.suppressed_reason, a.to_phone_last4,
                       a.answered_by, a.right_party, a.ring_sec, a.talk_sec,
                       a.provider_call_id, a.provider_status, a.provider_error,
                       a.interaction_id, a.decision_id, a.reserved_at, a.placed_at,
                       a.answered_at, a.ended_at,
                       o.connection, o.business, o.objective_met, o.nonpayment_reason,
                       o.summary, o.summary_source
                FROM call_attempts a
                JOIN customers c ON c.id = a.customer_id
                LEFT JOIN call_outcomes o ON o.attempt_id = a.id
                WHERE {' AND '.join(clauses)}
                ORDER BY a.reserved_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
    return [dict(r) for r in rows]


@app.get("/outbound/reasons")
def outbound_reasons(days: int = Query(default=30, ge=1, le=180)):
    """Why the book is not paying, counted.

    The question the product could not answer at all: it could say an account
    was 45 DPD with two bounces and never that the borrower lost their job in
    June. ``forgot`` is the row to watch — it counts the calls that were worth
    less than a reminder.
    """
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT nonpayment_reason AS reason, count(*) AS calls,
                       count(*) FILTER (WHERE objective_met) AS resolved
                FROM call_outcomes
                WHERE tenant_id = :tenant
                  AND nonpayment_reason IS NOT NULL
                  AND created_at >= now() - make_interval(days => :days)
                GROUP BY 1 ORDER BY 2 DESC
                """
            ),
            {"tenant": db.current_tenant(), "days": days},
        ).mappings().all()
    return [dict(r) for r in rows]


@app.get("/customers/{customer_id}/outbound/hours")
def outbound_hourly(customer_id: str, days: int = Query(default=90, ge=1, le=365)):
    """Per-hour answer rate for one borrower, in their own local time.

    This is what ``treatment/features.responsive_hours`` should eventually read:
    unlike the connect-only version, it has a denominator.
    """
    import outbound

    with db.engine.connect() as conn:
        return outbound.hourly_reach(conn, customer_id=customer_id, days=days)


@app.get("/outbound/campaigns")
def list_campaign_runs(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=db.MAX_LIST_LIMIT),
):
    """Runs and how far through each one is."""
    clauses = ["r.tenant_id = :tenant"]
    params: dict[str, Any] = {"tenant": db.current_tenant(), "limit": limit}
    if status:
        clauses.append("r.status = :status")
        params["status"] = status
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT r.*,
                  (SELECT count(*) FROM campaign_targets t
                    WHERE t.run_id = r.id AND t.state = 'pending')  AS pending,
                  (SELECT count(*) FROM campaign_targets t
                    WHERE t.run_id = r.id AND t.state = 'done')     AS done,
                  (SELECT count(*) FROM campaign_targets t
                    WHERE t.run_id = r.id AND t.state = 'skipped')  AS skipped
                FROM campaign_runs r
                WHERE {' AND '.join(clauses)}
                ORDER BY r.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return [dict(r) for r in rows]


@app.post("/outbound/campaigns")
def create_campaign_run(payload: dict[str, Any]):
    """Create a run in ``draft``. Nothing dials until it is explicitly started.

    Draft-by-default is the point. A campaign is the one object in this system
    whose accidental creation rings real phones, so bringing it into existence
    and setting it going are two deliberate acts rather than one.
    """
    import campaigns

    name = str(payload.get("name") or "").strip()
    objective = str(payload.get("objective") or "").strip()
    if not name or not objective:
        raise HTTPException(status_code=400, detail="name_and_objective_required")
    import flow_graph as fg

    if objective not in fg.OBJECTIVES:
        raise HTTPException(status_code=400, detail="unknown_objective")

    with db.engine.begin() as conn:
        run = campaigns.create(
            conn,
            tenant_id=db.current_tenant(),
            name=name,
            objective=objective,
            bot_id=payload.get("botId"),
            cadence=str(payload.get("cadence") or "default"),
            source=str(payload.get("source") or "list"),
            selector=payload.get("selector") or {},
            window_start_hour=int(payload.get("windowStartHour") or 10),
            window_end_hour=int(payload.get("windowEndHour") or 18),
            max_concurrent=int(payload.get("maxConcurrent") or 5),
            created_by_user_id=db._actor_user_id(),
        )
        ids = [str(c) for c in (payload.get("customerIds") or []) if str(c).strip()]
        if ids:
            campaigns.add_targets(conn, run["id"], ids)
        # A selector on the payload is resolved now, against the book as it
        # stands, and the resulting targets are frozen onto the run. Re-resolving
        # at dial time would mean the cohort an operator reviewed and the cohort
        # that got called were different populations — which is precisely the
        # audit answer a campaign exists to be able to give.
        selector = payload.get("selector") or {}
        if selector:
            try:
                campaigns.add_targets_from_selector(
                    conn, run["id"], tenant_id=db.current_tenant(), selector=selector
                )
            except campaigns.SelectorError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
    return dict(run)


@app.post("/outbound/campaigns/preview")
def preview_campaign_cohort(payload: dict[str, Any]):
    """Who this selector would call, before a run exists.

    Deliberately reachable without a run id. A campaign is the one object here
    whose accidental creation rings real phones, so seeing the population has to
    be possible *before* committing to one — otherwise the only way to check a
    cohort is to create the thing you were checking.
    """
    import campaigns

    try:
        with db.engine.connect() as conn:
            return campaigns.preview_selector(
                conn,
                tenant_id=db.current_tenant(),
                selector=payload.get("selector") or {},
                sample=int(payload.get("sample") or 10),
            )
    except campaigns.SelectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/outbound/campaigns/{run_id}/targets")
def add_campaign_targets(run_id: str, payload: dict[str, Any]):
    import campaigns

    ids = [str(c) for c in (payload.get("customerIds") or []) if str(c).strip()]
    selector = payload.get("selector") or {}
    if not ids and not selector:
        raise HTTPException(status_code=400, detail="customer_ids_or_selector_required")
    try:
        with db.engine.begin() as conn:
            added = campaigns.add_targets(conn, run_id, ids) if ids else 0
            if selector:
                added += campaigns.add_targets_from_selector(
                    conn, run_id, tenant_id=db.current_tenant(), selector=selector
                )
    except campaigns.SelectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"runId": run_id, "added": added, "requested": len(ids)}


@app.post("/outbound/campaigns/{run_id}/status")
def set_campaign_status(run_id: str, payload: dict[str, Any]):
    """start / pause / finish / cancel.

    Pause takes effect on the next worker iteration and never mid-call: a call
    already in progress is a conversation with a person, and hanging up on them
    to honour a button is worse than letting it finish.
    """
    import campaigns

    status = str(payload.get("status") or "").strip()
    allowed = {
        campaigns.STATUS_RUNNING,
        campaigns.STATUS_PAUSED,
        campaigns.STATUS_FINISHED,
        campaigns.STATUS_CANCELLED,
    }
    if status not in allowed:
        raise HTTPException(status_code=400, detail="bad_status")
    if status == campaigns.STATUS_RUNNING and not campaigns.enabled():
        raise HTTPException(status_code=409, detail="campaign_runtime_disabled")
    if status == campaigns.STATUS_RUNNING:
        import platform_switches

        if not platform_switches.outbound_enabled():
            raise HTTPException(status_code=409, detail="outbound_disabled")
    with db.engine.begin() as conn:
        run = campaigns.set_status(conn, run_id, status)
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    return dict(run)


@app.get("/outbound/campaigns/{run_id}")
def get_campaign_run(run_id: str):
    import campaigns

    with db.engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM campaign_runs WHERE id = :id AND tenant_id = :t"),
            {"id": run_id, "t": db.current_tenant()},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        return {**dict(row), "progress": campaigns.progress(conn, run_id)}


@app.get("/outbound/cadence")
def list_cadence_cases(
    customerId: str | None = Query(default=None),
    state: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=db.MAX_LIST_LIMIT),
):
    """Open retry ladders — what is waiting, and what ran out of attempts."""
    clauses = ["s.tenant_id = :tenant"]
    params: dict[str, Any] = {"tenant": db.current_tenant(), "limit": limit}
    if customerId:
        clauses.append("s.customer_id = :cid")
        params["cid"] = customerId
    if state:
        clauses.append("s.state = :state")
        params["state"] = state
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT s.*, c.name AS customer_name
                FROM call_cadence_state s
                JOIN customers c ON c.id = s.customer_id
                WHERE {' AND '.join(clauses)}
                ORDER BY s.next_attempt_at ASC NULLS LAST, s.updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return [dict(r) for r in rows]


@app.get("/outbound/number-pools")
def list_number_pools():
    """Caller-ID pools and the numbers in them, with how each is performing."""
    with db.engine.connect() as conn:
        pools = conn.execute(
            text(
                "SELECT * FROM number_pools WHERE tenant_id = :t ORDER BY name"
            ),
            {"t": db.current_tenant()},
        ).mappings().all()
        numbers = conn.execute(
            text(
                """
                SELECT n.* FROM pool_numbers n
                JOIN number_pools p ON p.id = n.pool_id
                WHERE p.tenant_id = :t
                ORDER BY n.e164
                """
            ),
            {"t": db.current_tenant()},
        ).mappings().all()
    by_pool: dict[str, list[dict[str, Any]]] = {}
    for row in numbers:
        by_pool.setdefault(str(row["pool_id"]), []).append(dict(row))
    return [{**dict(p), "numbers": by_pool.get(str(p["id"]), [])} for p in pools]


@app.get("/outbound/obligations")
def list_agent_obligations(
    state: str = Query(default="open"),
    limit: int = Query(default=50, ge=1, le=db.MAX_LIST_LIMIT),
):
    """What the agent promised and whether we kept it.

    An agent that keeps its promises is the whole trust proposition of an
    automated collections line, and a missed obligation is a QA finding with a
    named owner rather than a thing nobody knew happened.
    """
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT o.*, c.name AS customer_name
                FROM agent_obligations o
                JOIN customers c ON c.id = o.customer_id
                WHERE o.tenant_id = :t AND (:state = 'all' OR o.state = :state)
                ORDER BY o.due_at ASC
                LIMIT :limit
                """
            ),
            {"t": db.current_tenant(), "state": state, "limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


@app.get("/outbound/card-vocabulary")
def outbound_card_vocabulary():
    """Every closed vocabulary the Outbound card editor has to offer.

    One endpoint rather than a constant per list in the frontend, and derived
    from the definitions the runtime and the compiler actually use rather than
    restated. That is not tidiness: ``card.outbound`` is validated by Pydantic
    models with ``extra="forbid"`` and gated by G-OB1..8, so an option the
    editor offers that the backend does not know is not a cosmetic mismatch —
    it builds a card that cannot be published, and the author finds out at the
    publish button with a validation error naming a field they picked from a
    dropdown.

    ``dailyCap`` is here for the same reason. G-OB3 fails a cadence planning
    more contacts per day than ``contact_policy`` permits; the editor can say so
    while the number is being typed instead of at compile time.
    """
    from typing import get_args

    import contact_policy
    import flow_graph as fg
    import mission as mission_mod
    import outbound as outbound_mod
    from agent_core.authority import config as authority_config
    from agent_core.cards import compile as compile_mod
    from agent_core.cards import schema as card_schema

    pools: list[dict[str, Any]] = []
    try:
        with db.engine.connect() as conn:
            pools = [
                {"name": str(r["name"]), "kind": str(r["kind"])}
                for r in conn.execute(
                    text(
                        "SELECT name, kind FROM number_pools "
                        "WHERE tenant_id = :t AND enabled IS TRUE ORDER BY name"
                    ),
                    {"t": db.current_tenant()},
                ).mappings()
            ]
    except Exception:
        # A tenant with no pools table yet still gets a usable editor; the pool
        # name is free text on the card and G-OB4 keys off `pool_kind`.
        logger.debug("number pool lookup failed", exc_info=True)

    return {
        "objectives": list(fg.OBJECTIVES),
        "objectiveBriefs": dict(mission_mod.OBJECTIVE_BRIEF),
        "directions": list(get_args(card_schema.Direction)),
        "voicemailModes": list(get_args(card_schema.VoicemailMode)),
        "timeOfDay": list(get_args(card_schema.TimeOfDay)),
        "poolKinds": list(get_args(card_schema.PoolKind)),
        "qaModes": ["always", "sampled", "never"],
        # The Closer's taxonomy — what `success` / `partial` / `stop_on` and a
        # post-call rule's `when` may name. G-OB6 rejects anything else.
        "outcomeCodes": sorted(compile_mod.OUTCOME_CODES),
        # Verbs the Closer implements. A rule may also name any tool on the
        # card, which is why G-OB6 checks the union rather than this alone.
        "postCallActions": sorted(compile_mod.POST_CALL_ACTIONS),
        # `retry_on` is matched against the attempt's connection outcome *and*
        # its state, so the offerable set is the states worth another dial.
        "retryStates": sorted(outbound_mod.RETRYABLE),
        "authorityProfiles": [
            {"name": name, "ceilingInr": authority_config.profile_ceilings().get(name)}
            for name in authority_config.profile_names()
        ],
        "numberPools": pools,
        "dailyCap": contact_policy.daily_cap(),
    }


@app.get("/outbound/missions")
def list_missions(botId: str | None = Query(default=None)):
    """The missions a card can run, and where each starts.

    Serves the Outbound tab. Two sources, deliberately both: what the *card*
    declares and what the *graph* claims. They disagreeing is the failure G-OB2
    exists to catch, and an author needs to see both halves to fix it.

    ``botId`` is not optional in spirit. This read the default bot and nothing
    else, while the tab that calls it lives inside a per-card editor and says
    "No missions on **this card**" — so opening Outbound on any other card
    reported the default bot's missions, direction and number pool under that
    card's name. It is invisible today only because no card declares an
    outbound block yet, which makes every card show the same empty state; the
    first card to declare one would have shown its missions on all of them.
    """
    import flow_graph as fg
    import mission as mission_mod

    bot_id = (botId or "").strip() or db.DEFAULT_BOT_ID
    card = mission_mod.card_for_bot(bot_id)
    graph_entries: dict[str, str] = {}
    try:
        version = None
        studio = db.get_agent_studio_card(bot_id) or {}
        draft_id = studio.get("draftVersionId")
        if draft_id:
            version = db.get_prompt_version(draft_id) or {}
        if not (version and version.get("flow")):
            deployment = db.get_active_deployment(bot_id=bot_id, environment="production")
            if deployment and deployment.get("promptVersionId"):
                version = db.get_prompt_version(deployment["promptVersionId"]) or {}
        if version:
            graph_entries = fg.parse_graph(version.get("flow") or {}).entry_objectives()
    except Exception:
        logger.debug("mission entry lookup failed", exc_info=True)

    outbound_cfg = getattr(card, "outbound", None) if card is not None else None
    declared = [
        {
            "key": o.key,
            "entryNode": o.entry_node,
            "graphEntryNode": graph_entries.get(o.key),
            "agrees": graph_entries.get(o.key) == o.entry_node,
            "maxDurationSec": o.max_duration_sec,
            "allowedOffers": o.allowed_offers,
            "authorityProfile": o.authority_profile,
            "cadence": o.cadence,
            "success": o.success,
            "brief": mission_mod.OBJECTIVE_BRIEF.get(o.key, ""),
        }
        for o in (outbound_cfg.objectives if outbound_cfg else [])
    ]
    return {
        "botId": bot_id,
        "direction": getattr(outbound_cfg, "direction", "inbound"),
        "poolKind": getattr(outbound_cfg, "pool_kind", "general"),
        "numberPool": getattr(outbound_cfg, "number_pool", None),
        "objectives": declared,
        "graphEntries": graph_entries,
        "available": list(fg.OBJECTIVES),
    }


# ---------------------------------------------------------------------------
# Live authority matrix (P4)
# ---------------------------------------------------------------------------


@app.get("/authority/next")
def authority_next(
    customerId: str = Query(...),
    accountId: str | None = Query(default=None),
    feeType: str = Query(default="late_fee"),
    askedAmount: float | None = Query(default=None),
    interactionId: str | None = Query(default=None),
):
    """What may close on this call, in rupees.

    Safe to call from a screen: outside ``AUTHORITY_MODE=live`` the engine
    decides, logs and posts nothing. The decision row is written either way.
    """
    return _handle_write(
        db.next_authority,
        customer_id=customerId,
        account_id=accountId,
        fee_type=feeType,
        asked_amount=askedAmount,
        interaction_id=interactionId,
    )


@app.post("/authority/apply")
def authority_apply(payload: AuthorityApplyRequest):
    """Post the goodwill the matrix already approved. Live mode only."""
    return _handle_write(db.apply_authority, payload.model_dump(exclude_none=True))


# ---------------------------------------------------------------------------
# Provider registry — Agent Studio picks the vendor, the runtime obeys.
# ---------------------------------------------------------------------------


@app.get("/providers/models", response_model=list[ProviderModelItem])
def list_provider_models(kind: str | None = Query(default=None, pattern="^(stt|tts|llm)$")):
    """The capability matrix. Unconfigured providers are returned too, marked
    ``configured: false`` — hiding them makes "why can't I pick X?" unanswerable
    from the screen."""
    from agent_core.providers import persist as pv
    from agent_core.providers.registry import (
        RUNTIME_LIVE,
        configured_providers,
        find_model,
        runtime_status,
    )

    live = configured_providers()
    out = []
    for row in pv.list_models(kind):
        # A key makes a provider *configured*; it does not make the model
        # *runnable*. Both are reported because they fail differently: no key is
        # something the operator can fix from the Integrations screen, a missing
        # service class is not.
        spec = find_model(row["provider_id"], row["model_id"])
        runtime, detail = runtime_status(spec) if spec is not None else (RUNTIME_LIVE, "")
        out.append(
            {
                "id": row["id"],
                "providerId": row["provider_id"],
                "providerName": row["provider_name"],
                "kind": row["kind"],
                "modelId": row["model_id"],
                "displayName": row["display_name"],
                "serviceClass": row["service_class"],
                "locales": list(row["locales"] or []),
                "streaming": bool(row["streaming"]),
                "codeSwitch": bool(row["code_switch"]),
                "onPrem": bool(row["on_prem"]),
                "diarization": bool(row["diarization"]),
                "styles": list(row["styles"] or []),
                "costPerUnit": float(row["cost_per_unit"]) if row["cost_per_unit"] is not None else None,
                "costUnit": row["cost_unit"],
                "measuredLatencyP50Ms": row["measured_latency_p50_ms"],
                "measuredLatencyP95Ms": row["measured_latency_p95_ms"],
                "notes": row["notes"] or "",
                "paramsSchema": list(row["params_schema"] or []),
                "enabled": bool(row["enabled"]),
                "configured": row["provider_id"] in live,
                "runtime": runtime,
                "runtimeDetail": detail,
                # Read off the registry rather than the row: it is a measured
                # property of the vendor's engine, not tenant configuration, so
                # it has no business being editable per deployment.
                "sampling": bool(spec.sampling) if spec is not None else False,
            }
        )
    return out


@app.get("/providers/bindings", response_model=list[ProviderBindingItem])
def list_provider_bindings(botId: str | None = Query(default=None)):
    """Bindings for a bot plus the tenant defaults it inherits."""
    from agent_core.providers import persist as pv

    return [
        {
            "id": b["id"],
            "botId": b["bot_id"],
            "slot": b["slot"],
            "locale": b["locale"],
            "providerModelId": b["provider_model_id"],
            "providerId": b["provider_id"],
            "providerName": b["provider_name"],
            "modelId": b["model_id"],
            "displayName": b["display_name"],
            "voiceRef": b["voice_ref"],
            "priority": int(b["priority"]),
            "settings": dict(b["settings"] or {}),
            "enabled": bool(b["enabled"]),
        }
        for b in pv.list_bindings(tenant_id=db.current_tenant(), bot_id=botId)
    ]


@app.post("/providers/bindings", response_model=ProviderBindingItem)
def upsert_provider_binding(payload: ProviderBindingInput):
    from agent_core.providers import persist as pv

    binding_id = pv.upsert_binding(
        tenant_id=db.current_tenant(),
        slot=payload.slot,
        provider_model_id=payload.providerModelId,
        bot_id=payload.botId,
        locale=payload.locale,
        voice_ref=payload.voiceRef,
        priority=payload.priority,
        settings=payload.settings,
        enabled=payload.enabled,
    )
    rows = [b for b in pv.list_bindings(tenant_id=db.current_tenant(), bot_id=payload.botId)
            if b["id"] == binding_id]
    if not rows:
        raise HTTPException(status_code=500, detail="binding_write_failed")
    b = rows[0]
    return {
        "id": b["id"],
        "botId": b["bot_id"],
        "slot": b["slot"],
        "locale": b["locale"],
        "providerModelId": b["provider_model_id"],
        "providerId": b["provider_id"],
        "providerName": b["provider_name"],
        "modelId": b["model_id"],
        "displayName": b["display_name"],
        "voiceRef": b["voice_ref"],
        "priority": int(b["priority"]),
        "settings": dict(b["settings"] or {}),
        "enabled": bool(b["enabled"]),
    }


@app.delete("/providers/bindings/{binding_id}")
def delete_provider_binding(binding_id: str):
    from agent_core.providers import persist as pv

    if not pv.delete_binding(tenant_id=db.current_tenant(), binding_id=binding_id):
        raise HTTPException(status_code=404, detail="binding_not_found")
    return {"ok": True}


@app.get("/providers/pools", response_model=list[ProviderPoolStatus])
def list_provider_pools():
    """Key-pool health, so free-tier exhaustion is visible before a demo hits it."""
    from agent_core.providers import pool as pool_mod
    from agent_core.providers.registry import SEED

    # Touch every seeded provider so a pool that has never been acquired from
    # still reports (total=0) rather than being absent from the list.
    for spec in SEED:
        pool_mod.get_pool(spec.slug)
    return [
        {
            "provider": s.provider,
            "total": s.total,
            "available": s.available,
            "retired": s.retired,
            "sessionsBound": s.sessions_bound,
            "keys": s.keys,
        }
        for s in pool_mod.all_stats()
    ]


@app.get("/tts-voices/catalog-provider-counts")
def tts_voice_provider_counts():
    """Per-provider voice counts for the catalog filter chips.

    Dash-separated rather than `/catalog/provider-counts`: the latter would be
    captured by the `/tts-voices/catalog/{short_name}` route declared above and
    looked up as a voice named "provider-counts". Same reason
    `/tts-voices/catalog-warning` is spelled that way.
    """
    return db.list_tts_voice_provider_counts()


@app.get("/tts-voices/catalog-locale-counts")
def tts_voice_locale_counts(limit: int = Query(default=60, ge=1, le=400)):
    """Locales present in the catalog, most-voices-first, for the locale picker."""
    return db.list_tts_voice_locale_counts(limit=limit)
