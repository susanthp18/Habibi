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
from starlette.responses import StreamingResponse

import authz
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

PERMISSION_RULES: list[tuple[set[str], re.Pattern[str], tuple[str, ...]]] = [
    (_ANY, re.compile(r"^/(auth|superuser|public|agent-stream|mcp)(/|$)"), _DENY),
    (_W, re.compile(r"^/tools/[^/]+/revisions/\d+/review$"), _DENY),
    (_R, re.compile(r"^/(health|node-types|turn)(/|$)"), (authz.BOT_READ,)),
    (_ANY, re.compile(r"^/ws(/|$)"), (authz.VOICE_OPERATE,)),
    # The PayInt release endpoint owns preflight and the durable release audit.
    (_W, re.compile(r"^/workflow/\d+/publish$"), _DENY),
    (_W, re.compile(r"^/workflow/\d+/runs$"), (authz.VOICE_OPERATE,)),
    (_W, re.compile(r"^/telephony/initiate-call$"), (authz.VOICE_OPERATE,)),
    (_R, re.compile(r"^/campaign(/|$)"), (authz.BOT_READ,)),
    (_W, re.compile(r"^/campaign(/|$)"), (authz.VOICE_OPERATE,)),
    (_R, re.compile(r"^/knowledge-base(/|$)"), (authz.KB_READ,)),
    (_W, re.compile(r"^/knowledge-base/search$"), (authz.KB_READ,)),
    (_W, re.compile(r"^/knowledge-base(/|$)"), (authz.KB_WRITE,)),
    (_R, re.compile(r"^/organizations/(usage|reports)(/|$)"), (authz.ANALYTICS_READ,)),
    (_ANY, re.compile(r"^/user/api-keys(/|$)"), (authz.ADMIN_WRITE,)),
    # Hearing a voice sample changes nothing; agent editors tune voices with it.
    (_W, re.compile(r"^/user/configurations/voices/[^/]+/preview$"), (authz.AGENT_EDIT, authz.INTEGRATIONS_READ)),
    (
        _R,
        re.compile(r"^/(tools|credentials|telephony|user/configurations)(/|$)"
                   r"|^/organizations/(telephony-configs|model-configurations|langfuse-credentials)"),
        (authz.INTEGRATIONS_READ,),
    ),
    (
        _W,
        re.compile(r"^/(tools|credentials|telephony|user/configurations)(/|$)"
                   r"|^/organizations/(telephony-configs|model-configurations|langfuse-credentials)"),
        (authz.INTEGRATIONS_WRITE,),
    ),
    (_R, re.compile(r"^/s3(/|$)"), (authz.BOT_READ,)),
    (_W, re.compile(r"^/s3(/|$)"), (authz.AGENT_EDIT, authz.VOICE_OPERATE, authz.KB_WRITE)),
    (_R, re.compile(r"^/(workflow|folder|workflow-recordings)(/|$)"), (authz.BOT_READ,)),
    (_W, re.compile(r"^/(workflow|folder|workflow-recordings)(/|$)"), (authz.AGENT_EDIT,)),
    (_R, re.compile(r"^/(user|organizations)(/|$)"), (authz.BOT_READ,)),
    (_W, re.compile(r"^/user/onboarding-state$"), (authz.BOT_READ,)),
]


def required_permissions(method: str, path: str) -> tuple[str, ...]:
    for methods, pattern, perms in PERMISSION_RULES:
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


def _engine_path(path: str) -> str:
    """Engine path below /api/v1. The UI's generated client sends the full
    ``/api/v1/...`` path; both spellings address the same route."""
    path = "/" + path.lstrip("/")
    return path[len("/api/v1"):] if path.startswith("/api/v1/") else path


async def _proxy(request: Request, path: str) -> StreamingResponse:
    method = request.method.upper()
    engine_path = _engine_path(path)
    actor = _actor(request)
    await run_in_threadpool(_authorise, method, engine_path, actor)
    publish = re.fullmatch(r"/workflow/(\d+)/publish", engine_path)
    if method == "POST" and publish:
        # Releases go through /voice-studio/agents/{id}/publish: the same gate
        # (validate_publish) plus a changelog note and the releasing user.
        raise HTTPException(status_code=409, detail="Publish from Voice Studio with a changelog note")
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
    await bridge_websocket(websocket, upstream, headers=identity, label="agentstudio")
