"""JSON-RPC MCP dispatcher. Used by the out-of-process HTTP server.

Not mounted on FastAPI. Cursor/Claude speak this over POST /mcp.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import mcp_tools
from agent_core.mcp_http import prompts, resources, tasks
from agent_core.mcp_http.auth import resource_allowed, tool_allowed
from agent_core.platform_flags import mcp_apps_enabled, mcp_tasks_enabled
from agent_core.tools.catalog import CATALOG
from agent_core.tools.schema import CHANNEL_MCP

PROTOCOL_VERSION = "2025-11-25"


def tools_list_payload(principal: dict[str, Any], *, ttl_ms: int = 30_000) -> dict[str, Any]:
    tools = []
    for tool in mcp_tools.list_tools():
        if tool_allowed(principal, tool["name"]):
            tools.append(tool)
    if mcp_tasks_enabled() and tool_allowed(principal, "enqueue_task"):
        tools.append(
            {
                "name": "enqueue_task",
                "description": "Queue statement/bureau work. Returns a ticket id. Does not block.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "customer_id": {"type": "string"},
                        "kind": {"type": "string", "enum": sorted(tasks.ALLOWED_KINDS)},
                        "doc_type": {"type": "string"},
                    },
                    "required": ["customer_id", "kind"],
                },
            }
        )
    return {"tools": tools, "_meta": {"ttlMs": ttl_ms}}


def handle_rpc(method: str, params: dict[str, Any] | None, principal: dict[str, Any]) -> Any:
    params = params or {}
    if method in {"initialize", "notifications/initialized"}:
        if method == "notifications/initialized":
            return None
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {},
                "prompts": {},
                "tasks": {"listChanged": False} if mcp_tasks_enabled() else {},
            },
            "serverInfo": {"name": "bigbound-collections", "version": "3.0.0"},
        }
    if method in {"ping", "notifications/cancelled"}:
        return {}
    if method == "tools/list":
        return tools_list_payload(principal)
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if name in mcp_tools.DENIED:
            raise PermissionError("mutating_tools_denied")
        if not tool_allowed(principal, name):
            raise PermissionError("scope_denied")
        if name == "enqueue_task":
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            tasks.enqueue(
                                kind=str(arguments.get("kind") or ""),
                                customer_id=str(arguments.get("customer_id") or "") or None,
                                payload={"doc_type": arguments.get("doc_type")},
                            ),
                            default=str,
                        ),
                    }
                ]
            }
        spec = CATALOG.get(name)
        if spec is None or CHANNEL_MCP not in spec.channels:
            raise PermissionError("unknown_or_unavailable_tool")
        result = mcp_tools.call_tool(name, arguments)
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
    if method == "resources/list":
        listed = []
        for item in resources.list_resources():
            scheme = urlparse(item["uri"].split("{")[0]).scheme or item["uri"].split(":")[0]
            if resource_allowed(principal, scheme):
                listed.append(item)
        if mcp_apps_enabled():
            from agent_core.mcp_http.apps import list_apps

            listed.extend(
                {"uri": a["uri"], "name": a["title"], "description": a["description"]}
                for a in list_apps()
            )
        return {"resources": listed}
    if method == "resources/read":
        uri = str(params.get("uri") or "")
        if mcp_apps_enabled() and uri.startswith("ui://"):
            from agent_core.mcp_http.apps import app_resource

            return {"contents": [app_resource(uri)]}
        scheme = urlparse(uri).scheme
        if not resource_allowed(principal, scheme):
            raise PermissionError("scope_denied")
        payload = resources.read_resource(uri)
        return {"contents": [{"uri": uri, "mimeType": "application/json", "text": resources.as_text(payload)}]}
    if method == "prompts/list":
        return {"prompts": prompts.list_prompts()}
    if method == "prompts/get":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        got = prompts.get_prompt(name, arguments)
        return got
    if method == "tasks/get" and mcp_tasks_enabled():
        row = tasks.get_task(str(params.get("id") or ""))
        if not row:
            raise KeyError("task_not_found")
        return row
    if method.startswith("notifications/"):
        return None
    if mcp_apps_enabled() and method == "ui/list":
        from agent_core.mcp_http.apps import list_apps
        return {"apps": list_apps()}
    if mcp_apps_enabled() and method.startswith("ui/"):
        raise KeyError(f"method_not_found:{method}")
    raise KeyError(f"method_not_found:{method}")
