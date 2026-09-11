"""Making Agent Studio load-bearing instead of decorative.

The runtime has always preferred an authored graph and quietly run the built-in
Python script when there wasn't one. That fallback is why a card could look
authored, be edited, published, show a diff in the change log -- and change
nothing at all about what the caller heard. `kaia-v2-4` publishes the empty
sentinel today, so every demo call ran `voice/flows.py`, not the canvas.

`VOICE_FLOW_GRAPH=required` removes the quiet part. A bot with no published
graph, or one whose graph will not compile, refuses the call and names itself.

The cost is real and deliberate: under `required` a broken graph is a failed
call rather than a degraded one. That is the correct trade only once the graphs
are real, which is why it is a mode and not the default.
"""

from __future__ import annotations

import pytest

from voice import config as voice_config


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("VOICE_FLOW_GRAPH", raising=False)
    yield


SENTINEL = {"nodes": [], "edges": []}
AUTHORED = {
    "version": 1,
    "nodes": [
        {
            "id": "n_start",
            "key": "greet_disclose",
            "type": "conversation",
            "data": {"name": "Greet", "isStart": True, "instructions": "hi"},
            "position": {"x": 0, "y": 0},
        }
    ],
    "edges": [],
}


# --- the mode itself --------------------------------------------------------


def test_required_is_a_recognised_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_FLOW_GRAPH", "required")
    assert voice_config.voice_flow_graph() == "required"
    assert voice_config.voice_flow_required() is True


def test_every_mode_requires_a_published_graph() -> None:
    """There is nothing else to run. `voice/flows.py` was materialised into
    agent_core/cards/graphs/collections.json and deleted, so `auto` and `db`
    mean what `required` meant: a bot with no published, compilable graph
    refuses the call and names itself."""
    assert voice_config.voice_flow_graph() == "auto"
    assert voice_config.voice_flow_required() is True


def test_a_typo_does_not_take_voice_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """`requried` must degrade to `auto`, not to an unknown mode."""
    monkeypatch.setenv("VOICE_FLOW_GRAPH", "requried")
    assert voice_config.voice_flow_graph() == "auto"


@pytest.mark.parametrize("mode", ["legacy", "hub"])
def test_the_retired_modes_are_tolerated_and_logged(
    monkeypatch: pytest.MonkeyPatch, mode: str, caplog: pytest.LogCaptureFixture
) -> None:
    """A deployment that set the kill-switch keeps booting; the script it
    selected no longer exists, so the authored graph runs and the log says so."""
    monkeypatch.setenv("VOICE_FLOW_GRAPH", mode)
    with caplog.at_level("WARNING"):
        assert voice_config.voice_flow_graph() == "auto"
    assert any("retired" in r.getMessage() for r in caplog.records)
    assert voice_config.voice_uses_authored_flow(AUTHORED) is True


# --- what the graph check decides, and what it does not ---------------------


def test_an_authored_graph_is_recognised(monkeypatch: pytest.MonkeyPatch) -> None:
    assert voice_config.voice_uses_authored_flow(AUTHORED) is True


def test_the_sentinel_is_not_authored() -> None:
    """`{nodes: [], edges: []}` is genuinely not a graph.

    The refusal belongs at the call site, where there is a bot id to name --
    making this return True would compile an empty graph and fail later with a
    worse message.
    """
    assert voice_config.voice_uses_authored_flow(SENTINEL) is False


# --- the call site ----------------------------------------------------------


def test_run_bot_refuses_rather_than_falling_back() -> None:
    """Read the source: there is no fallback left to reach."""
    import inspect

    import voice.bot as bot

    src = inspect.getsource(bot.run_bot)
    assert "has no published Agent Studio" in src, "the refusal must name the problem"
    assert "falling back to the built-in flow" not in src
    assert "build_collections_flow" not in src


def test_the_error_names_the_bot() -> None:
    """"No flow" with no bot id is unactionable on a deployment with 13 cards."""
    import inspect

    import voice.bot as bot

    src = inspect.getsource(bot.run_bot)
    assert "bot {bot_id!r}" in src or "bot={}" in src


def test_the_python_script_is_gone() -> None:
    import importlib.util

    assert importlib.util.find_spec("voice.flows") is None
