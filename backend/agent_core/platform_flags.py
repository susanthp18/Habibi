"""Named flags for the agent factory.

All default **off**. Later phases turn a flag on after its eval + SLO gate.
Do not invent a new name in a feature PR — add it here and in ``.env.example``.
"""

from __future__ import annotations

import os

_TRUE = frozenset({"1", "true", "yes", "on"})


def _flag(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in _TRUE


def agent_cards_enabled() -> bool:
    return _flag("AGENT_CARDS_ENABLED")


def mcp_http_enabled() -> bool:
    return _flag("MCP_HTTP_ENABLED")


def mcp_client_enabled() -> bool:
    return _flag("MCP_CLIENT_ENABLED")


def mcp_tasks_enabled() -> bool:
    return _flag("MCP_TASKS_ENABLED")


def mcp_apps_enabled() -> bool:
    return _flag("MCP_APPS_ENABLED")


def a2a_enabled() -> bool:
    return _flag("A2A_ENABLED")


def eval_gate_enabled() -> bool:
    return _flag("EVAL_GATE_ENABLED")


def redteam_gate_enabled() -> bool:
    return _flag("REDTEAM_GATE_ENABLED")


def llm_gateway_enabled() -> bool:
    return _flag("LLM_GATEWAY_ENABLED")


def vision_ingest_enabled() -> bool:
    return _flag("VISION_INGEST_ENABLED")


def temporal_enabled() -> bool:
    return _flag("TEMPORAL_ENABLED")


def policy_export_enabled() -> bool:
    return _flag("POLICY_EXPORT_ENABLED")
