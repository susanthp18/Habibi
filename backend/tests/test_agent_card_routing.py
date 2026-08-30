"""Routing vs deployment, and the archive lifecycle.

The fleet index badged every published card "live · 100%". That describes the
deployment row and says nothing about traffic, so the badge was replaced by a
reachability walk over the handoff graph.

That walk then over-corrected. It seeded from ``BOT_ID`` alone, on the premise
that inbound resolves exactly one bot — but ``agent_core/deployment.py``
resolves ``bot_id or DEFAULT_BOT_ID`` against ``bot_deployments``, so the
default is a fallback and any card holding an active production deployment is
separately addressable. Intake, a live front door at 100% traffic that routes
*to* Collections, was reported "unreachable" alongside two empty scaffolds that
genuinely are. ``direct`` is the state that separates them.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import db
from agent_core.cards.clone import clone_card
from agent_core.cards.routing import reachability, reachable_from, runtime_entry_bot_id


def _card(*targets: str) -> dict:
    return {"handoffs": [{"to_bot_id": t} for t in targets]}


def test_entry_card_is_the_runtime_bot() -> None:
    """Both runtimes read BOT_ID — bot_runtime._bot_id() for the message
    channels, db.DEFAULT_BOT_ID for voice."""
    assert runtime_entry_bot_id() == db.DEFAULT_BOT_ID


def test_reachability_splits_entry_handoff_and_orphan() -> None:
    routes = reachability(
        [
            ("a", _card("b")),
            ("b", _card("c")),
            ("c", _card()),
            ("orphan", _card("a")),  # points *at* the entry; nothing points back
        ],
        entry="a",
    )
    assert routes == {
        "a": "entry",
        "b": "handoff",
        "c": "handoff",
        "orphan": "unreachable",
    }


def test_reachability_survives_a_handoff_cycle() -> None:
    """Collections and Insurance list each other in the shipped cards."""
    routes = reachability([("a", _card("b")), ("b", _card("a"))], entry="a")
    assert routes == {"a": "entry", "b": "handoff"}


def test_reachable_from_ignores_unknown_targets() -> None:
    # A handoff naming a deleted bot must not raise, only fail to resolve.
    assert reachable_from("a", {"a": ["gone"]}) == {"a", "gone"}


def test_live_fleet_marks_the_real_entry_point(db_tx) -> None:
    cards = {c["botId"]: c for c in db.list_agent_studio_cards()}
    entry = runtime_entry_bot_id()
    assert cards[entry]["reachability"] == "entry"
    assert sum(1 for c in cards.values() if c["reachability"] == "entry") == 1
    for card in cards.values():
        assert card["entryBotId"] == entry


@pytest.fixture
def cloned_bot(db_tx):
    row = clone_card(template_id="hardship", name=f"T {uuid.uuid4().hex[:6]}")
    bot_id = row["botId"]
    yield bot_id
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM bot_deployments WHERE bot_id = :b"), {"b": bot_id})
        conn.execute(text("DELETE FROM prompt_versions WHERE bot_id = :b"), {"b": bot_id})
        conn.execute(text("DELETE FROM bots WHERE id = :b"), {"b": bot_id})


def test_archive_hides_the_card_and_restore_brings_it_back(cloned_bot: str) -> None:
    db.archive_agent_studio_card(cloned_bot)
    assert cloned_bot not in {c["botId"] for c in db.list_agent_studio_cards()}

    archived = next(
        c for c in db.list_agent_studio_cards(include_archived=True) if c["botId"] == cloned_bot
    )
    assert archived["reachability"] == "archived"
    assert archived["archivedAt"]

    db.restore_agent_studio_card(cloned_bot)
    assert cloned_bot in {c["botId"] for c in db.list_agent_studio_cards()}


def test_archive_keeps_the_row_and_its_versions(cloned_bot: str) -> None:
    """bots.id is a foreign key on interactions and eval_reports — a delete
    would cascade the deployments and NULL the audit trail."""
    db.archive_agent_studio_card(cloned_bot)
    with db.engine.connect() as conn:
        assert db._one(conn.execute(text("SELECT 1 FROM bots WHERE id = :b"), {"b": cloned_bot}))
        assert db._one(
            conn.execute(text("SELECT 1 FROM prompt_versions WHERE bot_id = :b"), {"b": cloned_bot})
        )


def test_archive_refuses_first_party(db_tx) -> None:
    with pytest.raises(ValueError, match="first_party_card_not_archivable"):
        db.archive_agent_studio_card("intake-v1")


def test_archiving_a_live_card_retires_its_deployment(cloned_bot: str) -> None:
    """This used to raise card_has_active_deployment. That guard made the whole
    feature unreachable: publish always leaves an active deployment and rollback
    only swaps which one is active, so no card that had ever shipped could be
    retired. Taking no traffic is what archiving means, so the deployment is
    retired here rather than refused."""
    card = db.get_agent_studio_card(cloned_bot)
    db.publish_prompt_version(card["draftVersionId"], "live")
    assert db.get_active_deployment(bot_id=cloned_bot, environment="production")

    db.archive_agent_studio_card(cloned_bot)

    assert db.get_active_deployment(bot_id=cloned_bot, environment="production") is None


def test_archiving_twice_is_not_silently_ok(cloned_bot: str) -> None:
    db.archive_agent_studio_card(cloned_bot)
    with pytest.raises(KeyError):
        db.archive_agent_studio_card(cloned_bot)


def test_a_bot_with_no_version_gets_an_authorable_card(db_tx) -> None:
    """`{}` is not authorable — is_authored is false, so every card tab was
    empty and the compiler treated the bot as legacy."""
    from agent_core.cards.schema import is_authored, parse_card

    bot_id = f"zz-scaffold-{uuid.uuid4().hex[:6]}"
    with db.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO bots (id, tenant_id, name, version) VALUES (:i, :t, :n, '1.0')"),
            {"i": bot_id, "t": db._tenant(), "n": "Scaffold probe"},
        )
    try:
        card = db.get_agent_studio_card(bot_id)
        assert card["cardSource"] == "scaffold"
        assert is_authored(card["agentCard"])
        parsed = parse_card(card["agentCard"])
        assert parsed.identity.bot_id == bot_id
        assert parsed.tools.locked, "locked policy engines are the floor every card stands on"
    finally:
        with db.engine.begin() as conn:
            conn.execute(text("DELETE FROM bots WHERE id = :i"), {"i": bot_id})


def test_a_live_card_nothing_hands_off_to_is_direct_not_unreachable() -> None:
    """Intake is the shipped case: a front door at 100% traffic that routes
    *to* Collections while Collections is the configured default.

    Calling it "unreachable" was wrong twice over — it takes calls, and the word
    was doing real work elsewhere on the same screen for cards that genuinely
    take none.
    """
    routes = reachability(
        [("entry", _card("mid")), ("mid", _card()), ("front", _card("entry")), ("dead", _card())],
        entry="entry",
        deployed=["front"],
    )
    assert routes == {
        "entry": "entry",
        "mid": "handoff",
        "front": "direct",
        "dead": "unreachable",
    }


def test_an_inbound_edge_outranks_a_deployment_of_its_own() -> None:
    """Position in the conversation graph is the more specific fact."""
    routes = reachability(
        [("entry", _card("both")), ("both", _card())], entry="entry", deployed=["both"]
    )
    assert routes["both"] == "handoff"


def test_a_deployed_card_opens_the_graph_behind_it() -> None:
    """Whatever the front door can reach is reachable, even when the configured
    entry card cannot reach it."""
    routes = reachability(
        [("entry", _card()), ("front", _card("behind")), ("behind", _card())],
        entry="entry",
        deployed=["front"],
    )
    assert routes["behind"] == "handoff"


def test_the_fleet_and_the_single_card_endpoint_agree(db_tx) -> None:
    """They compute reachability from different edge queries. _handoff_edges
    was missing the tenant predicate the fleet index applies, so the detail page
    and the index could label the same card differently."""
    disagree = {
        c["botId"]: (c["reachability"], db.get_agent_studio_card(c["botId"])["reachability"])
        for c in db.list_agent_studio_cards()
        if db.get_agent_studio_card(c["botId"])["reachability"] != c["reachability"]
    }
    assert disagree == {}


def test_a_card_with_no_version_and_no_deployment_is_still_unreachable(db_tx) -> None:
    """The word has to keep meaning something. Seeding the walk with deployed
    cards must not quietly promote the empty scaffolds."""
    cards = {c["botId"]: c for c in db.list_agent_studio_cards()}
    empty = [c for c in cards.values() if c["deploymentStatus"] == "empty"]
    if not empty:
        pytest.skip("fleet has no empty cards to check")
    for card in empty:
        assert card["reachability"] == "unreachable", card["botId"]
