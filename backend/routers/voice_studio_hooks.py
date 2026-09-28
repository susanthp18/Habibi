"""PayInt Voice Studio -> PayInt: the engine's calls into our platform.

Not user routes. The engine authenticates with the shared bearer token
(VOICE_STUDIO_HOOK_TOKEN, stored in the engine as a credential), checked here
in constant time -- the same model as the payment and telephony webhooks.

    POST /voice-studio/hooks/tools/{name}     an agent tool call
    POST /voice-studio/hooks/call-started     a call began: put it on the floor
    POST /voice-studio/hooks/precall          inbound: who is calling
    POST /voice-studio/hooks/transfer         where a transfer-to-human rings
    POST /voice-studio/hooks/run-completed    post-call: file the call
    POST /voice-studio/hooks/authorize        may this engine API key's owner do this
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

import voice_studio
from api_support import ROUTER_DEPENDENCIES, Utf8JSONResponse

logger = logging.getLogger(__name__)

PREFIX = "/voice-studio/hooks"

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)


def _authorised(authorization: str | None) -> None:
    if not voice_studio.hook_token_ok(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")


async def _json(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        body = {}
    return body if isinstance(body, dict) else {}


@router.post(f"{PREFIX}/tools/{{name}}")
async def tool_call(name: str, request: Request, authorization: str | None = Header(default=None)) -> dict:
    _authorised(authorization)
    return await run_in_threadpool(voice_studio.run_tool, name, await _json(request))


@router.post(f"{PREFIX}/call-started")
async def call_started(request: Request, authorization: str | None = Header(default=None)) -> dict:
    _authorised(authorization)
    return await run_in_threadpool(voice_studio.call_started, await _json(request))


@router.post(f"{PREFIX}/precall")
async def precall(request: Request, authorization: str | None = Header(default=None)) -> dict:
    _authorised(authorization)
    return await run_in_threadpool(voice_studio.precall, await _json(request))


@router.post(f"{PREFIX}/transfer")
async def transfer(request: Request, authorization: str | None = Header(default=None)) -> dict:
    _authorised(authorization)
    return await run_in_threadpool(voice_studio.transfer_destination, await _json(request))


@router.post(f"{PREFIX}/admit")
async def admit(request: Request, authorization: str | None = Header(default=None)) -> dict:
    """Before the engine dials on its own: PayInt's contact policy decides."""
    _authorised(authorization)
    return await run_in_threadpool(voice_studio.admit_engine_call, await _json(request))


@router.post(f"{PREFIX}/run-completed")
async def run_completed(request: Request, authorization: str | None = Header(default=None)) -> dict:
    _authorised(authorization)
    body = await _json(request)
    try:
        return await run_in_threadpool(voice_studio.complete_run, body)
    except Exception:
        # Answered 500 so the engine's durable webhook delivery retries it.
        logger.exception("voice studio: filing run %s failed", body.get("workflow_run_id"))
        raise HTTPException(status_code=500, detail="filing_failed")


@router.post(f"{PREFIX}/authorize")
async def authorize(request: Request, authorization: str | None = Header(default=None)) -> dict:
    """An engine API key is used: is its PayInt owner still allowed to do this?

    Re-checked on every use, so deactivating someone or taking a permission
    away stops their keys at once. One policy: the gateway's own table.
    """
    _authorised(authorization)
    return await run_in_threadpool(key_use_allowed, await _json(request))


#: Engine paths a key may reach that the browser gateway never proxies.
_KEY_ONLY_PATHS = ("/public/", "/agent-stream/", "/telephony/initiate-call")


def key_use_allowed(body: dict) -> dict:
    import authz
    import db
    from routers import agentstudio_gateway as gateway
    from sqlalchemy import text

    user = str(body.get("user_id") or "")
    tenant = str(body.get("tenant_id") or "")
    method = str(body.get("method") or "GET").upper()
    path = "/" + str(body.get("path") or "").split("?", 1)[0].removeprefix("/api/v1").lstrip("/")
    if user == voice_studio.SYSTEM_ACTOR:
        return {"allowed": True}
    with db.engine.connect() as conn:
        row = conn.execute(text("SELECT tenant_id, status FROM users WHERE id = :u"), {"u": user}).first()
    if row is None or row.tenant_id != tenant or row.status != "active":
        return {"allowed": False, "reason": "owner_inactive"}
    if path.startswith(_KEY_ONLY_PATHS):
        perms: tuple[str, ...] = (authz.VOICE_OPERATE,)
    else:
        perms = gateway.required_permissions(method, path)
    if perms and any(authz.has_permission(user, p) for p in perms):
        return {"allowed": True}
    return {"allowed": False, "reason": f"forbidden:{perms[0] if perms else 'path'}"}
