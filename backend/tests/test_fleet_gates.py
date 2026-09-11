"""The four gates that need the merged graph.

G-F15, G-F2 and G-F6 block; G-F12 warns. The split is not caution: the
blocking gates describe a call that breaks or a door that can do business, and
all three pass on every card that emits them. G-F6 was promoted only once the
shipped intake card was authored down to the read set -- a gate introduced red
is a gate people learn to route around, which is what `npm audit
--audit-level=high` and the eslint warning budget are already pinned on here.

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
    assert g.status == "fail"
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
    assert gates["G-F15"].status == "fail"
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
    assert g.status == "fail"
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
    assert gates["G-F6"].status == "fail"
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


def test_only_the_three_that_describe_a_defect_can_block() -> None:
    """A card that trips all four. G-F15 and G-F2 block because the call is
    broken either way -- the caller is re-greeted, or a member cannot reach a
    terminal; G-F6 because a door holding a business tool is not a door.
    G-F12 reports the design, so it cannot block."""
    gates = _run(
        card=_card("intake-v1", tools=["load_skill"], handoffs=[{"to_bot_id": "kaia-v2-4"}]),
        flow=_DOOR_FLOW,
        # Starts on a door node *and* owns no terminal: re-greets the caller and
        # then cannot hang up on them.
        members=[_member(flow=_graph(["greet_disclose", "state_position"], start="greet_disclose"))],
    )
    assert {g for g, r in gates.items() if r.status == "fail"} == {"G-F15", "G-F2", "G-F6"}
    assert gates["G-F12"].status == "warn"


def test_the_door_may_record_when_it_may_ring() -> None:
    """`set_contact_preference` is the one write on the door: the calling
    window is said to whoever answers, and the dialler reads the consent
    record, not the handoff brief."""
    gates = _run(
        card=_card(
            "intake-v1",
            tools=["verify_identity", "handoff_to_agent", "set_contact_preference"],
            handoffs=[{"to_bot_id": "kaia-v2-4", "entry_node": "state_position"}],
        ),
        flow=_DOOR_FLOW,
        members=[_member()],
    )
    assert gates["G-F6"].status == "pass"


def test_the_shipped_door_passes_the_gate_it_is_now_held_to() -> None:
    """The condition for promoting G-F6: the seeded intake card holds only the
    read set. A regression here means someone put business back on the door."""
    from agent_core.cards.defaults import card_dump

    gates = _run(card=card_dump("intake-v1"), flow=_DOOR_FLOW, members=[_member()])
    assert gates["G-F6"].status == "pass", gates["G-F6"].detail


def test_an_inbound_card_still_reports_the_outbound_eval_gate() -> None:
    """EVALS-16: ticking Outbound on an inbound-only card produced no G-OB9 at
    all -- not even skipped -- so the requirement looked satisfied."""
    from agent_core.cards.compile import _outbound_gates
    from agent_core.cards.schema import parse_card

    card = parse_card(_card("intake-v1", tools=["handoff_to_agent"]))
    gates = {
        g.gate: g
        for g in _outbound_gates(
            card, {}, catalog_names=set(), effective=[], known_bot_ids=set(), eval_report=None
        )
    }
    assert gates["G-OB9"].status == "skipped"
    assert "inbound-only" in gates["G-OB9"].detail
