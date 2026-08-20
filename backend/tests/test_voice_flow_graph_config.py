"""VOICE_FLOW_GRAPH operator switch — no pipecat import."""

from __future__ import annotations

import pytest

import flow_graph as fg
from voice import config as voice_config


def test_flow_graph_defaults_to_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_FLOW_GRAPH", "")
    assert voice_config.voice_flow_graph() == "auto"


def test_legacy_is_the_authored_flow_kill_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_FLOW_GRAPH", "legacy")
    graph = fg.empty_graph().model_dump()
    assert voice_config.voice_uses_authored_flow(graph) is False


def test_hub_is_the_hardcoded_hub_kill_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_FLOW_GRAPH", "hub")
    graph = fg.empty_graph().model_dump()
    assert voice_config.voice_uses_authored_flow(graph) is False


def test_auto_uses_authored_flow_when_the_graph_has_nodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOICE_FLOW_GRAPH", "auto")
    assert voice_config.voice_uses_authored_flow(fg.empty_graph().model_dump()) is True
    assert voice_config.voice_uses_authored_flow({}) is False
