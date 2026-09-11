"""The hop is a move, and the move is what swaps the tools.

Every one of these fails against the code before this: the handler returned
``(out, None)``, so the flow cursor never left the sending member's node, the
offer stayed narrowed by *that* node's namespace, and the receiving specialist
spoke with the sender's grant. ``active_specialist`` was assigned and read by
exactly one thing — local node-name resolution — while a comment beside the
assignment claimed it was the handoff.

The existing hop tests set ``state.active_specialist`` by hand and assert
``may_offer``. That pins the predicate, which was never the broken part. These
drive the real handler.
"""

from __future__ import annotations

import asyncio

import flow_graph as fg
import pytest
from tests.test_flow_export import _stub_session
from voice.flows_dynamic import build_authored_flow

COLLECTIONS = "kaia-v2-4"
INSURANCE = "insurance-v1"


def _member_graph(ns: str, *, start: str, tool: str, is_start: bool) -> dict:
    return {
        "version": 1,
        "globalTools": [],
        "nodes": [
            {
                "id": f"{ns}/n-start",
                "key": f"{ns}/{start}",
                "data": {"isStart": is_start, "name": start, "tools": [tool], "instructions": "go"},
            },
            {
                "id": f"{ns}/n-wrap",
                "key": f"{ns}/wrap_up",
                "data": {"name": "wrap", "instructions": "bye"},
            },
        ],
        "edges": [],
    }


def _merged() -> dict:
    a = _member_graph(COLLECTIONS, start="state_position", tool="get_account_position", is_start=True)
    b = _member_graph(INSURANCE, start="pitch", tool="check_product_eligibility", is_start=False)
    return {
        "version": 1,
        "globalTools": [],
        "nodes": a["nodes"] + b["nodes"],
        "edges": [],
    }


@pytest.fixture
def built():
    """A two-member fleet graph, built the way the voice worker builds one."""
    card = {
        "schema_version": "1",
        "identity": {"bot_id": COLLECTIONS, "slug": "collections", "display_name": "Collections"},
        "handoffs": [
            {
                "to_bot_id": INSURANCE,
                "entry_node": "pitch",
                "bridge_line": "say a colleague will take the product question",
            }
        ],
        "tools": {"include": ["get_account_position", "handoff_to_agent"]},
    }
    # A verified caller: handoff_to_agent sits on the identity floor now, so an
    # unverified one is refused before the hop is even attempted — which is a
    # different test, below.
    session = _stub_session()
    session.customer_id = "CUST-1"
    session.identity_verified = True

    state, tools, initial, _globals = build_authored_flow(
        session,
        _merged(),
        role_message="",
        bot_id=COLLECTIONS,
        agent_card=card,
        allowed_tool_names={"get_account_position", "check_product_eligibility", "handoff_to_agent"},
        specialist_grants={
            COLLECTIONS: {"get_account_position", "handoff_to_agent"},
            INSURANCE: {"check_product_eligibility"},
        },
        specialist_entries={COLLECTIONS: f"{COLLECTIONS}/state_position", INSURANCE: f"{INSURANCE}/pitch"},
    )
    return state, tools, initial, card


def _offered(node_config: dict) -> set[str]:
    """Tool names a NodeConfig actually puts in front of the model."""
    out: set[str] = set()
    for fn in node_config.get("functions") or []:
        name = getattr(fn, "name", None)
        if name is None and isinstance(fn, dict):
            name = (fn.get("function") or {}).get("name") or fn.get("name")
        if name:
            out.add(str(name))
    return out


def test_the_speaker_is_seeded_from_the_entry_node(built) -> None:
    """Without this every built-in transition dies on a merged graph:
    `_node("wrap_up")` matches once per member and resolve_key calls it
    ambiguous, so the first fleet call would greet and then sit there."""
    state, _tools, _initial, _card = built
    assert state.active_specialist == COLLECTIONS


def test_a_built_in_transition_still_finds_its_own_node(built) -> None:
    state, tools, _initial, _card = built
    assert fg.resolve_key(
        [f"{COLLECTIONS}/wrap_up", f"{INSURANCE}/wrap_up"],
        "wrap_up",
        namespace=state.active_specialist,
    ) == f"{COLLECTIONS}/wrap_up"


def test_the_hop_lands_on_the_target_and_swaps_the_offer(built, monkeypatch) -> None:
    """The whole point. Fails before: handler returned no node, so the cursor
    stayed put and the offer stayed the sender's."""
    state, tools, _initial, _card = built

    import agent_core.tools.domain as domain

    monkeypatch.setattr(
        domain,
        "handoff_to_agent",
        lambda **kw: domain.ToolResult(ok=True, data={"targetBotId": kw["target_bot_id"]}),
    )

    handler = tools["handoff_to_agent"].handler
    _result, landing = asyncio.run(handler({"target_bot_id": INSURANCE, "reason": "product"}, None))

    assert landing is not None, "the hop returned no node — the cursor never moved"
    assert state.current_node == f"{INSURANCE}/pitch"
    assert state.active_specialist == INSURANCE
    # The invariant that makes the offer correct: the speaker is whoever owns
    # the node the cursor is on.
    assert fg.split_key(state.current_node)[0] == state.active_specialist

    offered = _offered(landing)
    assert "check_product_eligibility" in offered, offered
    assert "get_account_position" not in offered, offered


def test_a_refused_hop_does_not_move(built, monkeypatch) -> None:
    state, tools, _initial, _card = built
    import agent_core.tools.domain as domain

    monkeypatch.setattr(
        domain,
        "handoff_to_agent",
        lambda **kw: domain.ToolResult(ok=False, error="handoff_not_allowlisted"),
    )
    handler = tools["handoff_to_agent"].handler
    _result, landing = asyncio.run(handler({"target_bot_id": INSURANCE, "reason": "x"}, None))
    assert landing is None
    assert state.active_specialist == COLLECTIONS
