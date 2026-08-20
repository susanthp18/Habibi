"""Implicit transitions — the hops the built-in tools perform.

An authored graph that uses reserved node keys inherits real transitions with
no authored edges: the materialised collections script has twelve nodes and
zero edges, and rendered as a pile of disconnected rectangles. These are
derived from ``voice/tools.py`` so the canvas can draw them without inventing
edges the runtime would then apply twice.
"""

from __future__ import annotations

import flow_graph


def test_known_hops_are_derived() -> None:
    t = flow_graph.implicit_transitions()
    assert t["begin_dispute"] == ["handle_dispute"]
    assert t["begin_negotiate"] == ["negotiate_ptp"]
    assert set(t["disclose_recording"]) == {"discover_intent", "verify_identity"}
    # Both of these await _close_probe_node(), which returns _node("pre_close")
    # when the caller still has something open — a second real destination, not
    # an artefact of following the call graph. This test asserted the single
    # target back when the reader could not see past the registered function.
    assert set(t["begin_wrap_up"]) == {"wrap_up", "pre_close"}
    assert set(t["end_call"]) == {"call_ended", "pre_close"}


def test_every_target_is_a_reserved_key() -> None:
    """A hop to a key the editor does not advertise is a trap: an author could
    never know to name a node that, and the transition would silently no-op."""
    targets = {n for hops in flow_graph.implicit_transitions().values() for n in hops}
    assert targets <= set(flow_graph.RESERVED_NODE_KEYS), sorted(
        targets - set(flow_graph.RESERVED_NODE_KEYS)
    )


def test_tools_that_do_not_move_are_absent() -> None:
    t = flow_graph.implicit_transitions()
    # A read is not a transition; drawing an edge for it would be a lie.
    assert "get_account_position" not in t
    assert "search_knowledge_base" not in t


def test_every_tool_named_is_in_the_catalog() -> None:
    """The canvas keys these against node.data.tools, which come from the
    catalog — a name that is in neither would draw nothing."""
    catalog = {t["key"] for t in flow_graph.tool_catalog()}
    assert set(flow_graph.implicit_transitions()) <= catalog


def test_the_built_in_graph_gains_edges_from_this() -> None:
    """The point of the whole thing: the exported script stops being a pile of
    disconnected boxes."""
    from voice.flow_export import built_in_collections_graph

    graph = built_in_collections_graph()
    hops = flow_graph.implicit_transitions()
    by_key = {n["key"] for n in graph["nodes"]}
    drawn = {
        (n["key"], target)
        for n in graph["nodes"]
        for tool in n["data"]["tools"]
        for target in hops.get(tool, [])
        if target in by_key
    }
    assert ("greet_disclose", "discover_intent") in drawn
    assert ("state_position", "handle_dispute") in drawn
    assert len(drawn) >= 6, sorted(drawn)


def test_result_is_cached_and_stable() -> None:
    assert flow_graph.implicit_transitions() is flow_graph.implicit_transitions()


def test_delegating_tools_are_followed_to_their_handler() -> None:
    """Most tools are thin wrappers. The registry binds "escalate_to_human" to a
    function that calls _escalate_to_human_handler, and the helper owns the
    _node() call — so reading only the registered function found 8 of the real
    transitions and drew escalate_close as an orphan on the canvas."""
    transitions = flow_graph.implicit_transitions()

    assert transitions["escalate_to_human"] == ["escalate_close"]
    assert transitions["flag_dispute"] == ["escalate_close"]
    assert transitions["capture_call_goal"] == ["verify_identity"]
    assert "terminate_politely" in transitions["verify_identity"]


def test_a_tool_bound_by_a_factory_is_still_read() -> None:
    """`capture_call_goal = _spec("capture_call_goal", _capture_call_goal_handler)`
    binds a name the AST never sees as a function. Any function handed to the
    factory counts as its delegate, so renaming the factory cannot break this."""
    assert flow_graph.implicit_transitions().get("capture_call_goal")


def test_a_node_key_held_in_a_parameter_default_is_resolved() -> None:
    """return_to_position calls _node(hub_node), and hub_node is a parameter
    defaulting to "state_position". A literals-only reader drew the busiest node
    in the graph with nothing pointing at it."""
    transitions = flow_graph.implicit_transitions()

    assert transitions["return_to_position"] == ["state_position"]
    assert "state_position" in transitions["verify_identity"]


def test_every_reserved_key_except_the_hub_variant_has_an_inbound_tool() -> None:
    """RESERVED_NODE_KEYS documents what the built-in tools transition to, so a
    key nothing reaches means either the docs or the reader is wrong.
    collections_hub is the exception by design — it replaces state_position only
    under VOICE_FLOW_GRAPH=hub."""
    reached = {t for targets in flow_graph.implicit_transitions().values() for t in targets}

    assert set(flow_graph.RESERVED_NODE_KEYS) - reached == {"collections_hub"}
