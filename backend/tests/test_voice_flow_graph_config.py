"""VOICE_FLOW_GRAPH operator switch — no pipecat import."""

from __future__ import annotations

import pytest

import flow_graph as fg
from voice import config as voice_config


def test_flow_graph_defaults_to_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_FLOW_GRAPH", "")
    assert voice_config.voice_flow_graph() == "auto"


def test_the_retired_kill_switches_no_longer_select_a_script(monkeypatch: pytest.MonkeyPatch) -> None:
    """`legacy` and `hub` selected voice/flows.py, which is gone: an authored
    graph runs under either name, and a missing one is refused at the call
    site rather than replaced."""
    for mode in ("legacy", "hub"):
        monkeypatch.setenv("VOICE_FLOW_GRAPH", mode)
        assert voice_config.voice_flow_graph() == "auto"
        assert voice_config.voice_uses_authored_flow(fg.empty_graph().model_dump()) is True
        assert voice_config.voice_uses_authored_flow({}) is False


def test_auto_uses_authored_flow_when_the_graph_has_nodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOICE_FLOW_GRAPH", "auto")
    assert voice_config.voice_uses_authored_flow(fg.empty_graph().model_dump()) is True
    assert voice_config.voice_uses_authored_flow({}) is False
