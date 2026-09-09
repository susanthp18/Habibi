"""Two members, one graph, and a grant each.

Before this, ``grant_by_specialist`` mapped every namespace it found to the
*union* grant — so a hop that read it would have handed the receiving specialist
exactly the tools it was supposed to stop it having. And nothing in the tree
produced a namespaced graph at all, so the whole per-member path was unreachable
and untested.

The merge is the one place a namespace is ever written, and the namespace is a
bot id. These pin the properties a merged graph has to have for the runtime to
be able to walk it: one start node, no colliding ids, and grants that actually
differ.
"""

from __future__ import annotations

import flow_graph as fg
import pytest
from agent_core.cards.compile import CompileReport
from agent_core.fleet.compile import compile_bundle, digest

_PRIMARY_TOOLS = ["get_account_position", "create_promise_to_pay"]
_MEMBER_TOOLS = ["check_product_eligibility", "capture_lead"]


def _graph(*, start_key: str, second_key: str) -> dict:
    """Two nodes and an edge. Ids are deliberately identical between members —
    both real graphs ship `n-start`, which is the collision the merge must
    survive."""
    return {
        "version": 1,
        "globalTools": ["search_knowledge_base"],
        "nodes": [
            {"id": "n-start", "key": start_key, "data": {"isStart": True, "tools": ["verify_identity"]}},
            {"id": "n-2", "key": second_key, "data": {"tools": []}},
        ],
        "edges": [{"id": "e1", "source": "n-start", "target": "n-2"}],
    }


def _card(bot_id: str, tools: list[str]) -> dict:
    return {
        "schema_version": "1",
        "identity": {"bot_id": bot_id, "slug": bot_id, "display_name": bot_id},
        "tools": {"include": tools},
    }


def _report(bot_id: str, tools: list[str]) -> CompileReport:
    return CompileReport(bot_id=bot_id, gates=[], effective_tools=tools, card=_card(bot_id, tools))


def _bundle(members):
    return compile_bundle(
        report=_report("kaia-v2-4", _PRIMARY_TOOLS),
        flow=_graph(start_key="greet", second_key="wrap_up"),
        members=members,
    )


@pytest.fixture
def merged():
    return _bundle(
        [
            {
                "bot_id": "insurance-v1",
                "card": _card("insurance-v1", _MEMBER_TOOLS),
                "flow": _graph(start_key="pitch", second_key="wrap_up"),
            }
        ]
    )


def test_one_member_still_compiles_to_todays_behaviour() -> None:
    """The runtime falls back to `flow`, so nothing changes until a fleet exists."""
    bundle = _bundle(None)
    assert bundle.fleet_flow == {}
    assert bundle.entry_by_specialist == {}
    assert bundle.grant_by_specialist == {}


def test_both_members_may_own_a_wrap_up(merged) -> None:
    keys = [n["key"] for n in merged.fleet_flow["nodes"]]
    assert "kaia-v2-4/wrap_up" in keys
    assert "insurance-v1/wrap_up" in keys


def test_ids_do_not_collide(merged) -> None:
    ids = [n["id"] for n in merged.fleet_flow["nodes"]]
    assert len(ids) == len(set(ids)), ids
    # And the edges still point at nodes that exist.
    by_id = set(ids)
    for edge in merged.fleet_flow["edges"]:
        assert edge["source"] in by_id and edge["target"] in by_id


def test_exactly_one_start_node(merged) -> None:
    starts = [n["key"] for n in merged.fleet_flow["nodes"] if (n["data"] or {}).get("isStart")]
    assert starts == ["kaia-v2-4/greet"]


def test_each_member_gets_its_own_grant_not_the_union(merged) -> None:
    """The bug this replaces: every namespace mapped to the union."""
    primary = set(merged.grant_by_specialist["kaia-v2-4"])
    member = set(merged.grant_by_specialist["insurance-v1"])
    assert "create_promise_to_pay" in primary
    assert "create_promise_to_pay" not in member
    assert "capture_lead" in member
    assert "capture_lead" not in primary


def test_global_tools_do_not_leak_across_members(merged) -> None:
    """A member's globals ride on its own nodes, never on the merged graph."""
    assert merged.fleet_flow["globalTools"] == []
    for node in merged.fleet_flow["nodes"]:
        assert "search_knowledge_base" in (node["data"] or {}).get("tools", [])


def test_entry_by_specialist_names_a_node_that_exists(merged) -> None:
    keys = {n["key"] for n in merged.fleet_flow["nodes"]}
    assert merged.entry_by_specialist["insurance-v1"] == "insurance-v1/pitch"
    for entry in merged.entry_by_specialist.values():
        assert entry in keys


def test_the_authored_flow_and_its_digest_are_untouched(merged) -> None:
    """A fleet publish must not make the canvas or `parity_report` disagree."""
    authored = _graph(start_key="greet", second_key="wrap_up")
    assert merged.flow == authored
    assert merged.hashes.flow == digest(authored)


def test_the_namespaces_are_bot_ids(merged) -> None:
    assert fg.graph_namespaces(merged.fleet_flow) == {"kaia-v2-4", "insurance-v1"}
    assert set(merged.grant_by_specialist) == {"kaia-v2-4", "insurance-v1"}
