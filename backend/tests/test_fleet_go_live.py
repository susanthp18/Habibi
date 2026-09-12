"""The fleet is live on the dev stack: the Door answers and hands off.

These read the deployed state -- the entry binding, the door's active
bundle -- rather than fixtures, because the go-live is a property of the
stack, not of a unit. They skip on a stack that has not been seeded
(`scripts/seed_member_graphs.py --apply`, `scripts/republish_first_party.py`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import flow_graph
from flow_vars import FlowVariables
from flow_walk import FlowWalker

DOOR = "intake-v1"
COLLECTIONS = "kaia-v2-4"


def _door_bundle():
    from agent_core.deployment import load_active_bundle

    try:
        return load_active_bundle("production", bot_id=DOOR)
    except KeyError:
        pytest.skip("the door has no active deployment on this stack")


def test_the_template_ships_the_fleet_on() -> None:
    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    lines = {ln.split("=", 1)[0]: ln.split("=", 1)[1] for ln in example.splitlines() if "=" in ln and not ln.startswith("#")}
    assert lines["DOOR_ENABLED"] == "true"


def test_the_bound_number_resolves_to_the_door(monkeypatch: pytest.MonkeyPatch) -> None:
    import db
    from sqlalchemy import text

    from agent_core.cards.routing import resolve_entry

    monkeypatch.setenv("DOOR_ENABLED", "1")
    with db.engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT address FROM entry_bindings WHERE bot_id = :b AND channel = 'voice' "
                "AND enabled AND address IS NOT NULL LIMIT 1"
            ),
            {"b": DOOR},
        ).scalar()
    if not row:
        pytest.skip("no voice entry binding for the door on this stack")
    assert resolve_entry("voice", str(row)) == DOOR


def test_the_voice_channel_default_is_the_door(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not only the one bound number: a call to any voice address lands on the
    Door, so the fleet index has exactly one voice entry and kaia is reached
    through it."""
    from agent_core.cards.routing import resolve_entry

    monkeypatch.setenv("DOOR_ENABLED", "1")
    assert resolve_entry("voice") == DOOR
    assert resolve_entry("voice", "+10000000000") == DOOR


def test_the_door_serves_the_merged_fleet_graph() -> None:
    bundle = _door_bundle()
    flow = bundle["flow"]
    namespaces = flow_graph.graph_namespaces(flow)
    assert {DOOR, COLLECTIONS} <= namespaces, namespaces
    compiled = bundle["compiled"]
    assert set(compiled["grant_by_specialist"]) == namespaces


def test_a_text_rehearsal_walks_the_door_into_collections() -> None:
    """greet -> discover -> verify -> route -> kaia-v2-4/state_position: the
    hop lands on collections' business node, verified, with collections' grant."""
    bundle = _door_bundle()
    graph = flow_graph.parse_graph(bundle["flow"])
    compiled = bundle["compiled"]
    entries = {k: v for k, v in compiled["entry_by_specialist"].items()}
    w = FlowWalker(graph, FlowVariables({}))
    assert w.current is not None and flow_graph.local_key(w.current.key) == "greet_disclose"
    assert w.namespace == DOOR
    for tool, expect in (
        ("disclose_recording", "discover_intent"),
        ("capture_call_goal", "verify_identity"),
        ("verify_identity", "state_position"),
    ):
        landed = w.advance(tool)
        assert landed is not None and flow_graph.local_key(landed.key) == expect, (tool, landed)
    assert "handoff_to_agent" in w.current.data.tools
    landing = w.move_to(w.node(entries[COLLECTIONS]))
    assert landing.key == entries[COLLECTIONS]
    assert w.namespace == COLLECTIONS
    assert flow_graph.local_key(landing.key) == "state_position"
    assert "get_account_position" in landing.data.tools
