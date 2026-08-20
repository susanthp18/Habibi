"""MCP Apps — read-mostly UI for handoff prep and PTP confirm.

Served by the out-of-process MCP HTTP server, never FastAPI. Habibi only
shows status.
"""

from __future__ import annotations

from typing import Any

APPS = (
    {
        "id": "handoff-prep",
        "title": "Handoff prep",
        "description": "Read-only brief for a warm transfer. Does not write CRM.",
        "uri": "ui://handoff-prep",
    },
    {
        "id": "ptp-confirm",
        "title": "PTP confirm",
        "description": "Confirm a promise amount and date before the mouth speaks it.",
        "uri": "ui://ptp-confirm",
    },
)


def list_apps() -> list[dict[str, Any]]:
    return [dict(a) for a in APPS]


def app_resource(uri: str) -> dict[str, Any]:
    if uri == "ui://handoff-prep":
        return {
            "uri": uri,
            "mimeType": "application/json",
            "text": '{"title":"Handoff prep","fields":["customer","dpd","lastPromise","authority"],"readonly":true}',
        }
    if uri == "ui://ptp-confirm":
        return {
            "uri": uri,
            "mimeType": "application/json",
            "text": '{"title":"PTP confirm","fields":["amount","date","channel"],"readonly":true}',
        }
    raise KeyError("mcp_app_not_found")
