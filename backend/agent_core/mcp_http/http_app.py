"""Starlette MCP HTTP app. Separate process — never mounted on FastAPI."""

from __future__ import annotations

import json
import os
import ssl
from typing import Any

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from agent_core.mcp_http.auth import authenticate
from agent_core.mcp_http.protocol import handle_rpc
from agent_core.platform_flags import mcp_http_enabled


class _AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in {"/healthz", "/readyz"}:
            return await call_next(request)
        presented = request.headers.get("authorization") or request.headers.get("x-mcp-key")
        principal = authenticate(presented)
        if principal is None:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        request.state.principal = principal
        return await call_next(request)


async def health(_: Request) -> Response:
    return JSONResponse({"ok": True, "transport": "http"})


async def mcp_endpoint(request: Request) -> Response:
    if request.method == "GET":
        return JSONResponse({"error": "use_post_jsonrpc"}, status_code=405)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32700, "message": "parse error"}}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32600, "message": "invalid request"}}, status_code=400)
    rpc_id = body.get("id")
    method = str(body.get("method") or "")
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    headers = {
        "Mcp-Method": method,
        "Mcp-Name": "bigbound-collections",
        "Mcp-Protocol-Version": "2025-11-25",
    }
    principal = getattr(request.state, "principal", None) or {}
    try:
        result = handle_rpc(method, params, principal)
        if rpc_id is None:
            return Response(status_code=204, headers=headers)
        return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": result}, headers=headers)
    except PermissionError as exc:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32001, "message": str(exc)}},
            status_code=403,
            headers=headers,
        )
    except KeyError as exc:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": str(exc)}},
            status_code=404,
            headers=headers,
        )
    except Exception as exc:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32000, "message": type(exc).__name__}},
            status_code=500,
            headers=headers,
        )


def build_app() -> Starlette:
    app = Starlette(
        routes=[
            Route("/healthz", health),
            Route("/mcp", mcp_endpoint, methods=["GET", "POST"]),
        ]
    )
    app.add_middleware(_AuthMiddleware)
    return app


def ssl_kwargs() -> dict[str, Any]:
    cert = (os.getenv("MCP_TLS_CERTFILE") or "").strip()
    key = (os.getenv("MCP_TLS_KEYFILE") or "").strip()
    ca = (os.getenv("MCP_TLS_CAFILE") or "").strip()
    if not cert or not key:
        return {}
    kwargs: dict[str, Any] = {"ssl_certfile": cert, "ssl_keyfile": key}
    if ca:
        kwargs["ssl_ca_certs"] = ca
        kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED
    return kwargs


def serve_http() -> None:
    if not mcp_http_enabled():
        raise SystemExit("MCP_HTTP_ENABLED is off")
    import uvicorn

    host = (os.getenv("MCP_HTTP_HOST") or "127.0.0.1").strip()
    port = int(os.getenv("MCP_HTTP_PORT") or "8081")
    uvicorn.run(build_app(), host=host, port=port, **ssl_kwargs())
