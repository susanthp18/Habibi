"""A bot with no published graph refuses the call.

The runtime used to prefer an authored graph and quietly run a built-in
Python script when there was none, which is why a card could look authored,
be edited, published, show a diff in the change log -- and change nothing the
caller heard. The script is gone (the conversation is
agent_core/cards/graphs/collections.json, published like any other graph), so
a bot with no published, compilable graph refuses the call and names itself.
"""

from __future__ import annotations

import flow_graph

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


def test_an_authored_graph_is_recognised() -> None:
    assert flow_graph.is_authored(AUTHORED) is True


def test_the_sentinel_is_not_authored() -> None:
    """`{nodes: [], edges: []}` is genuinely not a graph.

    The refusal belongs at the call site, where there is a bot id to name --
    treating the sentinel as authored would compile an empty graph and fail
    later with a worse message.
    """
    assert flow_graph.is_authored(SENTINEL) is False
    assert flow_graph.is_authored({}) is False
    assert flow_graph.is_authored(None) is False


# --- the call site ----------------------------------------------------------


def test_run_bot_refuses_rather_than_falling_back() -> None:
    """Read the source: there is no fallback left to reach."""
    import inspect

    from voice import bot_flow

    src = inspect.getsource(bot_flow.build_flow)
    assert "has no published Agent Studio" in src, "the refusal must name the problem"
    assert "falling back to the built-in flow" not in src
    assert "build_collections_flow" not in src


def test_the_error_names_the_bot() -> None:
    """"No flow" with no bot id is unactionable on a deployment with 13 cards."""
    import inspect

    from voice import bot_flow

    src = inspect.getsource(bot_flow.build_flow)
    assert "bot {bot_id!r}" in src or "bot={}" in src


def test_the_python_script_is_gone() -> None:
    import importlib.util

    assert importlib.util.find_spec("voice.flows") is None
