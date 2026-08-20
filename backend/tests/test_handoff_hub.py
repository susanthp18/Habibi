"""Handoff Hub: assigned session, claim race, wrap-up, disclosures."""

from __future__ import annotations

import pytest
from sqlalchemy import text

import actor_context
import authz
import db

AGENT = "sara-khan"
OTHER = "arjun-mehta"
ADMIN = "priya-nair"


@pytest.fixture(autouse=True)
def _enforce(monkeypatch):
    monkeypatch.setenv("VISIBILITY_ENFORCE", "1")
    authz.invalidate_permission_cache()
    yield
    authz.invalidate_permission_cache()


@pytest.fixture
def as_actor():
    tokens = []

    def _use(user_id: str):
        tokens.append(actor_context.set_actor_user_id(user_id))

    yield _use
    for token in reversed(tokens):
        actor_context.reset_actor_user_id(token)


def _seed_unclaimed(conn, *, team: str = "card-collections", suffix: str = "a") -> tuple[str, str, str]:
    cust = conn.execute(text("SELECT id FROM customers ORDER BY id LIMIT 1")).scalar()
    acct = conn.execute(
        text("SELECT id FROM accounts WHERE customer_id = :c ORDER BY id LIMIT 1"),
        {"c": cust},
    ).scalar()
    if not cust or not acct:
        pytest.skip("no customers")
    ix = f"IX-HO-{suffix}"
    ho = f"HO-{suffix}"
    conn.execute(
        text(
            """
            INSERT INTO interactions (
              id, tenant_id, customer_id, account_id, channel, direction, status,
              handler_kind, handler_bot_id, started_at, created_at, updated_at
            ) VALUES (
              :id, :tenant, :cid, :aid, 'voice', 'inbound', 'active',
              'bot', :bot, now(), now(), now()
            )
            """
        ),
        {
            "id": ix,
            "tenant": db.current_tenant(),
            "cid": cust,
            "aid": acct,
            "bot": db.DEFAULT_BOT_ID,
        },
    )
    conn.execute(
        text(
            """
            INSERT INTO interaction_handoffs (
              id, interaction_id, from_kind, from_bot_id, to_kind, to_team_id,
              reason, queue, requested_at, created_at
            ) VALUES (
              :id, :iid, 'bot', :bot, 'human', :team,
              'dispute', 'Card Collections', now(), now()
            )
            """
        ),
        {"id": ho, "iid": ix, "bot": db.DEFAULT_BOT_ID, "team": team},
    )
    conn.execute(
        text(
            """
            INSERT INTO interaction_transcript (
              id, interaction_id, turn_index, speaker, at_sec, text, sentiment_delta
            ) VALUES (
              :id, :iid, 0, 'customer', 4, 'I already paid', -0.4
            )
            """
        ),
        {"id": f"T-{suffix}", "iid": ix},
    )
    return ix, str(cust), str(acct)


def test_active_handoff_empty_when_none_claimed(db_tx, as_actor) -> None:
    as_actor(AGENT)
    assert db.get_active_handoff_session() is None


def test_queue_scoped_to_actor_team(db_tx, as_actor) -> None:
    _seed_unclaimed(db_tx, team="card-collections", suffix="card")
    _seed_unclaimed(db_tx, team="retail-collections", suffix="ret")
    as_actor(AGENT)
    queue = db.list_handoff_queue()
    ids = {item["interactionId"] for item in queue["items"]}
    assert "IX-HO-card" in ids
    assert "IX-HO-ret" not in ids


def test_admin_sees_all_unclaimed(db_tx, as_actor) -> None:
    _seed_unclaimed(db_tx, team="retail-collections", suffix="adm")
    as_actor(ADMIN)
    queue = db.list_handoff_queue()
    ids = {item["interactionId"] for item in queue["items"]}
    assert "IX-HO-adm" in ids


def test_claim_then_second_caller_conflicts(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="race")
    as_actor(AGENT)
    session = db.claim_handoff(ix)
    assert session["claimed"] is True
    assert session["activeCall"]["escalationReason"] == "dispute"
    assert session["status"] == "active"
    as_actor(OTHER)
    with pytest.raises(ValueError, match="handoff_already_claimed"):
        db.claim_handoff(ix)


def test_snapshot_uses_handoff_reason_not_disposition(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="reason")
    db_tx.execute(
        text("UPDATE interactions SET disposition = 'escalated' WHERE id = :id"),
        {"id": ix},
    )
    as_actor(AGENT)
    db.claim_handoff(ix)
    session = db.get_handoff_session(ix)
    assert session["activeCall"]["escalationReason"] == "dispute"
    assert session["transcriptScript"][0]["text"] == "I already paid"
    assert session["sentimentSeries"]


def test_non_assignee_cannot_read_claimed_session(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="forbid")
    as_actor(AGENT)
    db.claim_handoff(ix)
    as_actor(OTHER)
    with pytest.raises(PermissionError, match="handoff_not_assigned"):
        db.get_handoff_session(ix)


def test_supervisor_can_monitor_claimed_session(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="mon")
    as_actor(AGENT)
    db.claim_handoff(ix)
    as_actor(ADMIN)
    session = db.get_handoff_session(ix)
    assert session["monitor"] is True
    assert session["claimed"] is True
    assert session["interactionId"] == ix


def test_wrap_up_completes_handoff_row(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="wrap")
    as_actor(AGENT)
    db.claim_handoff(ix)
    result = db.wrap_up_interaction(ix, {"disposition": "PTP captured", "notes": "cleared"})
    assert result["id"] == ix
    row = db_tx.execute(
        text(
            """
            SELECT i.status, i.disposition, h.completed_at
            FROM interactions i
            JOIN interaction_handoffs h ON h.interaction_id = i.id
            WHERE i.id = :id
            """
        ),
        {"id": ix},
    ).mappings().one()
    assert row["status"] == "completed"
    assert row["disposition"] == "PTP captured"
    assert row["completed_at"] is not None


def test_disclosure_write_and_identity_lock(db_tx, as_actor) -> None:
    ix, cust, _acct = _seed_unclaimed(db_tx, suffix="disc")
    as_actor(AGENT)
    db.claim_handoff(ix)
    session = db.record_handoff_disclosure(
        ix, {"itemId": "rule-recording", "ruleId": "rule-recording", "label": "Recording disclosure read"}
    )
    rec = next(i for i in session["complianceItems"] if i["ruleId"] == "rule-recording")
    assert rec["checked"] is True
    db.record_handoff_disclosure(ix, {"itemId": "identity", "ruleId": "rule-identity"})
    with pytest.raises(ValueError, match="identity_locked"):
        db.record_handoff_disclosure(ix, {"itemId": "identity", "ruleId": "rule-identity"})


def test_suggestion_accept(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="sug")
    db_tx.execute(
        text(
            """
            INSERT INTO ai_response_suggestions (id, interaction_id, suggestion_text, source)
            VALUES ('sug-ho', :iid, 'Offer a PTP today', 'playbook')
            """
        ),
        {"iid": ix},
    )
    as_actor(AGENT)
    db.claim_handoff(ix)
    session = db.accept_handoff_suggestion(ix, "sug-ho")
    hit = next(s for s in session["suggestions"] if s["id"] == "sug-ho")
    assert hit["accepted"] is True


def test_cross_tenant_handoff_is_not_found(db_tx, as_actor) -> None:
    as_actor(ADMIN)
    db_tx.execute(text("INSERT INTO tenants (id, name) VALUES ('rival.bank', 'Rival')"))
    db_tx.execute(
        text("INSERT INTO users (id, tenant_id, name) VALUES ('rv-user', 'rival.bank', 'Rival')")
    )
    db_tx.execute(
        text(
            "INSERT INTO products (id, tenant_id, name, type, is_active)"
            " VALUES ('rv-prod', 'rival.bank', 'Rival Card', 'card', true)"
        )
    )
    db_tx.execute(
        text(
            "INSERT INTO customers (id, tenant_id, name, risk)"
            " VALUES ('rv-cust', 'rival.bank', 'Rival Customer', 'low')"
        )
    )
    db_tx.execute(
        text(
            "INSERT INTO accounts (id, customer_id, product_id, status)"
            " VALUES ('rv-acct', 'rv-cust', 'rv-prod', 'active')"
        )
    )
    db_tx.execute(
        text(
            """
            INSERT INTO interactions (
              id, tenant_id, customer_id, account_id, handler_kind, handler_user_id,
              channel, status
            ) VALUES (
              'rv-ix', 'rival.bank', 'rv-cust', 'rv-acct', 'human', 'rv-user',
              'voice', 'active'
            )
            """
        )
    )
    db_tx.execute(
        text(
            """
            INSERT INTO interaction_handoffs (
              id, interaction_id, from_kind, from_bot_id, to_kind, reason, requested_at
            ) VALUES (
              'rv-ho', 'rv-ix', 'bot', :bot, 'human', 'dispute', now()
            )
            """
        ),
        {"bot": db.DEFAULT_BOT_ID},
    )
    with pytest.raises(KeyError):
        db.get_handoff_session("rv-ix")
    with pytest.raises(KeyError):
        db.claim_handoff("rv-ix")
