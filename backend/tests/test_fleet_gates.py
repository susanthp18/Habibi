"""The four gates that need the merged graph.

All warn-level. Every one reports on cards that are already published, so
shipping them as blocking would make live cards unpublishable on the commit that
added the gate -- and a gate introduced red is a gate people learn to route
around, which is the reasoning `npm audit --audit-level=high` and the eslint
warning budget are already pinned on here.

`door_keys` is passed explicitly throughout rather than imported from
`voice.flow_export`, so these run in a container without pipecat.
"""

from __future__ import annotations

import pytest
from agent_core.fleet.compile import fleet_gates

DOOR = frozenset({"greet_disclose", "discover_intent", "verify_identity", "call_ended"})


def _node(key: str, *, start: bool = False, tools: list[str] | None = None) -> dict:
    return {
        "id": f"n-{key}",
        "key": key,
        "data": {"isStart": start, "tools": tools or [], "entryFor": []},
    }


def _graph(keys: list[str], *, start: str) -> dict:
    return {
        "version": 1,
        "globalTools": [],
        "nodes": [_node(k, start=(k == start)) for k in keys],
        "edges": [],
    }


def _card(bot_id: str, *, tools: list[str], handoffs: list[dict] | None = None) -> dict:
    return {
        "schema_version": "1",
        "identity": {"bot_id": bot_id, "slug": bot_id, "display_name": bot_id},
        "tools": {"include": tools},
        "handoffs": handoffs or [],
    }


def _run(*, card: dict, flow: dict, members: list[dict]):
    gates = fleet_gates(
        primary_bot_id="intake-v1",
        card_raw=card,
        flow=flow,
        members=members,
        door_keys=DOOR,
    )
    return {g.gate: g for g in gates}


_DOOR_FLOW = _graph(
    ["greet_disclose", "discover_intent", "verify_identity", "state_position", "call_ended"],
    start="greet_disclose",
)
_MEMBER_FLOW = _graph(
    ["greet_disclose", "state_position", "negotiate_ptp", "call_ended"],
    start="greet_disclose",
)


def _member(bot_id: str = "kaia-v2-4", flow: dict | None = None) -> dict:
    return {
        "bot_id": bot_id,
        "card": _card(bot_id, tools=["create_promise_to_pay"]),
        "flow": flow if flow is not None else _MEMBER_FLOW,
    }


# ---------------------------------------------------------------------------
# G-F15 -- where a hop lands
# ---------------------------------------------------------------------------


def test_a_hop_with_no_entry_node_lands_on_the_greeting() -> None:
    """The live defect. `CardHandoff.entry_node` defaults to "", documented as
    "that member's start node" -- and `namespaced(keep_start=False)` clears
    `isStart` on every non-primary member, so there is no start node and
    `_merge_members` falls through to "the first node in the list". For a
    collections graph that is `greet_disclose`: the hop would greet a caller who
    has already been greeted and read the recording disclosure a second time."""
    gates = _run(
        card=_card("intake-v1", tools=["handoff_to_agent"], handoffs=[{"to_bot_id": "kaia-v2-4"}]),
        flow=_DOOR_FLOW,
        members=[_member()],
    )
    g = gates["G-F15"]
    assert g.status == "warn"
    assert g.issues[0]["member"] == "kaia-v2-4"
    assert g.issues[0]["entry_node"] == "greet_disclose"
    assert g.issues[0]["authored"] is False


def test_authoring_entry_node_clears_it() -> None:
    gates = _run(
        card=_card(
            "intake-v1",
            tools=["handoff_to_agent"],
            handoffs=[{"to_bot_id": "kaia-v2-4", "entry_node": "state_position"}],
        ),
        flow=_DOOR_FLOW,
        members=[_member()],
    )
    assert gates["G-F15"].status == "pass"


def test_authoring_a_door_node_as_the_entry_is_still_caught() -> None:
    """Authoring the wrong node is not better than authoring none, and the
    gate must not read "the author set a value" as "the author was right"."""
    gates = _run(
        card=_card(
            "intake-v1",
            tools=["handoff_to_agent"],
            handoffs=[{"to_bot_id": "kaia-v2-4", "entry_node": "greet_disclose"}],
        ),
        flow=_DOOR_FLOW,
        members=[_member()],
    )
    assert gates["G-F15"].status == "warn"
    assert gates["G-F15"].issues[0]["authored"] is True


# ---------------------------------------------------------------------------
# G-F2 -- terminals
# ---------------------------------------------------------------------------


def test_a_member_missing_a_terminal_its_sibling_owns_is_caught() -> None:
    """Complete residency, not exclusive ownership.

    `resolve_key` tries the speaking member's namespace first, so a duplicated
    terminal is safe when every namespace has one. Partial is the fatal case: a
    member with no `call_ended` of its own resolves into a sibling's, and once
    two siblings own one `resolve_key` calls it ambiguous and returns None --
    a caller nobody can hang up on."""
    gates = _run(
        card=_card("intake-v1", tools=["handoff_to_agent"], handoffs=[{"to_bot_id": "kaia-v2-4"}]),
        flow=_DOOR_FLOW,
        members=[_member(flow=_graph(["state_position", "negotiate_ptp"], start="state_position"))],
    )
    g = gates["G-F2"]
    assert g.status == "warn"
    assert [i["terminal"] for i in g.issues] == ["call_ended"]
    assert g.issues[0]["missing"] == ["kaia-v2-4"]


def test_every_namespace_owning_the_terminal_passes() -> None:
    gates = _run(
        card=_card("intake-v1", tools=["handoff_to_agent"], handoffs=[{"to_bot_id": "kaia-v2-4"}]),
        flow=_DOOR_FLOW,
        members=[_member()],
    )
    assert gates["G-F2"].status == "pass"


# ---------------------------------------------------------------------------
# G-F6 -- a door that can do business is not a door
# ---------------------------------------------------------------------------


def test_the_door_may_identify_read_route_and_leave() -> None:
    gates = _run(
        card=_card(
            "intake-v1",
            tools=[
                "verify_identity",
                "get_customer_context",
                "capture_call_goal",
                "search_knowledge_base",
                "add_customer_note",
                "handoff_to_agent",
                "escalate_to_human",
            ],
            handoffs=[{"to_bot_id": "kaia-v2-4", "entry_node": "state_position"}],
        ),
        flow=_DOOR_FLOW,
        members=[_member()],
    )
    assert gates["G-F6"].status == "pass"


@pytest.mark.parametrize(
    "tool",
    [
        # Moves money. The reason `ToolSpec.entity` was not usable as the
        # read-only signal: it does not mark this one.
        "apply_goodwill",
        # Creates an obligation on the borrower.
        "create_promise_to_pay",
        # Changes how the borrower may be contacted -- a regulated record.
        "set_contact_preference",
        # Widens the door's own tool surface at runtime.
        "load_skill",
        "run_skill_script",
    ],
)
def test_a_door_holding_a_business_tool_is_caught(tool: str) -> None:
    gates = _run(
        card=_card(
            "intake-v1",
            tools=["handoff_to_agent", tool],
            handoffs=[{"to_bot_id": "kaia-v2-4", "entry_node": "state_position"}],
        ),
        flow=_DOOR_FLOW,
        members=[_member()],
    )
    assert gates["G-F6"].status == "warn"
    assert gates["G-F6"].issues[0]["beyond_routing"] == [tool]


# ---------------------------------------------------------------------------
# No fleet, no fleet gates
# ---------------------------------------------------------------------------


def test_a_single_member_card_emits_nothing() -> None:
    """A card with no members has no hop to check, no sibling to share a
    terminal with and no door. Emitting `pass` for those would be a green light
    for checks that never ran, which `CONTEXT.md` forbids by name."""
    gates = _run(
        card=_card("intake-v1", tools=["handoff_to_agent"]),
        flow=_DOOR_FLOW,
        members=[],
    )
    assert gates == {}


def test_every_emitted_id_is_registered() -> None:
    """`_gate` asserts id -> name against `_GATE_NAMES`; this proves these four
    went through it rather than around it."""
    from agent_core.cards.compile import _GATE_NAMES

    gates = _run(
        card=_card("intake-v1", tools=["handoff_to_agent"], handoffs=[{"to_bot_id": "kaia-v2-4"}]),
        flow=_DOOR_FLOW,
        members=[_member()],
    )
    assert set(gates) == {"G-F2", "G-F6", "G-F12", "G-F15"}
    for gate_id, result in gates.items():
        assert _GATE_NAMES[gate_id] == result.name


def test_none_of_them_can_block_a_publish() -> None:
    """Warn-level by design, for this phase. If one of these is ever promoted to
    blocking, this test is the place that says so out loud."""
    gates = _run(
        card=_card("intake-v1", tools=["load_skill"], handoffs=[{"to_bot_id": "kaia-v2-4"}]),
        flow=_DOOR_FLOW,
        members=[_member(flow=_graph(["state_position"], start="state_position"))],
    )
    assert [g.status for g in gates.values() if g.status == "fail"] == []
