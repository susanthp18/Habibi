"""The door graph the seeder authors.

Nine of its ten nodes are derived and `test_flow_export.py` already pins those.
What is worth a test here is the tenth, because it is the only hand-written node
in the Door and it exists to close a specific hole: with no `state_position` in
the door's own namespace, a successful verification resolves through
`resolve_key`'s third tier into `kaia-v2-4/state_position` and crosses a member
boundary with no ledger row, no carry packet and no hop-cap decrement.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pipecat.flows")

from scripts.seed_door_graph import _ROUTE_NODE, door_graph  # noqa: E402


@pytest.fixture(scope="module")
def graph() -> dict:
    return door_graph()


def test_the_door_owns_the_hub_key_build_tools_defaults_to(graph: dict) -> None:
    """`build_tools(hub_node="state_position")` and flows_dynamic never overrides it."""
    from voice.tools import build_tools
    import inspect

    default = inspect.signature(build_tools).parameters["hub_node"].default
    assert default == "state_position"
    assert default in {n["key"] for n in graph["nodes"]}


def test_the_route_node_can_only_route(graph: dict) -> None:
    """Its business surface is the handoff and nothing else.

    A door that could negotiate or take a payment is not a door. The derived
    node under this key is the collections hub and carries begin_negotiate /
    begin_dispute / begin_wrap_up, which is exactly why this one is authored.
    """
    node = next(n for n in graph["nodes"] if n["key"] == "state_position")
    assert node["data"]["tools"] == ["handoff_to_agent"]


def test_the_route_node_is_not_the_start_and_does_not_end_the_call(graph: dict) -> None:
    node = next(n for n in graph["nodes"] if n["key"] == "state_position")
    assert node["data"]["isStart"] is False
    assert node["data"]["endConversation"] is False
    assert {n["key"] for n in graph["nodes"] if n["data"]["isStart"]} == {"greet_disclose"}


def test_the_door_does_not_claim_collections_outbound_missions(graph: dict) -> None:
    """`confirm_identity` advertises four cadences the door has no way to run."""
    assert all(not n["data"]["entryFor"] for n in graph["nodes"])


def test_the_graph_validates(graph: dict) -> None:
    import flow_graph

    result = flow_graph.validate_graph(
        flow_graph.parse_graph(graph),
        known_tools=[t["key"] for t in flow_graph.tool_catalog()],
    )
    assert result.ok, [i.message for i in result.issues if i.severity == "error"]


def test_node_keys_are_unique(graph: dict) -> None:
    """The authored node is appended to a derived list -- a duplicate key would
    make `resolve_key` ambiguous, which returns None and strands the caller."""
    keys = [n["key"] for n in graph["nodes"]]
    assert len(keys) == len(set(keys))
    ids = [n["id"] for n in graph["nodes"]]
    assert len(ids) == len(set(ids))


def test_the_route_node_sits_where_the_hub_sits_in_the_full_graph() -> None:
    from voice.flow_export import built_in_collections_graph

    hub = next(n for n in built_in_collections_graph()["nodes"] if n["key"] == "state_position")
    assert _ROUTE_NODE["position"] == hub["position"]
