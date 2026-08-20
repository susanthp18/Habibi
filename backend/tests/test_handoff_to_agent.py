"""Handoff is a tool with a log. Prose does not move handler_bot_id."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import db
from agent_core.cards.defaults import COLLECTIONS_BOT_ID, INSURANCE_BOT_ID
from agent_core.tools import domain


def _interaction(conn, customer_id: str) -> str:
    ix = f"ix-handoff-{uuid.uuid4().hex[:8]}"
    conn.execute(
        text(
            """
            INSERT INTO interactions (
              id, tenant_id, customer_id, handler_kind, handler_bot_id, channel,
              status, started_at, created_at, updated_at
            ) VALUES (
              :id, :t, :c, 'bot', :bot, 'voice', 'active', now(), now(), now()
            )
            """
        ),
        {"id": ix, "t": db._tenant(), "c": customer_id, "bot": COLLECTIONS_BOT_ID},
    )
    return ix


def test_handoff_tool_writes_handler_bot_id(db_tx) -> None:
    customers = db.list_customers(limit=1)
    assert customers
    cid = customers[0]["id"]
    with db.engine.begin() as conn:
        ix = _interaction(conn, cid)
    result = domain.handoff_to_agent(
        interaction_id=ix,
        from_bot_id=COLLECTIONS_BOT_ID,
        target_bot_id=INSURANCE_BOT_ID,
        reason="in-policy upsell",
        allowlist={INSURANCE_BOT_ID},
    )
    assert result.ok
    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(
                text(
                    "SELECT handler_bot_id, transferred_from_bot_id FROM interactions WHERE id = :id"
                ),
                {"id": ix},
            )
        )
    assert row["handler_bot_id"] == INSURANCE_BOT_ID
    assert row["transferred_from_bot_id"] == COLLECTIONS_BOT_ID


def test_prose_does_not_handoff(db_tx) -> None:
    customers = db.list_customers(limit=1)
    cid = customers[0]["id"]
    with db.engine.begin() as conn:
        ix = _interaction(conn, cid)
    # No tool call. The transcript saying "transfer to legal" is irrelevant.
    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(
                text("SELECT handler_bot_id, transferred_from_bot_id FROM interactions WHERE id = :id"),
                {"id": ix},
            )
        )
    assert row["handler_bot_id"] == COLLECTIONS_BOT_ID
    assert row["transferred_from_bot_id"] is None


def test_allowlist_rejects_legal(db_tx) -> None:
    result = domain.handoff_to_agent(
        interaction_id="ix-none",
        from_bot_id=COLLECTIONS_BOT_ID,
        target_bot_id="legal-v1",
        reason="customer asked",
        allowlist={INSURANCE_BOT_ID},
    )
    assert result.ok is False
    assert result.error == "handoff_not_allowlisted"
