"""GET /staff must not describe an undeployable mouth as active."""

from __future__ import annotations

import uuid

from sqlalchemy import text

import db


def test_an_archived_bot_is_not_active_on_the_staff_roster(db_tx) -> None:
    bot_id = f"roster-archived-{uuid.uuid4().hex[:8]}"
    with db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO bots (id, tenant_id, name, version, archived_at) "
                "VALUES (:i, :t, :n, '1.0', now())"
            ),
            {"i": bot_id, "t": db._tenant(), "n": "Archived roster probe"},
        )
    try:
        row = next(s for s in db.list_staff() if s["id"] == bot_id)
        assert row["kind"] == "bot"
        assert row["status"] == "archived"
        assert row["status"] != "active"
    finally:
        with db.engine.begin() as conn:
            conn.execute(text("DELETE FROM bots WHERE id = :i"), {"i": bot_id})


def test_a_bot_without_a_deployment_is_not_active_on_the_staff_roster(db_tx) -> None:
    bot_id = f"roster-idle-{uuid.uuid4().hex[:8]}"
    with db.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO bots (id, tenant_id, name, version) VALUES (:i, :t, :n, '1.0')"),
            {"i": bot_id, "t": db._tenant(), "n": "Idle roster probe"},
        )
    try:
        row = next(s for s in db.list_staff() if s["id"] == bot_id)
        assert row["kind"] == "bot"
        assert row["status"] != "active"
    finally:
        with db.engine.begin() as conn:
            conn.execute(text("DELETE FROM bots WHERE id = :i"), {"i": bot_id})


def test_seeded_scaffold_bots_are_not_active_on_the_staff_roster() -> None:
    """The two mouths seed_postgres archives on purpose: no prompt, no deployment."""
    by_id = {s["id"]: s for s in db.list_staff()}
    for bot_id in ("webchatbot", "collectionsbot-v2-4"):
        row = by_id.get(bot_id)
        if row is None:
            continue
        assert row["kind"] == "bot"
        assert row["status"] != "active", bot_id
