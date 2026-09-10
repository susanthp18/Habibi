"""Named flags for the agent factory.

All default **off**. Later phases turn a flag on after its eval + SLO gate.
Do not invent a new name in a feature PR — add it here and in ``.env.example``.
"""

from __future__ import annotations

from env_utils import env_bool as _flag


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


def fleet_enabled() -> bool:
    """Phase-1 compiled bundle is loaded and compared either way.

    Off (default): production still uses the live grant/prompt path; mismatches
    are logged. On: the persisted artefact is the mouth. Do not turn this on
    until one-member parity is measured green.
    """
    return _flag("FLEET_ENABLED")


def door_enabled() -> bool:
    """Whether authored ``entry_bindings`` decide which card answers.

    Off (default): ``resolve_entry`` falls back to ``runtime_entry_bot_id`` and
    every inbound contact lands on the tenant default, exactly as today. On: the
    dialled number chooses. Read per call rather than cached, so unsetting it is
    a complete rollback with no restart and no data to undo.

    ``agent_core.cards.routing.door_enabled`` is the caller-facing name and
    delegates here; this module is where the flag is *declared*, alongside
    ``FLEET_ENABLED`` which it is meaningless without.
    """
    return _flag("DOOR_ENABLED")


def eval_gate_enabled() -> bool:
    return _flag("EVAL_GATE_ENABLED")


def redteam_gate_enabled() -> bool:
    return _flag("REDTEAM_GATE_ENABLED")


def llm_gateway_enabled() -> bool:
    return _flag("LLM_GATEWAY_ENABLED")


def vision_ingest_enabled() -> bool:
    return _flag("VISION_INGEST_ENABLED")


def policy_export_enabled() -> bool:
    return _flag("POLICY_EXPORT_ENABLED")


def outbound_eval_gate_enabled() -> bool:
    """G-OB9: block an outbound publish without a passing outbound eval suite.

    Off by default like every other gate flag, and for the same reason — a
    module landing in a repository must not change what an existing deployment
    can publish. Turning it on is the step that makes "nobody asked to be
    called" an enforced property rather than an intention.
    """
    return _flag("OUTBOUND_EVAL_GATE_ENABLED")


def campaign_runtime_enabled() -> bool:
    """The cadence executor and campaign dialer. Off means nothing dials."""
    return _flag("CAMPAIGN_RUNTIME_ENABLED")
