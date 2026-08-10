"""MCP server for the collections tool catalog. Runs OUT OF PROCESS.

    python -m mcp_server

Deliberately not mounted on the FastAPI app, for three independent reasons:

1. ``ApiKeyMiddleware`` is a ``BaseHTTPMiddleware``, which does not cleanly
   support ASGI SSE/WebSocket scopes — the reason ``/ws`` had to be added to
   ``_AUTH_EXEMPT_PREFIXES`` in the first place.
2. ``GZipMiddleware(minimum_size=1024)`` sits *inside* the auth middleware and
   would compress and buffer a ``text/event-stream``.
3. Exempting ``/mcp`` from auth to work around (1) would put CRM tools on the
   public API unauthenticated — the exact bug the comment at ``main.py`` warns
   about.

The ``voice.host.register_routes(app)`` precedent does not apply: those are
plain request/response signalling routes, not a streaming protocol.

The ``mcp`` SDK is an optional dependency (``requirements-mcp.txt``) so the API
image does not grow for a surface it does not serve — the same split as
``requirements-voice.txt``.

Transport defaults to stdio, where the process boundary is the auth boundary.
``MCP_API_KEY`` is required before any network transport is allowed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)


def _transport() -> str:
    return (os.getenv("MCP_TRANSPORT") or "stdio").strip().lower()


async def _serve() -> None:
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import TextContent, Tool
    except ImportError:  # pragma: no cover - optional dependency
        raise SystemExit(
            "The `mcp` package is not installed. Install it with:\n"
            "    pip install -r requirements-mcp.txt"
        )

    import json

    import mcp_tools

    server = Server("bigbound-collections")

    @server.list_tools()
    async def _list() -> list[Tool]:
        return [
            Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["inputSchema"],
            )
            for t in mcp_tools.list_tools()
        ]

    @server.call_tool()
    async def _call(name: str, arguments: dict) -> list[TextContent]:
        # to_thread: every handler underneath is synchronous SQLAlchemy, and
        # blocking the MCP event loop would stall concurrent requests.
        try:
            result = await asyncio.to_thread(mcp_tools.call_tool, name, arguments)
        except mcp_tools.McpToolError as exc:
            # Returned as content rather than raised: a caller mistake is
            # information the agent can act on, not a transport failure.
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]
        return [TextContent(type="text", text=json.dumps(result, default=str))]

    transport = _transport()
    if transport != "stdio":
        raise SystemExit(
            f"MCP_TRANSPORT={transport} is not supported yet. Only stdio is "
            "implemented — a network transport needs an auth story reviewed "
            "alongside it (see the module docstring)."
        )

    logger.info("mcp server starting on stdio · tools=%s", len(mcp_tools.list_tools()))
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), stream=sys.stderr)
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
