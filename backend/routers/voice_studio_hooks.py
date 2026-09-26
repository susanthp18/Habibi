"""PayInt Voice Studio -> PayInt: the engine's calls into our platform.

Not user routes. The engine authenticates with the shared bearer token
(VOICE_STUDIO_HOOK_TOKEN, stored in the engine as a credential), checked here
in constant time -- the same model as the payment and telephony webhooks.

    POST /voice-studio/hooks/tools/{name}     an agent tool call
    POST /voice-studio/hooks/precall          inbound: who is calling
    POST /voice-studio/hooks/transfer         where a transfer-to-human rings
    POST /voice-studio/hooks/run-completed    post-call: file the call
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


@router.post(f"{PREFIX}/precall")
async def precall(request: Request, authorization: str | None = Header(default=None)) -> dict:
    _authorised(authorization)
    return await run_in_threadpool(voice_studio.precall, await _json(request))


@router.post(f"{PREFIX}/transfer")
async def transfer(request: Request, authorization: str | None = Header(default=None)) -> dict:
    _authorised(authorization)
    return await run_in_threadpool(voice_studio.transfer_destination, await _json(request))


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
