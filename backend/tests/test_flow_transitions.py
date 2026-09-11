"""Implicit transitions — the hops the built-in tools perform.

An authored graph that uses reserved node keys inherits real transitions with
no authored edges: the materialised collections script has twelve nodes and
zero edges, and rendered as a pile of disconnected rectangles. The hops are
*declared* in ``flow_graph.TRANSITIONS`` — one map the canvas, the walker and
the validator read — and ``test_transitions_are_declared.py`` proves the
handlers in ``voice/tools.py`` agree with it.
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


def test_the_result_is_a_copy_the_caller_may_mutate() -> None:
    """Lists, as the canvas endpoint was built against; and a fresh copy each
    time, so nothing a consumer does to it can reach the declaration."""
    first = flow_graph.implicit_transitions()
    first["begin_dispute"].append("nowhere")
    assert flow_graph.implicit_transitions()["begin_dispute"] == ["handle_dispute"]


def test_the_transitioning_flag_is_derived_from_the_map() -> None:
    """The hand-kept `_TRANSITIONING_TOOLS` had drifted to 12 of 16 — the
    canvas showed `flag_dispute` and `request_callback` as tools that stay put.
    Derived, it cannot."""
    rows = {t["key"]: t for t in flow_graph.tool_catalog()}
    for tool in flow_graph.TRANSITIONS:
        assert rows[tool]["transitions"] is True, tool
    assert rows["get_account_position"]["transitions"] is False


def test_every_reserved_key_except_the_hub_variant_has_an_inbound_tool() -> None:
    """RESERVED_NODE_KEYS documents what the built-in tools transition to, so a
    key nothing reaches means either the docs or the reader is wrong.
    collections_hub is the exception by design — it replaces state_position only
    under VOICE_FLOW_GRAPH=hub."""
    reached = {t for targets in flow_graph.implicit_transitions().values() for t in targets}

    assert set(flow_graph.RESERVED_NODE_KEYS) - reached == {"collections_hub"}


# ---------------------------------------------------------------------------
# The text channel: what a step's exits are, and which steps are passed through
# ---------------------------------------------------------------------------


def _node(key: str, *, tools: list[str] | None = None, start: bool = False, end: bool = False) -> dict:
    return {
        "id": f"n-{key}",
        "key": key,
        "type": "conversation",
        "data": {"isStart": start, "tools": tools or [], "endConversation": end, "entryFor": []},
    }


def _walker(nodes: list[dict]):
    from flow_vars import FlowVariables
    from flow_walk import FlowWalker

    return FlowWalker(
        flow_graph.parse_graph({"version": 1, "globalTools": [], "nodes": nodes, "edges": []}),
        FlowVariables({}),
    )


def test_the_greeting_is_passed_through_on_text() -> None:
    """Its only exit is `disclose_recording`, a voice verb with one declared
    destination. A WhatsApp thread has no recording to disclose, so it starts
    where the disclosure would have led."""
    walker = _walker(
        [
            _node("greet_disclose", tools=["disclose_recording"], start=True),
            _node("discover_intent", tools=["capture_call_goal"]),
            _node("verify_identity", tools=["verify_identity"]),
        ]
    )
    granted = {"capture_call_goal", "verify_identity"}  # no flow verbs on text
    assert walker.text_exits(granted=granted)["pass_through"] == ["discover_intent"]
    assert walker.pass_through(granted=granted) == ["greet_disclose"]
    assert walker.current.key == "discover_intent"
    # And it stops there: capture_call_goal is a granted mover, a real choice.
    assert walker.pass_through(granted=granted) == []


def test_a_step_whose_voice_exits_disagree_is_not_guessed() -> None:
    """`pre_close` leaves through `return_to_position` (the hub) or `end_call`
    (the end). Two destinations is a choice the graph did not make for text."""
    walker = _walker(
        [
            _node("pre_close", tools=["return_to_position", "end_call"], start=True),
            _node("state_position"),
            _node("call_ended", end=True),
        ]
    )
    assert walker.text_exits(granted=set())["pass_through"] == []
    assert walker.pass_through(granted=set()) == []
    assert walker.current.key == "pre_close"


def test_a_handoff_is_an_exit_and_an_ending_step_is_not_stuck() -> None:
    walker = _walker(
        [
            _node("greet_disclose", tools=["disclose_recording"], start=True),
            _node("discover_intent", tools=["capture_call_goal"]),
            _node("verify_identity", tools=["verify_identity"]),
            _node("state_position", tools=["handoff_to_agent"]),
            _node("terminate_politely", end=True),
            # Reached only by `not_account_holder`, a voice verb: not a text problem.
            _node("third_party"),
        ]
    )
    granted = {"capture_call_goal", "verify_identity", "handoff_to_agent"}
    reachable, stuck = walker.text_reachable(granted=granted, handoffs=True)
    assert reachable == {"greet_disclose", "discover_intent", "verify_identity", "state_position", "terminate_politely"}
    assert stuck == []
    # Without a handoff to make, the route node is where the thread stops.
    _reachable, stuck = walker.text_reachable(granted=granted, handoffs=False)
    assert stuck == ["state_position"]
