"""Agent-factory flag names are locked. All default off."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_core import platform_flags as flags

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "fn",
    [
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
        flags.outbound_eval_gate_enabled,
        flags.campaign_runtime_enabled,
    ],
)
def test_factory_flags_default_off(fn, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
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
        "OUTBOUND_EVAL_GATE_ENABLED",
        "CAMPAIGN_RUNTIME_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    assert fn() is False


def test_flag_turns_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_HTTP_ENABLED", "true")
    assert flags.mcp_http_enabled() is True


def test_every_flag_is_documented_in_env_example() -> None:
    """The module docstring says "add it here and in .env.example". Enforce it.

    Nothing checked that, so the two drifted in both directions:
    AGENT_CARDS_ENABLED outlived its last reader and stayed in both files, while
    OUTBOUND_EVAL_GATE_ENABLED and CAMPAIGN_RUNTIME_ENABLED were added to the
    module without joining the locked list here. A flag list nobody can trust is
    worse than no list, because it is read as a contract.
    """
    import inspect
    import re

    source = inspect.getsource(flags)
    declared = set(re.findall(r'_flag\("([A-Z_]+)"\)', source))
    assert declared, "no flags found - the parser is wrong, not the module"

    env = (BACKEND / ".env.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"^([A-Z_]+)=", env, re.M))
    missing = sorted(declared - documented)
    assert not missing, f"declared in platform_flags but undocumented: {missing}"


def test_the_locked_list_covers_every_flag_the_module_declares() -> None:
    """The parametrize above is the contract; it must not lag the module."""
    import inspect
    import re

    declared = set(re.findall(r'_flag\("([A-Z_]+)"\)', inspect.getsource(flags)))
    locked = set(re.findall(r'"([A-Z_]+)"', inspect.getsource(test_factory_flags_default_off)))
    missing = sorted(declared - locked)
    assert not missing, f"flags missing from the locked list: {missing}"
