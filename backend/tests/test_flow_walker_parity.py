"""The walker and the audio path agree about the graph.

``flow_walk`` exists so the text mouths stop guessing at a script the voice
mouth already runs. The whole value of that is parity, and parity that is not
pinned drifts — the audit counted 20 duplicated vocabularies in this tree and
found that every one given a drift test held, while every one without had
already separated.

So these are the assertions that fail if the two ever disagree: the names and
descriptions the model is offered, the order the offer is built in, and the
node a transition lands on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flow_graph import parse_graph
from flow_vars import FlowVariables
from flow_walk import EXTRACT_TOOL, TRANSITION_PREFIX, FlowWalker, entry_node

BASE = Path(__file__).resolve().parent.parent


def _builtin():
    # The one conversation definition (a stale copy of it used to sit at the
    # backend root, predating FLOW-2's terminals).
    from voice.flow_export import built_in_collections_graph

    return parse_graph(built_in_collections_graph())


def _walker(graph=None, **kw):
    return FlowWalker(graph or _builtin(), FlowVariables({}), **kw)


def test_the_built_in_script_walks_from_the_greeting_to_a_negotiation() -> None:
    """The materialised collections script has zero authored edges.

    It moves entirely through built-in tool hops, so a walker that only honoured
    authored edges would greet the caller and then sit on ``greet_disclose``
    forever. That was the behaviour before ``_implicit_target`` existed, and it
    is the single most important thing this test holds down.
    """
    w = _walker()
    assert w.current.key == "greet_disclose"
    hops = ["disclose_recording", "capture_call_goal", "verify_identity", "begin_negotiate"]
    landed = [w.advance(tool).key for tool in hops]
    assert landed == ["discover_intent", "verify_identity", "state_position", "negotiate_ptp"]


def test_a_read_is_not_a_transition() -> None:
    """Drawing an edge for a read would be a lie, and walking one would be worse."""
    w = _walker()
    w.advance("disclose_recording")
    w.advance("capture_call_goal")
    w.advance("verify_identity")
    assert w.current.key == "state_position"
    assert w.advance("get_account_position") is None
    assert w.current.key == "state_position"


def test_a_fallback_chain_takes_the_first_target_that_exists() -> None:
    """``disclose_recording`` is ``_node("discover_intent") or _node("verify_identity")``.

    The derived hop list is in source order, so "first present in the graph" is
    not an approximation of that rule — it is that rule.
    """
    import flow_graph

    assert flow_graph.implicit_transitions()["disclose_recording"] == [
        "discover_intent",
        "verify_identity",
    ]
    graph = _builtin()
    # A graph missing the first target must fall through to the second, exactly
    # as the `or` does when an older node registry returns None.
    graph.nodes = [n for n in graph.nodes if n.key != "discover_intent"]
    w = _walker(graph)
    assert w.advance("disclose_recording").key == "verify_identity"


def test_offers_drop_a_tool_the_card_cannot_grant() -> None:
    """The node names a tool; the card decides whether it is offered at all.

    A node may reference a tool the author later removed from the card. The
    voice path drops it at the registry lookup, and announcing it on text would
    be the studio promising a capability the runtime would refuse.
    """
    w = _walker()
    w.advance("disclose_recording")
    w.advance("capture_call_goal")
    w.advance("verify_identity")
    w.advance("begin_negotiate")
    assert "create_promise_to_pay" in w.offers()
    assert w.offers(granted={"create_promise_to_pay"}) == ["create_promise_to_pay"]
    assert w.offers(granted=set()) == []


def test_a_generated_transition_is_never_filtered_by_the_grant() -> None:
    """The grant says what the agent may *do*; the graph says where it may go.

    An author who drew the edge authorised the move, so a ``go_to_*`` survives
    an empty grant — otherwise a card with a narrow grant could never leave its
    first node.
    """
    graph = parse_graph(
        {
            "version": 1,
            "globalTools": [],
            "nodes": [
                {"id": "a", "key": "a", "data": {"name": "A", "isStart": True, "tools": ["end_call"]}},
                {"id": "b", "key": "b", "data": {"name": "B"}},
            ],
            "edges": [
                {
                    "id": "e",
                    "source": "a",
                    "target": "b",
                    "data": {"condition": {"type": "prompt", "prompt": "the caller agrees"}},
                }
            ],
        }
    )
    w = _walker(graph)
    assert w.offers(granted=set()) == [f"{TRANSITION_PREFIX}b"]
    assert w.advance(f"{TRANSITION_PREFIX}b").key == "b"


def test_the_authors_condition_text_is_the_description() -> None:
    """It is what the model reads to decide, so it must survive to both mouths."""
    graph = parse_graph(
        {
            "version": 1,
            "globalTools": [],
            "nodes": [
                {"id": "a", "key": "a", "data": {"name": "A", "isStart": True}},
                {"id": "b", "key": "b", "data": {"name": "Bee"}},
                {"id": "c", "key": "c", "data": {"name": "Cee"}},
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": "a",
                    "target": "b",
                    "data": {"condition": {"type": "prompt", "prompt": "they want to pay"}},
                },
                {
                    "id": "e2",
                    "source": "a",
                    "target": "c",
                    "data": {"condition": {"type": "prompt", "prompt": ""}},
                },
            ],
        }
    )
    assert _walker(graph).transitions() == [
        (f"{TRANSITION_PREFIX}b", "they want to pay"),
        # An undescribed choice is one the model cannot make on purpose, so the
        # target's display name stands in rather than an empty string.
        (f"{TRANSITION_PREFIX}c", "Move to Cee"),
    ]


def test_an_end_node_offers_nothing() -> None:
    graph = parse_graph(
        {
            "version": 1,
            "globalTools": [],
            "nodes": [
                {"id": "a", "key": "a", "type": "end", "data": {"name": "A", "isStart": True}}
            ],
            "edges": [],
        }
    )
    assert _walker(graph).offers() == []


def test_a_captured_boolean_satisfies_an_equals_true_edge() -> None:
    """The FLOW-5 fix, asserted through the walker.

    ``extract_details`` stored ``str(value)``, so a JSON ``true`` became
    ``"True"`` while ``identity_verified`` was deliberately lower-cased — and an
    authored ``equals true`` edge could never fire. A second reader of the
    variable bag is exactly where that would come back.
    """
    graph = parse_graph(
        {
            "version": 1,
            "globalTools": [],
            "nodes": [
                {
                    "id": "a",
                    "key": "a",
                    "data": {
                        "name": "A",
                        "isStart": True,
                        "extractVariables": [{"key": "agreed", "type": "boolean"}],
                    },
                },
                {"id": "b", "key": "b", "data": {"name": "B"}},
            ],
            "edges": [
                {
                    "id": "e",
                    "source": "a",
                    "target": "b",
                    "data": {
                        "condition": {
                            "type": "expression",
                            "clauses": [
                                {"variable": "agreed", "operator": "equals", "value": "true"}
                            ],
                        }
                    },
                }
            ],
        }
    )
    w = _walker(graph)
    assert w.offers() == [EXTRACT_TOOL]
    assert w.extract_properties() == {"agreed": {"type": "boolean"}}
    assert w.capture({"agreed": True, "not_declared": "x"}) == ["agreed"]
    assert w.advance().key == "b"


def test_an_unknown_transition_target_moves_nothing() -> None:
    w = _walker()
    assert w.advance(f"{TRANSITION_PREFIX}no_such_node") is None
    assert w.current.key == "greet_disclose"


@pytest.mark.parametrize(
    "objective,entry_key,expected",
    [
        (None, None, "greet_disclose"),
        (None, "negotiate_ptp", "negotiate_ptp"),
        (None, "no_such_node", "greet_disclose"),
        ("inbound", None, "greet_disclose"),
    ],
)
def test_entry_selection_is_shared(objective, entry_key, expected) -> None:
    """A mission that starts three steps in must not restart at "the phone rang".

    ``flows_dynamic`` and the text mouths call the same function for this, so a
    rehearsal begins on the node the call would.
    """
    node = entry_node(_builtin(), objective=objective, entry_key=entry_key)
    assert node is not None and node.key == expected


# ---------------------------------------------------------------------------
# A hop crosses into another member, on every mouth
# ---------------------------------------------------------------------------


def _fleet_graph():
    """Two members, each owning a `wrap_up` and one tool of its own."""
    def member(ns: str, start: str, tool: str, is_start: bool):
        return [
            {
                "id": f"{ns}/n1",
                "key": f"{ns}/{start}",
                "data": {"isStart": is_start, "name": start, "instructions": "x", "tools": [tool]},
            },
            {"id": f"{ns}/n2", "key": f"{ns}/wrap_up", "data": {"name": "w", "instructions": "bye"}},
        ]

    return parse_graph(
        {
            "version": 1,
            "globalTools": [],
            "nodes": member("kaia-v2-4", "state_position", "get_account_position", True)
            + member("insurance-v1", "pitch", "check_product_eligibility", False),
            "edges": [],
        }
    )


_GRANTS = {
    "kaia-v2-4": {"get_account_position", "handoff_to_agent"},
    "insurance-v1": {"check_product_eligibility"},
}


def test_union_covers_every_member_so_a_hop_is_executable() -> None:
    """The text mouths gate execution on one set computed before the turn, so
    without this the receiving member's own tools are refused as ungranted the
    moment the hop lands — the mirror of what narrowing fixes."""
    walker = _walker(_fleet_graph())
    widened = walker.union({"get_account_position", "handoff_to_agent"}, _GRANTS)
    assert "check_product_eligibility" in widened
    # And it is bounded by the graph: an unrelated card's grant cannot leak in
    # through a stale bundle.
    assert "capture_lead" not in walker.union({"get_account_position"}, {**_GRANTS, "other": {"capture_lead"}})


def test_a_flat_graph_unions_nothing() -> None:
    walker = _walker()
    assert walker.union({"get_account_position"}, _GRANTS) == {"get_account_position"}


def test_moving_into_another_member_swaps_the_namespace_and_the_grant() -> None:
    """This is the text mouth's half of the hop: the cursor moves, and `narrow`
    already reads the namespace off the cursor."""
    walker = _walker(_fleet_graph())
    assert walker.namespace == "kaia-v2-4"
    granted = walker.union({"get_account_position", "handoff_to_agent"}, _GRANTS)
    assert walker.narrow(granted, _GRANTS) == {"get_account_position", "handoff_to_agent"}

    target = walker.node("insurance-v1/pitch")
    assert target is not None
    walker.move_to(target)

    assert walker.namespace == "insurance-v1"
    assert walker.narrow(granted, _GRANTS) == {"check_product_eligibility"}


def test_a_local_name_resolves_inside_the_member_the_cursor_is_in() -> None:
    """Both members own a `wrap_up`; the one you get is your own."""
    walker = _walker(_fleet_graph())
    assert walker.node("wrap_up").key == "kaia-v2-4/wrap_up"
    walker.move_to(walker.node("insurance-v1/pitch"))
    assert walker.node("wrap_up").key == "insurance-v1/wrap_up"
