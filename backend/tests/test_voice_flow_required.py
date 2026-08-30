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


def test_the_default_is_still_the_forgiving_one() -> None:
    """Unset must not start refusing calls on somebody else's deployment."""
    assert voice_config.voice_flow_graph() == "auto"
    assert voice_config.voice_flow_required() is False


def test_a_typo_does_not_take_voice_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """`requried` must degrade to `auto`, not to "refuse everything"."""
    monkeypatch.setenv("VOICE_FLOW_GRAPH", "requried")
    assert voice_config.voice_flow_graph() == "auto"
    assert voice_config.voice_flow_required() is False


@pytest.mark.parametrize("mode", ["legacy", "hub"])
def test_the_kill_switches_still_win(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """`legacy` remains the escape hatch and must not be overridden by strictness."""
    monkeypatch.setenv("VOICE_FLOW_GRAPH", mode)
    assert voice_config.voice_uses_authored_flow(AUTHORED) is False
    assert voice_config.voice_flow_required() is False


# --- what `required` decides, and what it does not --------------------------


def test_required_still_runs_a_real_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_FLOW_GRAPH", "required")
    assert voice_config.voice_uses_authored_flow(AUTHORED) is True


def test_required_does_not_pretend_the_sentinel_is_authored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`{nodes: [], edges: []}` is genuinely not a graph.

    The refusal belongs at the call site, where there is a bot id to name --
    making this return True would compile an empty graph and fail later with a
    worse message.
    """
    monkeypatch.setenv("VOICE_FLOW_GRAPH", "required")
    assert voice_config.voice_uses_authored_flow(SENTINEL) is False


def test_the_sandbox_override_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-call override is how the studio previews a graph; strictness must
    not silently ignore it."""
    monkeypatch.setenv("VOICE_FLOW_GRAPH", "required")
    assert voice_config.voice_uses_authored_flow(AUTHORED, override="legacy") is False


# --- the call site ----------------------------------------------------------


def test_run_bot_refuses_rather_than_falling_back() -> None:
    """Read the source: the fallback must be unreachable under `required`."""
    import inspect

    import voice.bot as bot

    src = inspect.getsource(bot.run_bot)
    assert "voice_flow_required()" in src, "the mode has to be consulted at the call site"
    assert "has no published Agent Studio" in src, "the refusal must name the problem"
    # The compile-failure path must re-raise instead of degrading.
    fallback = src.index("falling back to the built-in flow")
    guard = src.rindex("voice_flow_required()", 0, fallback)
    assert "raise" in src[guard:fallback], (
        "a graph that will not compile must refuse under `required`, not degrade"
    )


def test_the_error_names_the_bot() -> None:
    """"No flow" with no bot id is unactionable on a deployment with 13 cards."""
    import inspect

    import voice.bot as bot

    src = inspect.getsource(bot.run_bot)
    assert "bot {bot_id!r}" in src or "bot={}" in src
