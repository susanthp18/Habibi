"""AgentStudio gateway: the browser's only way into the voice-agent engine.

The engine (agentstudio/engine, AUTH_PROVIDER=internal) trusts exactly one
caller: this router. Every request is authenticated here (Entra / API key,
by ``ApiKeyMiddleware``), authorised against our RBAC, stripped of any
credential the browser sent, and forwarded with the actor's identity signed by
the shared secret. Writes land on the hash-chained audit log.

    /studio-api/{path}                 HTTP, streamed both ways
    POST /studio-api/_ws-ticket        mint a one-use socket ticket
    WS   /studio-ws/{ticket}/{path}    WebSocket (live test calls), ticket-gated

The engine's public surfaces (telephony webhooks and media sockets, embed and
API triggers) carry their own credentials and bypass this router at the proxy.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
import uuid
from typing import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.concurrency import run_in_threadpool
from starlette.background import BackgroundTask
from starlette.responses import Response, StreamingResponse

import authz
import voice_studio_supervision
from api_support import ROUTER_DEPENDENCIES, Utf8JSONResponse
from env_utils import env_str

logger = logging.getLogger(__name__)

HTTP_PREFIX = "/studio-api"
WS_PREFIX = "/studio-ws"
_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
_WRITE = {"POST", "PUT", "PATCH", "DELETE"}

# ---------------------------------------------------------------------------
# Permission table: (methods, engine path regex) -> any-of permissions.
# First match wins; anything unmatched needs admin. Paths are engine paths
# below /api/v1.
# ---------------------------------------------------------------------------
_R = {"GET"}
_W = _WRITE
_ANY = _R | _W
_DENY: tuple[str, ...] = ()
_PHONE_NUMBER = re.compile(r"^/organizations/telephony-configs/\d+/phone-numbers(/\d+)?$")

#: The fourth field names the action for the Roles screen (``studio_actions``);
#: None for rules that are plumbing or refusals rather than something to grant.
PERMISSION_RULES: list[tuple[set[str], re.Pattern[str], tuple[str, ...], str | None]] = [
    (_ANY, re.compile(r"^/(auth|superuser|public|agent-stream|mcp)(/|$)"), _DENY, None),
    (_W, re.compile(r"^/tools/[^/]+/revisions/\d+/review$"), _DENY, None),
    # The carrier's media socket. Twilio reaches it through nginx with a signed
    # token; no browser should be handed a ticket that lets it become a call.
    (_ANY, re.compile(r"^/telephony/ws(/|$)"), _DENY, None),
    (_R, re.compile(r"^/(health|node-types|turn)(/|$)"), (authz.BOT_READ,), None),
    (_ANY, re.compile(r"^/ws(/|$)"), (authz.VOICE_OPERATE,), "Talk to an agent from the browser"),
    # Supervising a live call (voice_studio_supervision): a socket ticket is
    # minted as a GET. Whispers go server-side through the Floor's action.
    (_R, re.compile(r"^/supervise/\d+/listen$"), (authz.SUPERVISOR_READ,), "Listen to a live call"),
    (_R, re.compile(r"^/supervise/\d+/takeover$"), (authz.SUPERVISOR_WRITE,), "Take over a live call"),
    (_ANY, re.compile(r"^/supervise(/|$)"), _DENY, None),
    # The PayInt release endpoint owns preflight and the durable release audit.
    (_W, re.compile(r"^/workflow/\d+/publish$"), _DENY, None),
    (_W, re.compile(r"^/workflow/\d+/runs$"), (authz.VOICE_OPERATE,), "Start a run of an agent"),
    (_W, re.compile(r"^/telephony/initiate-call$"), (authz.VOICE_OPERATE,), "Ring a test number from the editor"),
    # Files of borrower numbers and call outcomes: raw personal data.
    (_R, re.compile(r"^/campaign/\d+/(source-download-url|report)$|^/workflow/\d+/report$"
                    r"|^/organizations/usage/runs/report$"),
     (authz.PII_RAW_READ,), "Download campaign and agent reports (unmasked)"),
    # Changing a running campaign's schedule, pace or retries is as much a
    # launch decision as starting it.
    ({"PATCH"}, re.compile(r"^/campaign/\d+$"), (authz.COLLECTIONS_WRITE,),
     "Change a campaign's schedule, pace or retries"),
    # Ringing phones is a launch, as with PayInt campaigns; drafting one is not.
    (_W, re.compile(r"^/campaign/\d+/(start|resume|redial)$"), (authz.COLLECTIONS_WRITE,),
     "Start, resume or redial a Voice Studio campaign"),
    (_R, re.compile(r"^/campaign(/|$)"), (authz.BOT_READ,), "See campaigns and their progress"),
    (_W, re.compile(r"^/campaign(/|$)"), (authz.VOICE_OPERATE,), "Draft or pause a Voice Studio campaign"),
    (_R, re.compile(r"^/knowledge-base(/|$)"), (authz.KB_READ,), "Browse and search agent knowledge"),
    (_W, re.compile(r"^/knowledge-base/search$"), (authz.KB_READ,), None),
    (_W, re.compile(r"^/knowledge-base(/|$)"), (authz.KB_WRITE,), "Upload and edit agent knowledge"),
    (_R, re.compile(r"^/organizations/(usage|reports)(/|$)"), (authz.ANALYTICS_READ,), "See agent runs, usage and reports"),
    (_ANY, re.compile(r"^/user/api-keys(/|$)"), (authz.ADMIN_WRITE,), "Create engine API keys"),
    # Hearing a voice sample changes nothing; agent editors tune voices with it.
    (_W, re.compile(r"^/user/configurations/voices/[^/]+/preview$"), (authz.AGENT_EDIT, authz.INTEGRATIONS_READ),
     "Preview voices"),
    # Tools are part of the agent: edited by its authors, released by an
    # approver through tool revisions (review is PayInt's, above).
    (_W, re.compile(r"^/tools(/|$)"), (authz.AGENT_EDIT,), "Create, edit and test the tools an agent calls"),
    # An approver must be able to open the tool whose revision they approve.
    (_R, re.compile(r"^/tools(/|$)"), (authz.INTEGRATIONS_READ, authz.TOOL_APPROVE), None),
    (
        _R,
        re.compile(r"^/(tools|credentials|telephony|user/configurations)(/|$)"
                   r"|^/organizations/(telephony-configs|model-configurations|langfuse-credentials)"),
        (authz.INTEGRATIONS_READ,),
        "See tools, credentials, telephony and model settings",
    ),
    (
        _W,
        re.compile(r"^/(credentials|telephony|user/configurations)(/|$)"
                   r"|^/organizations/(telephony-configs|model-configurations|langfuse-credentials)"),
        (authz.INTEGRATIONS_WRITE,),
        "Change credentials, telephony, phone numbers and which models agents use",
    ),
    (_R, re.compile(r"^/s3(/|$)"), (authz.BOT_READ,), None),
    (_W, re.compile(r"^/s3(/|$)"), (authz.AGENT_EDIT, authz.VOICE_OPERATE, authz.KB_WRITE), None),
    # Making an agent public (embed) or taking it out of service is a release.
    (_W, re.compile(r"^/workflow/\d+/(embed-token|status)$"), (authz.AGENT_PUBLISH,),
     "Embed an agent on a website, or archive it"),
    (_R, re.compile(r"^/(workflow|folder|workflow-recordings)(/|$)"), (authz.BOT_READ,), "Open agents and their runs"),
    (_W, re.compile(r"^/(workflow|folder|workflow-recordings)(/|$)"), (authz.AGENT_EDIT,),
     "Edit agents, folders and recordings; chat-test a draft"),
    (_R, re.compile(r"^/(user|organizations)(/|$)"), (authz.BOT_READ,), None),
    (_W, re.compile(r"^/user/onboarding-state$"), (authz.BOT_READ,), None),
]

#: PayInt-side Voice Studio actions that are not engine paths.
STUDIO_ACTIONS_EXTRA: tuple[tuple[str, str], ...] = (
    (authz.AGENT_PUBLISH, "Publish or roll back an agent"),
    (authz.AGENT_PUBLISH, "Route inbound, outbound or WhatsApp to an agent (with Place calls)"),
    (authz.VOICE_OPERATE, "Route inbound, outbound or WhatsApp to an agent (with Publish)"),
    (authz.VOICE_OPERATE, "Ring a test handset from Settings"),
    (authz.TOOL_APPROVE, "Approve a tool revision (not your own)"),
    (authz.AGENT_EDIT, "Edit an agent's guardrails and MCP keys"),
    (authz.EVAL_RUN, "Run checks and AI-customer simulations"),
    (authz.PII_RAW_READ, "Hear recordings and read unmasked transcripts"),
)


def studio_actions() -> dict[str, list[str]]:
    """What each permission unlocks in Voice Studio, derived from the rules above."""
    out: dict[str, list[str]] = {}
    for _methods, _pattern, perms, label in PERMISSION_RULES:
        for perm in perms if label else ():
            out.setdefault(perm, []).append(label)
    for perm, label in STUDIO_ACTIONS_EXTRA:
        out.setdefault(perm, []).append(label)
    out.setdefault(authz.ADMIN_WRITE, []).append("Anything not listed here")
    return out


def required_permissions(method: str, path: str) -> tuple[str, ...]:
    for methods, pattern, perms, _label in PERMISSION_RULES:
        if method in methods and pattern.search(path):
            return perms
    return (authz.ADMIN_WRITE,)


def _authorise(method: str, path: str, actor: str | None) -> None:
    perms = required_permissions(method, path)
    if not perms:
        raise HTTPException(status_code=404, detail="Not found")
    if not authz.enforcement_enabled():
        return
    if not actor or not any(authz.has_permission(actor, p) for p in perms):
        raise HTTPException(status_code=403, detail=f"forbidden:{perms[0]}")


# ---------------------------------------------------------------------------
# Identity forwarded to the engine
# ---------------------------------------------------------------------------


def _engine_url() -> str:
    return env_str("AGENTSTUDIO_ENGINE_URL", "http://agentstudio_engine:8000").rstrip("/")


def _identity(actor: str) -> dict[str, str]:
    import db
    from sqlalchemy import text

    secret = env_str("AGENTSTUDIO_INTERNAL_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Voice Studio is not configured")
    with db.engine.connect() as conn:
        email = conn.execute(
            text("SELECT COALESCE(email, entra_upn) FROM users WHERE id = :id"), {"id": actor}
        ).scalar()
    return {
        "X-Internal-Secret": secret,
        "X-User-Id": actor,
        "X-User-Email": email or "",
        "X-Org-Id": db.current_tenant(),
    }


def _actor(request_or_ws) -> str | None:
    actor = getattr(request_or_ws.state, "actor_user_id", None)
    if actor is None and not authz.enforcement_enabled():
        import actor_context

        actor = actor_context.get_actor_user_id()  # local dev without auth
    return actor


def _audit(actor: str | None, method: str, path: str, status: int) -> None:
    import db
    from agent_core import change_log

    try:
        with db.engine.begin() as conn:
            change_log.record_agentstudio_change(
                conn,
                tenant_id=db.current_tenant(),
                actor_user_id=actor,
                entry_id=f"as-{uuid.uuid4().hex}",
                method=method,
                path=path,
                status=status,
            )
    except Exception:
        logger.exception("agentstudio audit write failed: %s %s", method, path)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

_FORWARD_REQUEST = ("content-type", "accept", "accept-encoding", "accept-language", "range", "if-none-match")
_DROP_RESPONSE = {"connection", "keep-alive", "transfer-encoding", "content-length", "server", "date"}
_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        # ponytail: one pooled client for the process (API runs one worker).
        _client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=5.0))
    return _client


router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)


@router.post(f"{HTTP_PREFIX}/_ws-ticket")
async def mint_ws_ticket(request: Request, body: dict) -> dict:
    """A one-use, 60-second ticket for one engine socket path."""
    path = _engine_path(str(body.get("path") or ""))
    actor = _actor(request)
    await run_in_threadpool(_authorise, "GET", path, actor)
    if not actor:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"ticket": _tickets.mint(actor, path), "expiresInSeconds": int(_TICKET_TTL_S)}


def _can_see_raw_pii(actor: str | None) -> bool:
    return bool(actor) and authz.has_permission(actor, authz.PII_RAW_READ)


def _raw_media(engine_path: str, request: Request) -> bool:
    """A signed URL for call audio or a raw transcript, or a public download of one."""
    if engine_path.startswith("/public/download/"):
        return True
    if engine_path == "/s3/signed-url":
        key = (request.query_params.get("key") or "").lstrip("/")
        return key.startswith(("recordings/", "transcripts/"))
    return False


def _engine_path(path: str) -> str:
    """Engine path below /api/v1. The UI's generated client sends the full
    ``/api/v1/...`` path; both spellings address the same route."""
    path = "/" + path.lstrip("/")
    return path[len("/api/v1"):] if path.startswith("/api/v1/") else path


async def _proxy(request: Request, path: str) -> Response:
    method = request.method.upper()
    engine_path = _engine_path(path)
    actor = _actor(request)
    await run_in_threadpool(_authorise, method, engine_path, actor)
    publish = re.fullmatch(r"/workflow/(\d+)/publish", engine_path)
    if method == "POST" and publish:
        # Releases go through /voice-studio/agents/{id}/publish: the same gate
        # (validate_publish) plus a changelog note and the releasing user.
        raise HTTPException(status_code=409, detail="Publish from Voice Studio with a changelog note")
    raw_pii = await run_in_threadpool(_can_see_raw_pii, actor)
    if not raw_pii and _raw_media(engine_path, request):
        # Call audio and raw transcripts are heard through PayInt (redacted,
        # audited: /interactions/{id}/recording), not signed straight from storage.
        raise HTTPException(status_code=403, detail="Recordings play from PayInt, redacted; "
                                                    "the original needs raw-PII permission")
    raw: bytes | None = None
    if method in _WRITE and _PHONE_NUMBER.match(engine_path):
        # Inbound routing changes go through the audited, preflighted Routing
        # page (voice_studio_routing.assign), never a phone-number edit.
        raw = await request.body()
        try:
            sent = json.loads(raw or b"{}")
        except ValueError:
            sent = {}
        if isinstance(sent, dict) and (sent.get("inbound_workflow_id") is not None
                                       or sent.get("clear_inbound_workflow")):
            raise HTTPException(status_code=409, detail="Set the inbound agent on the Voice Studio Routing page")
    headers = {k: v for k, v in request.headers.items() if k.lower() in _FORWARD_REQUEST}
    headers.update(await run_in_threadpool(_identity, actor or ""))
    if rid := request.headers.get("x-request-id"):
        headers["X-Request-Id"] = rid

    async def body() -> AsyncIterator[bytes]:
        async for chunk in request.stream():
            yield chunk

    upstream = _http().build_request(
        method,
        f"{_engine_url()}/api/v1{engine_path}",
        params=request.query_params.multi_items(),
        headers=headers,
        content=raw if raw is not None else (body() if method in _WRITE else None),
    )
    try:
        resp = await _http().send(upstream, stream=True)
    except httpx.HTTPError as exc:
        logger.warning("agentstudio engine unreachable: %s", exc)
        raise HTTPException(status_code=502, detail="Voice Studio engine unavailable") from exc

    async def done() -> None:
        await resp.aclose()
        if method in _WRITE and 200 <= resp.status_code < 300:
            await run_in_threadpool(_audit, actor, method, engine_path, resp.status_code)

    import voice_studio_privacy

    mask = not raw_pii and voice_studio_privacy.needs_masking(method, engine_path)
    # The engine prices nothing here; each run's cost is what PayInt metered.
    priced = method == "GET" and engine_path == "/organizations/usage/runs"
    if resp.status_code == 200 and (mask or priced):
        body = await resp.aread()
        await done()
        if mask:
            # Run views carry the conversation as spoken: masked for this viewer.
            body = await run_in_threadpool(voice_studio_privacy.mask_payload, engine_path, body)
        if priced:
            import voice_studio

            body = await run_in_threadpool(voice_studio.price_runs, body)
        return Response(content=body, status_code=200, media_type="application/json",
                        headers={"Cache-Control": "private, no-store"})

    return StreamingResponse(
        resp.aiter_raw(),
        status_code=resp.status_code,
        headers={k: v for k, v in resp.headers.items() if k.lower() not in _DROP_RESPONSE},
        background=BackgroundTask(done),
    )


for _method in _METHODS:
    router.add_api_route(
        f"{HTTP_PREFIX}/{{path:path}}",
        _proxy,
        methods=[_method],
        include_in_schema=False,
        name=f"agentstudio_{_method.lower()}",
    )


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

_TICKET_TTL_S = 60.0


class _Tickets:
    """One-use socket tickets bound to an actor and an engine path.

    ponytail: in-process, valid because the API runs one uvicorn worker
    (docker-compose.yml pins --workers 1); move to Postgres before scaling out.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._live: dict[str, tuple[str, str, float]] = {}

    def mint(self, actor: str, path: str) -> str:
        ticket = secrets.token_urlsafe(24)
        with self._lock:
            now = time.monotonic()
            self._live = {k: v for k, v in self._live.items() if v[2] > now}
            self._live[hashlib.sha256(ticket.encode()).hexdigest()] = (actor, path, now + _TICKET_TTL_S)
        return ticket

    def redeem(self, ticket: str, path: str) -> str | None:
        digest = hashlib.sha256(ticket.encode()).hexdigest()
        with self._lock:
            entry = self._live.pop(digest, None)
        if entry is None or entry[2] < time.monotonic():
            return None
        actor, bound_path, _ = entry
        return actor if hmac.compare_digest(bound_path, path) else None


_tickets = _Tickets()


@router.websocket(f"{WS_PREFIX}/{{ticket}}/{{path:path}}")
async def proxy_ws(websocket: WebSocket, ticket: str, path: str) -> None:
    from voice.ws_proxy import bridge_websocket

    engine_path = _engine_path(path)
    actor = _tickets.redeem(ticket, engine_path)
    if actor is None:
        await websocket.close(code=1008, reason="invalid or expired ticket")
        return
    identity = await asyncio.to_thread(_identity, actor)
    query = websocket.url.query
    upstream = "ws" + _engine_url()[4:] + f"/api/v1{engine_path}" + (f"?{query}" if query else "")
    supervised = voice_studio_supervision.SOCKET_PATH.match(engine_path)
    if not supervised:
        await bridge_websocket(websocket, upstream, headers=identity, label="agentstudio")
        return
    run_id, mode = supervised.groups()
    await asyncio.to_thread(_audit, actor, "WS", engine_path, 101)
    ctx = await asyncio.to_thread(voice_studio_supervision.opened, actor, run_id, mode)
    try:
        await bridge_websocket(
            websocket, upstream, headers=identity, label="agentstudio-supervise",
            server_text=voice_studio_supervision.masker(await asyncio.to_thread(_can_see_raw_pii, actor)),
        )
    finally:
        await asyncio.to_thread(voice_studio_supervision.closed, ctx)
