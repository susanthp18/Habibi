"""A specialist hop is a row in ``interaction_handoffs``, not an escalation.

That table has always meant one thing — handed to a human — and three analytics
queries read the mere existence of a row as the escalated flag. The in-process
hop writes rows to the same table, so without the ``to_kind`` filter the first
hop this tree ever makes inflates the escalation and containment rates a
grievance MIS report is built on.

The CHECK widening and the filter shipped in the same commit for exactly that
reason. Either alone is a wrong number, so both halves are pinned here.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text

import db
import db_bot_analytics
import db_inbox
from agent_core.cards.defaults import COLLECTIONS_BOT_ID, INSURANCE_BOT_ID
from agent_core.tools import domain

HUMAN_REASONS = (
    "sentiment_drop",
    "verification_failed",
    "compliance",
    "customer_requested",
    "hardship",
    "dispute",
    "high_value",
    "routing_rule",
)
FLEET_REASONS = ("specialist_route", "specialist_return", "mission_entry")


def _interaction(conn) -> str:
    customers = db.list_customers(limit=1)
    assert customers
    ix = f"ix-hop-{uuid.uuid4().hex[:8]}"
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
        {
            "id": ix,
            "t": db._tenant(),
            "c": customers[0]["id"],
            "bot": COLLECTIONS_BOT_ID,
        },
    )
    return ix


def _escalated(conn, ix: str) -> bool:
    """The predicate the analytics module actually uses, run on one row."""
    return bool(
        conn.execute(
            text(f"SELECT {db_bot_analytics._ESCALATED_PRED} FROM interactions i WHERE i.id = :id"),
            {"id": ix},
        ).scalar()
    )


def test_every_reason_the_check_admits(db_tx) -> None:
    """The eight human values still fit, and the three fleet values now do too.

    Before the widening an insert of ``specialist_route`` failed outright, so a
    hop could not be recorded at all — which is why the ledger for a bot-to-bot
    transfer was two columns on ``interactions`` and nothing else.
    """
    with db.engine.begin() as conn:
        ix = _interaction(conn)
        for reason in HUMAN_REASONS + FLEET_REASONS:
            conn.execute(
                text(
                    """
                    INSERT INTO interaction_handoffs (
                      id, interaction_id, from_kind, from_bot_id, to_kind, reason,
                      requested_at, created_at
                    ) VALUES (:id, :ix, 'bot', :bot, 'bot', :reason, now(), now())
                    """
                ),
                {
                    "id": f"ho-{uuid.uuid4().hex[:10]}",
                    "ix": ix,
                    "bot": COLLECTIONS_BOT_ID,
                    "reason": reason,
                },
            )


def test_a_bot_hop_does_not_count_as_an_escalation(db_tx) -> None:
    with db.engine.begin() as conn:
        ix = _interaction(conn)
        assert _escalated(conn, ix) is False
        conn.execute(
            text(
                """
                INSERT INTO interaction_handoffs (
                  id, interaction_id, from_kind, from_bot_id, to_kind, to_bot_id,
                  reason, requested_at, created_at
                ) VALUES (
                  :id, :ix, 'bot', :from_bot, 'bot', :to_bot,
                  'specialist_route', now(), now()
                )
                """
            ),
            {
                "id": f"ho-{uuid.uuid4().hex[:10]}",
                "ix": ix,
                "from_bot": COLLECTIONS_BOT_ID,
                "to_bot": INSURANCE_BOT_ID,
            },
        )
        assert _escalated(conn, ix) is False


def test_a_human_handoff_still_counts(db_tx) -> None:
    """The filter must not have quietly turned the metric off."""
    with db.engine.begin() as conn:
        ix = _interaction(conn)
        conn.execute(
            text(
                """
                INSERT INTO interaction_handoffs (
                  id, interaction_id, from_kind, from_bot_id, to_kind, reason,
                  requested_at, created_at
                ) VALUES (:id, :ix, 'bot', :bot, 'human', 'hardship', now(), now())
                """
            ),
            {"id": f"ho-{uuid.uuid4().hex[:10]}", "ix": ix, "bot": COLLECTIONS_BOT_ID},
        )
        assert _escalated(conn, ix) is True


def test_the_handoff_tool_writes_the_hop_row(db_tx) -> None:
    """The packet that crossed the boundary is recorded, not remembered."""
    with db.engine.begin() as conn:
        ix = _interaction(conn)
    packet = {"identity_verified": True, "call_goal": "dispute a late fee"}
    result = domain.handoff_to_agent(
        interaction_id=ix,
        from_bot_id=COLLECTIONS_BOT_ID,
        target_bot_id=INSURANCE_BOT_ID,
        reason="in-policy upsell",
        allowlist={INSURANCE_BOT_ID},
        packet=packet,
        carry="brief",
        turn_index=7,
        deployment_id="dep-test",
    )
    assert result.ok
    with db.engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT to_kind, to_bot_id, reason, turn_index, deployment_id,
                       carry, packet
                FROM interaction_handoffs WHERE interaction_id = :ix
                """
            ),
            {"ix": ix},
        ).mappings().one()
        assert _escalated(conn, ix) is False
    assert row["to_kind"] == "bot"
    assert row["to_bot_id"] == INSURANCE_BOT_ID
    assert row["reason"] == "specialist_route"
    assert row["turn_index"] == 7
    assert row["deployment_id"] == "dep-test"
    assert row["carry"] == "brief"
    stored = row["packet"] if isinstance(row["packet"], dict) else json.loads(row["packet"])
    assert stored == packet


def test_the_route_reason_a_caller_asks_for_is_what_lands(db_tx) -> None:
    """The CHECK admitted three values and the writer hardcoded one of them.

    ``specialist_return`` and ``mission_entry`` were in the constraint and
    produced by nothing, so the test above proved the database would accept a
    value the product could not emit. This drives the writer.
    """
    with db.engine.begin() as conn:
        ix = _interaction(conn)
    db_inbox.handoff_to_agent(
        interaction_id=ix,
        from_bot_id=COLLECTIONS_BOT_ID,
        target_bot_id=INSURANCE_BOT_ID,
        reason="caller asked about a policy",
        route_reason="specialist_return",
    )
    with db.engine.connect() as conn:
        row = conn.execute(
            text("SELECT reason FROM interaction_handoffs WHERE interaction_id = :ix"),
            {"ix": ix},
        ).mappings().first()
    assert row["reason"] == "specialist_return"


def test_an_unknown_route_reason_does_not_abort_a_live_call(db_tx) -> None:
    """A bad value degrades to the ordinary route rather than 500-ing a call."""
    with db.engine.begin() as conn:
        ix = _interaction(conn)
    db_inbox.handoff_to_agent(
        interaction_id=ix,
        from_bot_id=COLLECTIONS_BOT_ID,
        target_bot_id=INSURANCE_BOT_ID,
        reason="x",
        route_reason="not_a_real_reason",
    )
    with db.engine.connect() as conn:
        row = conn.execute(
            text("SELECT reason FROM interaction_handoffs WHERE interaction_id = :ix"),
            {"ix": ix},
        ).mappings().first()
    assert row["reason"] == "specialist_route"


def test_the_hop_cap_is_counted_in_the_write(db_tx) -> None:
    """One cap for both channels, and one that survives a reconnect.

    It lived on ``ToolState.hops_taken``, so text had no cap at all and a voice
    call that dropped and came back got a fresh allowance.
    """
    import pytest

    with db.engine.begin() as conn:
        ix = _interaction(conn)
    db_inbox.handoff_to_agent(
        interaction_id=ix,
        from_bot_id=COLLECTIONS_BOT_ID,
        target_bot_id=INSURANCE_BOT_ID,
        reason="first",
        max_hops=1,
    )
    with pytest.raises(ValueError, match="hop_cap_reached"):
        db_inbox.handoff_to_agent(
            interaction_id=ix,
            from_bot_id=INSURANCE_BOT_ID,
            target_bot_id=COLLECTIONS_BOT_ID,
            reason="second",
            max_hops=1,
        )
