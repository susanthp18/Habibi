"""Agent-factory flag names are locked. All default off."""

from __future__ import annotations

import pytest

from agent_core import platform_flags as flags


@pytest.mark.parametrize(
    "fn",
    [
        flags.agent_cards_enabled,
        flags.mcp_http_enabled,
        flags.mcp_client_enabled,
        flags.mcp_tasks_enabled,
        flags.mcp_apps_enabled,
        flags.a2a_enabled,
        flags.eval_gate_enabled,
        flags.redteam_gate_enabled,
        flags.llm_gateway_enabled,
        flags.vision_ingest_enabled,
        flags.temporal_enabled,
        flags.policy_export_enabled,
    ],
)
def test_factory_flags_default_off(fn, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AGENT_CARDS_ENABLED",
        "MCP_HTTP_ENABLED",
        "MCP_CLIENT_ENABLED",
        "MCP_TASKS_ENABLED",
        "MCP_APPS_ENABLED",
        "A2A_ENABLED",
        "EVAL_GATE_ENABLED",
        "REDTEAM_GATE_ENABLED",
        "LLM_GATEWAY_ENABLED",
        "VISION_INGEST_ENABLED",
        "TEMPORAL_ENABLED",
        "POLICY_EXPORT_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    assert fn() is False


def test_flag_turns_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_CARDS_ENABLED", "true")
    assert flags.agent_cards_enabled() is True
