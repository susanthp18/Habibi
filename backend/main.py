"""Collections Agent — CRM backend API.

Run:  .venv/Scripts/python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
Serves read/query endpoints from the normalized Postgres data layer.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Callable

from env_loader import load_env
from env_utils import env_bool

load_env()

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from api_support import Utf8JSONResponse, authz_guard as _authz_guard
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

import actor_context
import authz
import azure_openai
import circuit_breaker
import db
import observability
import request_context
import storage


logger = logging.getLogger(__name__)

# Unrecognised APP_ENV is production. Only an explicit laptop name keeps the
# open envelope — a typo or APP_ENV=staging must not silently disable auth.
_APP_ENV = (os.getenv("APP_ENV") or "dev").strip().lower()
_IS_PROD = _APP_ENV not in {"dev", "test", "local"}

from api_support import EMBEDDED_VOICE_HOST as _EMBEDDED_VOICE_HOST  # noqa: E402

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
    # Delivery receipts. Twilio carries no API key; the handler HMAC is the
    # authentication — same as the voice callbacks above. This path lived in
    # authz.PUBLIC_ROUTES and not here, so ApiKeyMiddleware 401'd it first.
    "/twilio/sms/status",
    "/pay",
    "/webhooks/payments",
    # `/webhooks/payments` does not prefix-match `/webhooks/collections/…`
    # because matching is `path == p or path.startswith(p + "/")`.
    "/webhooks/collections/payment-events",
    "/ws",
    "/.well-known/agent-card.json",
    # SmallWebRTC signalling. The WebRTC client cannot attach our API-key
    # header to its offer POST, and the standalone runner it replaces has no
    # auth at all — so this is parity, not a downgrade. Only present when the
    # embedded host is actually serving these routes.
    *(("/api/offer", "/voice-rtc") if _EMBEDDED_VOICE_HOST else ()),
)


def _a2a_enabled() -> bool:
    from agent_core.platform_flags import a2a_enabled

    return a2a_enabled()


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """API-key gate + request-scoped actor binding.

    CORS preflight (OPTIONS) must never be gated — browsers do not send
    custom headers on preflight, and this middleware must run *inside*
    CORSMiddleware so even 401 responses carry CORS headers.

    Actor resolution (see ``actor_context``):
      - ``API_KEY_MAP`` JSON maps each secret → ``users.id``
      - shared ``API_KEY`` → ``ACTOR_USER_ID``, or ``X-Actor-User-Id`` when
        ``ALLOW_ACTOR_HEADER`` is on (default: off; must be set explicitly)
    """

    async def dispatch(self, request: Request, call_next: Callable):
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        # A2A authenticates by client certificate, reported by the TLS
        # terminator -- but only while the feature is on. Off, the route is
        # an ordinary authenticated endpoint that answers 403 `a2a_disabled`.
        if request.method == "POST" and path == "/a2a" and _a2a_enabled():
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
        # Absent credentials are a refusal, not a mode. Production-like
        # environments require a key even if the operator left both unset
        # (the lifespan check should have refused to boot; this is the belt).
        auth_required = _IS_PROD or bool(single or key_map)

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
    """Refuse to boot a deployed or production-named process while controls are off.

    Dev/test/local is allowed only on a verified local or CI host. A deployed
    container (HABIBI_DEPLOYED=1) is always hardened. There is no hatch.
    """
    deployed = env_bool("HABIBI_DEPLOYED")
    unhardened_ok = _APP_ENV in {"dev", "test", "local"} and not deployed
    if unhardened_ok:
        return
    raise RuntimeError(
        f"APP_ENV={_APP_ENV} but the data layer's deferred controls are not active: "
        + "; ".join(_DEFERRED_HARDENING_CONTROLS)
        + ". Run this build locally with APP_ENV=dev, or complete the deferred controls."
    )


def _warn_if_no_policy_rules() -> None:
    import policy_rules

    with db.engine.connect() as conn:
        resolved = policy_rules.resolve(conn, tenant_id=db.current_tenant())
    if resolved is policy_rules.EMPTY or not resolved.rules:
        logger.warning(
            "no published statutory rule set for tenant %s — the contact gate runs on "
            "module constants and stamps no policy_version; run scripts/seed_policy_rules.py",
            db.current_tenant(),
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
        raise RuntimeError(
            f"API_KEY or API_KEY_MAP must be set when APP_ENV={_APP_ENV!r} "
            "(only dev/test/local may boot without credentials)"
        )
    if not has_auth:
        logger.warning(
            "API_KEY / API_KEY_MAP unset — CRM routes are public. "
            "Set credentials (required outside APP_ENV=dev/test/local)."
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
            # Say so at boot, not per decision: with no published statutory
            # set the contact gate runs on module constants and stamps no
            # policy_version. The seeder is scripts/seed_policy_rules.py.
            await asyncio.to_thread(_warn_if_no_policy_rules)
        except Exception:
            logger.warning("policy rule set check failed", exc_info=True)
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








































































































































































































































































































































































































































































































































































































































































# ---------------------------------------------------------------------------
# Next-best-treatment (P3)
# ---------------------------------------------------------------------------






















# ---------------------------------------------------------------------------
# Outbound — the reach numbers that did not exist before call_attempts
# ---------------------------------------------------------------------------
































# ---------------------------------------------------------------------------
# Live authority matrix (P4)
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# Provider registry — Agent Studio picks the vendor, the runtime obeys.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Routes live in routers/<domain>.py (WS7). Included last: every middleware,
# exception handler and lifespan hook above is wired before a route exists.
# ---------------------------------------------------------------------------
from api_support import _handle_write, _read_upload_capped, _MAX_UPLOAD_BYTES  # noqa: E402,F401  (tests and middleware reach them here)
from routers import a2a, agent_studio, billing, compliance, crm, evals, floor, inbox, integrations, kb, outbound, payments, platform, routing, sandbox, telephony, voice_catalog, webhooks  # noqa: E402

# Appended flat rather than `include_router`: FastAPI 0.139 nests an included
# router as one `_IncludedRouter` entry, and everything that walks `app.routes`
# -- the authz coverage check, the response-model test, the voice websocket
# test -- expects one APIRoute per route. Each router carries the app's
# response class itself, so nothing is lost by not going through include.
for _router_module in (a2a, agent_studio, billing, compliance, crm, evals, floor, inbox, integrations, kb, outbound, payments, platform, routing, sandbox, telephony, voice_catalog, webhooks):
    for _route in _router_module.router.routes:
        app.router.routes.append(_route)
