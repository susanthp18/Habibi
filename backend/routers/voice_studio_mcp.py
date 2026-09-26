"""Authenticated Streamable HTTP gateway for Voice Studio draft authoring."""

from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

import authz
from api_support import ROUTER_DEPENDENCIES
from routers import agentstudio_gateway as gateway

router = APIRouter(dependencies=ROUTER_DEPENDENCIES)

_READ_TOOLS = frozenset({
    "get_node_type", "get_workflow", "get_workflow_code", "list_credentials",
    "list_documents", "list_node_types", "list_recordings", "list_tools",
    "list_workflows", "get_tool_revisions", "get_voice_prompting_guide", "list_docs", "read_doc", "search_docs",
})
_EDIT_TOOLS = frozenset({"create_workflow", "create_tool", "save_workflow", "update_tool"})
_FORWARD = {"accept", "content-type", "mcp-protocol-version", "mcp-session-id", "last-event-id"}
_DROP = {"connection", "keep-alive", "transfer-encoding", "content-length", "server", "date"}
_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=5.0))
    return _client


def _authorise(request: Request, payload: Any | None) -> tuple[str, str | None]:
    principal = getattr(request.state, "studio_mcp_key", None)
    if not principal:
        raise HTTPException(status_code=401, detail="unauthorized")
    actor = principal["userId"]
    scopes = set(principal["scopes"])
    if not scopes.intersection({"studio.read", "studio.edit"}) or not authz.has_permission(actor, authz.BOT_READ):
        raise HTTPException(status_code=403, detail="forbidden:studio.read")
    if request.method != "POST":
        return actor, None
    if not isinstance(payload, dict) or isinstance(payload.get("method"), (dict, list)):
        raise HTTPException(status_code=400, detail="single_jsonrpc_request_required")
    method = payload.get("method")
    if method == "tools/call":
        params = payload.get("params")
        name = params.get("name") if isinstance(params, dict) else None
        if name in _EDIT_TOOLS:
            if "studio.edit" not in scopes or not authz.has_permission(actor, authz.AGENT_EDIT):
                raise HTTPException(status_code=403, detail="forbidden:studio.edit")
            return actor, str(name)
        if name not in _READ_TOOLS:
            raise HTTPException(status_code=403, detail="mcp_operation_not_allowed")
        return actor, str(name)
    if method not in {"initialize", "notifications/initialized", "ping", "tools/list"}:
        raise HTTPException(status_code=403, detail="mcp_operation_not_allowed")
    return actor, None


@router.api_route("/studio-mcp/", methods=["GET", "POST", "DELETE"])
@router.api_route("/studio-mcp", methods=["GET", "POST", "DELETE"])
async def studio_mcp_gateway(request: Request) -> StreamingResponse:
    raw = b""
    payload = None
    if request.method == "POST":
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > 1_048_576:
                raise HTTPException(status_code=413, detail="mcp_request_too_large")
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid_jsonrpc") from exc
    actor, operation = await run_in_threadpool(_authorise, request, payload)
    headers = {k: v for k, v in request.headers.items() if k.lower() in _FORWARD}
    headers.update(await run_in_threadpool(gateway._identity, actor))
    if rid := request.headers.get("x-request-id"):
        headers["X-Request-Id"] = rid
    upstream = _http().build_request(
        request.method, f"{gateway._engine_url()}/api/v1/mcp/",
        headers=headers, content=raw if request.method == "POST" else None,
    )
    try:
        response = await _http().send(upstream, stream=True)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Voice Studio MCP unavailable") from exc

    async def done() -> None:
        await response.aclose()
        if operation and 200 <= response.status_code < 300:
            await run_in_threadpool(
                gateway._audit, actor, "POST",
                f"/mcp/keys/{request.state.studio_mcp_key['id']}/tools/{operation}",
                response.status_code,
            )

    return StreamingResponse(
        response.aiter_raw(), status_code=response.status_code,
        headers={k: v for k, v in response.headers.items() if k.lower() not in _DROP},
        background=BackgroundTask(done),
    )
