"""Edge cases in the Agent Studio surface, each one a bug that shipped."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import db
import flow_graph
from agent_core.cards.clone import clone_card
from agent_core.skills.persist import create_draft_skill, delete_skill


@pytest.fixture
def cloned_bot(db_tx):
    row = clone_card(template_id="hardship", name=f"E {uuid.uuid4().hex[:6]}")
    bot_id = row["botId"]
    yield bot_id
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM bot_deployments WHERE bot_id = :b"), {"b": bot_id})
        conn.execute(text("DELETE FROM prompt_versions WHERE bot_id = :b"), {"b": bot_id})
        conn.execute(text("DELETE FROM bots WHERE id = :b"), {"b": bot_id})


def test_an_archived_card_stops_conferring_reachability(cloned_bot: str) -> None:
    """A retired card carries no traffic, so its handoffs are not a path. Leaving
    them in the closure made other cards look reachable through an agent that no
    longer answers."""
    card = db.get_agent_studio_card(cloned_bot)
    raw = dict(card["agentCard"])
    raw["handoffs"] = [{"to_bot_id": "supervisor-brief", "when": "x", "payload_schema": {}}]
    db.patch_prompt_version(card["draftVersionId"], {"agentCard": raw})

    db.archive_agent_studio_card(cloned_bot)
    assert cloned_bot not in {b for b, _ in db._handoff_edges()}

    rows = {c["botId"]: c for c in db.list_agent_studio_cards(include_archived=True)}
    assert rows[cloned_bot]["reachability"] == "archived"


def test_first_party_is_reported_not_inferred(db_tx) -> None:
    """The fleet inferred it from cardSource == "default", but a first-party
    card with a published row reports "published" — so its Archive button
    enabled and then 409'd."""
    cards = {c["botId"]: c for c in db.list_agent_studio_cards()}
    intake = cards["intake-v1"]
    assert intake["isFirstParty"] is True
    assert intake["cardSource"] != "default", "the old inference would have missed this"
    with pytest.raises(ValueError, match="first_party_card_not_archivable"):
        db.archive_agent_studio_card("intake-v1")


def test_a_tenant_card_is_not_first_party(cloned_bot: str) -> None:
    assert db.get_agent_studio_card(cloned_bot)["isFirstParty"] is False


def test_delete_sees_attachments_on_unpublished_drafts(cloned_bot: str) -> None:
    """`attachedCards` counts published versions only — right for the fleet
    badge, wrong as a delete guard, because a skill pinned by a draft reported
    zero attachments.

    In practice the signed-version guard fires first (attaching requires a
    signed version), so this is defence in depth. It is still worth holding:
    the guard is the one that names *which* card is using the skill, and it is
    the only thing standing between a relaxed attach rule and a published card
    pointing at a pack that no longer exists.
    """
    slug = f"t-{uuid.uuid4().hex[:8]}"
    version_id: str | None = None
    skill = create_draft_skill({"slug": slug, "description": "scratch"})
    draft_id = db.get_agent_studio_card(cloned_bot)["draftVersionId"]

    with db.engine.begin() as conn:
        version_id = conn.execute(
            text("SELECT id FROM skill_versions WHERE skill_id = :i LIMIT 1"),
            {"i": skill["id"]},
        ).scalar_one()
        # Bypass attach_skill_to_prompt, which would demand a signed version —
        # the point here is what delete_skill sees, not how the row got there.
        conn.execute(
            text(
                "INSERT INTO skill_attachments (prompt_version_id, skill_version_id)"
                " VALUES (:pv, :sv) ON CONFLICT DO NOTHING"
            ),
            {"pv": draft_id, "sv": version_id},
        )

    with pytest.raises(ValueError, match="skill_attached") as exc:
        delete_skill(skill["id"])
    assert cloned_bot in str(exc.value)
    assert "draft" in str(exc.value), "the message must say it is only a draft"

    with db.engine.begin() as conn:
        conn.execute(
            text("DELETE FROM skill_attachments WHERE skill_version_id = :sv"),
            {"sv": version_id},
        )
    delete_skill(skill["id"])


def test_an_authored_edge_duplicating_a_tool_hop_warns() -> None:
    """Two routes to one node: the business tool, plus the transition tool the
    edge compiles into. Invisible on the canvas, because the ghost edge is
    hidden once an authored one covers the pair."""
    from voice.flow_export import built_in_collections_graph

    graph = built_in_collections_graph()
    src = next(n["id"] for n in graph["nodes"] if n["key"] == "state_position")
    tgt = next(n["id"] for n in graph["nodes"] if n["key"] == "handle_dispute")
    graph["edges"] = [
        {
            "id": "e1",
            "source": src,
            "target": tgt,
            "data": {"condition": {"type": "prompt", "prompt": "x", "match": "all", "clauses": []}},
        }
    ]
    result = flow_graph.validate_graph(
        flow_graph.parse_graph(graph),
        known_tools=[t["key"] for t in flow_graph.tool_catalog()],
    )
    warnings = [i for i in result.issues if i.code == "redundant_with_tool"]
    assert len(warnings) == 1
    assert "begin_dispute" in warnings[0].message
    assert result.ok, "advisory only — an explicit path may be deliberate"


def test_a_non_duplicating_edge_does_not_warn() -> None:
    """negotiate_ptp carries no tool that reaches handle_dispute — begin_dispute
    lives on other nodes — so this edge adds a route rather than repeating one.

    This used to draw handle_dispute -> state_position, which looked
    non-duplicating only because the transition reader could not see through
    `_node(hub_node)`. handle_dispute carries return_to_position, so that edge
    was always a second route and the warning it now raises is correct.
    """
    from voice.flow_export import built_in_collections_graph

    graph = built_in_collections_graph()
    src = next(n["id"] for n in graph["nodes"] if n["key"] == "negotiate_ptp")
    tgt = next(n["id"] for n in graph["nodes"] if n["key"] == "handle_dispute")
    graph["edges"] = [
        {
            "id": "e1",
            "source": src,
            "target": tgt,
            "data": {"condition": {"type": "prompt", "prompt": "x", "match": "all", "clauses": []}},
        }
    ]
    result = flow_graph.validate_graph(
        flow_graph.parse_graph(graph),
        known_tools=[t["key"] for t in flow_graph.tool_catalog()],
    )
    assert [i for i in result.issues if i.code == "redundant_with_tool"] == []


def test_list_and_single_card_return_the_same_shape(db_tx) -> None:
    """The fleet and the editor read the same type. `archivedAt` was set only on
    the tenant branch of the list, so first-party rows omitted it entirely while
    the single-card endpoint always had it — a field the client declares
    non-optional."""
    listed = db.list_agent_studio_cards(include_archived=True)
    assert listed
    single = db.get_agent_studio_card(listed[0]["botId"])
    assert single is not None
    assert set(single) == set(listed[0])
    assert all("archivedAt" in c for c in listed)
    assert all("isFirstParty" in c for c in listed)
    assert all("reachability" in c and "entryBotId" in c for c in listed)


def test_an_edge_that_repeats_a_hub_return_warns() -> None:
    """The counterpart. handle_dispute offers return_to_position, which moves the
    call to the hub, so drawing that edge by hand gives the model two ways to do
    one thing — invisible on the canvas, because an authored edge hides the ghost."""
    from voice.flow_export import built_in_collections_graph

    graph = built_in_collections_graph()
    src = next(n["id"] for n in graph["nodes"] if n["key"] == "handle_dispute")
    tgt = next(n["id"] for n in graph["nodes"] if n["key"] == "state_position")
    graph["edges"] = [
        {
            "id": "e1",
            "source": src,
            "target": tgt,
            "data": {"condition": {"type": "prompt", "prompt": "x", "match": "all", "clauses": []}},
        }
    ]

    result = flow_graph.validate_graph(
        flow_graph.parse_graph(graph),
        known_tools=[t["key"] for t in flow_graph.tool_catalog()],
    )

    warnings = [i for i in result.issues if i.code == "redundant_with_tool"]
    assert len(warnings) == 1
    assert "return_to_position" in warnings[0].message


def test_a_step_cannot_transition_to_itself() -> None:
    """A self-edge compiles into a transition tool whose only destination is the
    node the model is already on, so the call can never leave — and on the canvas
    it draws as a stub behind the card, invisible. The editor rejects the drag;
    this is the half that a stored graph cannot get past."""
    from voice.flow_export import built_in_collections_graph

    graph = built_in_collections_graph()
    hub = next(n["id"] for n in graph["nodes"] if n["key"] == "state_position")
    graph["edges"] = [
        {
            "id": "e-self",
            "source": hub,
            "target": hub,
            "data": {"condition": {"type": "prompt", "prompt": "x", "match": "all", "clauses": []}},
        }
    ]

    result = flow_graph.validate_graph(
        flow_graph.parse_graph(graph),
        known_tools=[t["key"] for t in flow_graph.tool_catalog()],
    )

    assert not result.ok
    assert [i.code for i in result.issues if i.severity == "error"] == ["self_edge"]


def test_a_self_edge_is_not_also_reported_as_redundant() -> None:
    """One finding per fault. The self-edge check `continue`s, so the pair never
    reaches the duplicate/redundancy passes that would otherwise pile three
    messages onto one bad drag."""
    from voice.flow_export import built_in_collections_graph

    graph = built_in_collections_graph()
    node = next(n["id"] for n in graph["nodes"] if n["key"] == "handle_dispute")
    graph["edges"] = [
        {
            "id": "e-self",
            "source": node,
            "target": node,
            "data": {"condition": {"type": "prompt", "prompt": "x", "match": "all", "clauses": []}},
        }
    ]

    issues = flow_graph.validate_graph(
        flow_graph.parse_graph(graph),
        known_tools=[t["key"] for t in flow_graph.tool_catalog()],
    ).issues

    assert [i.code for i in issues if i.edgeId == "e-self"] == ["self_edge"]
