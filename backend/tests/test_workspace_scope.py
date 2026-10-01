"""My Workspace: what "yours" means, and that every number on it says what it counts.

The queue used to fall back to the whole tenant book when an operator had no
assigned rows, under a header that still read "Items routed to you". The summary
beside it skipped the visibility predicate the queue applied, anchored its
"rolling 7 days" to the last interaction in the tenant, and counted any
interaction on any channel as a handled call.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

import actor_context
import authz
import db

AGENT = "sara-khan"
OTHER_AGENT = "arjun-mehta"
ADMIN = "priya-nair"


@pytest.fixture
def as_actor():
    tokens = []

    def _use(user_id: str):
        tokens.append(actor_context.set_actor_user_id(user_id))

    yield _use
    for token in reversed(tokens):
        actor_context.reset_actor_user_id(token)


@pytest.fixture
def enforce(monkeypatch):
    monkeypatch.setenv("VISIBILITY_ENFORCE", "1")
    authz.invalidate_permission_cache()
    yield
    authz.invalidate_permission_cache()


def _uid(prefix: str) -> str:
    return f"{prefix}-WS-{uuid.uuid4().hex[:8].upper()}"


def _customer_of(conn, user_id: str | None) -> str:
    clause = "assigned_user_id = :u" if user_id else "assigned_user_id IS NULL"
    row = conn.execute(
        text(f"SELECT id FROM customers WHERE {clause} ORDER BY id LIMIT 1"), {"u": user_id}
    ).scalar()
    if row is None:
        pytest.skip(f"seed has no customer for {user_id!r}")
    return row


def _callback(conn, customer_id: str, *, at: datetime, assignee: str | None = None,
              account_id: str | None = None, status: str = "scheduled") -> str:
    cid = _uid("CB")
    conn.execute(
        text(
            "INSERT INTO callbacks (id, customer_id, account_id, assignee_user_id, reason, "
            "scheduled_at, status) VALUES (:id, :c, :a, :u, 'general', :at, :s)"
        ),
        {"id": cid, "c": customer_id, "a": account_id, "u": assignee, "at": at, "s": status},
    )
    return cid


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def test_an_operator_with_nothing_assigned_has_an_empty_queue(db_tx, as_actor) -> None:
    """No silent fallback to the tenant book: 'mine' is mine, the pool is separate."""
    as_actor("entra-demo-nobody")
    assert db.list_work_items(assignee="me") == []
    pool = db.list_work_items(assignee="pool", limit=1000)
    assert pool, "the seed has no unassigned work at all"
    assert all(row["assigneeUserId"] is None for row in pool)


def test_mine_includes_unassigned_ai_work_on_my_book(db_tx, as_actor) -> None:
    """The AI files callbacks and promises with no assignee; they belong to the
    agent whose book the borrower is on, not to nobody."""
    mine = _customer_of(db_tx, AGENT)
    assigned = _callback(db_tx, mine, at=_now() + timedelta(days=2), assignee=AGENT)
    ai_filed = _callback(db_tx, mine, at=_now() + timedelta(days=2))
    as_actor(AGENT)
    ids = {row["id"] for row in db.list_work_items(assignee="me", limit=1000)}
    assert {assigned, ai_filed} <= ids
    pool = {row["id"] for row in db.list_work_items(assignee="pool", limit=1000)}
    assert ai_filed not in pool


def test_summary_never_shows_what_the_queue_hides(db_tx, as_actor, enforce) -> None:
    hidden = _callback(
        db_tx, _customer_of(db_tx, AGENT), at=_now() + timedelta(minutes=1), assignee=AGENT
    )
    as_actor(OTHER_AGENT)
    summary = db.workspace_summary(assignee="all")
    assert (summary["nextCallback"] or {}).get("id") != hidden
    assert hidden not in {row["id"] for row in summary["attention"]}
    assert hidden not in {row["id"] for row in db.list_work_items(assignee="all", limit=1000)}


def test_queue_counts_cover_the_whole_scope_not_one_page(db_tx, as_actor) -> None:
    as_actor(ADMIN)
    rows = db.list_work_items(assignee="all", limit=1000)
    counts = db.workspace_summary(assignee="all")["queueCounts"]
    assert counts["total"] == len(rows)
    assert sum(counts["byType"].values()) == len(rows)
    assert len(db.list_work_items(assignee="all", limit=1)) == 1


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


def test_queue_callback_time_is_converted_to_ist(db_tx, as_actor) -> None:
    at = (_now() + timedelta(days=3)).replace(hour=9, minute=0, second=0, microsecond=0)
    cb = _callback(db_tx, _customer_of(db_tx, ADMIN), at=at, assignee=ADMIN)
    as_actor(ADMIN)
    row = next(r for r in db.list_work_items(assignee="me", limit=1000) if r["id"] == cb)
    assert row["type"] == "Callback · 2:30 PM IST"


def test_next_callback_names_the_callbacks_own_account(db_tx, as_actor) -> None:
    row = db_tx.execute(
        text(
            "SELECT customer_id, max(id) AS account_id FROM accounts GROUP BY customer_id "
            "HAVING count(*) > 1 ORDER BY customer_id LIMIT 1"
        )
    ).mappings().first()
    if row is None:
        pytest.skip("seed has no customer with two accounts")
    cb = _callback(
        db_tx, row["customer_id"], at=_now() + timedelta(seconds=30), assignee=ADMIN,
        account_id=row["account_id"],
    )
    as_actor(ADMIN)
    nxt = db.workspace_summary(assignee="me")["nextCallback"]
    assert nxt["id"] == cb
    assert nxt["accountId"] == row["account_id"]


def test_next_callback_is_upcoming_not_missed_or_in_progress(db_tx, as_actor) -> None:
    customer = _customer_of(db_tx, ADMIN)
    _callback(db_tx, customer, at=_now() - timedelta(minutes=20), assignee=ADMIN, status="missed")
    _callback(db_tx, customer, at=_now() - timedelta(minutes=10), assignee=ADMIN, status="in_progress")
    as_actor(ADMIN)
    nxt = db.workspace_summary(assignee="me")["nextCallback"]
    assert nxt is None or datetime.fromisoformat(nxt["scheduledAt"]) >= _now() - timedelta(seconds=5)
    assert nxt is None or nxt["status"] in {"scheduled", "reminded", "rescheduled"}


def test_lapsed_callbacks_are_marked_missed_by_the_backend(db_tx) -> None:
    """Opening the Callbacks page used to be what marked them missed."""
    import db_callbacks

    customer = _customer_of(db_tx, ADMIN)
    lapsed = _callback(db_tx, customer, at=_now() - timedelta(hours=2))
    upcoming = _callback(db_tx, customer, at=_now() + timedelta(hours=2))
    live = _callback(db_tx, customer, at=_now() - timedelta(hours=2), status="in_progress")
    db_callbacks.mark_lapsed_missed(db.engine)
    status = dict(
        db_tx.execute(
            text("SELECT id, status FROM callbacks WHERE id = ANY(:ids)"),
            {"ids": [lapsed, upcoming, live]},
        ).all()
    )
    assert status == {lapsed: "missed", upcoming: "scheduled", live: "in_progress"}


def test_contact_warning_is_the_gates_verdict(db_tx, as_actor, monkeypatch) -> None:
    """The banner counted preferred-hour misses and called them the allowed
    contact window; the Gate is the only owner of that answer."""
    import contact_policy

    ist = timezone(timedelta(hours=5, minutes=30))
    tomorrow = (_now().astimezone(ist) + timedelta(days=1)).date()
    at = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 3, 0, tzinfo=ist)
    _callback(db_tx, _customer_of(db_tx, ADMIN), at=at, assignee=ADMIN)
    as_actor(ADMIN)
    assert db.workspace_summary(assignee="me")["callbacksBlockedCount"] >= 1
    monkeypatch.setattr(contact_policy, "blocks_scheduling", lambda *a, **k: None)
    assert db.workspace_summary(assignee="me")["callbacksBlockedCount"] == 0


# ---------------------------------------------------------------------------
# Attention rows
# ---------------------------------------------------------------------------


def test_attention_rows_carry_their_entity_not_a_label_to_parse(db_tx, as_actor) -> None:
    as_actor(ADMIN)
    rows = db.workspace_summary(assignee="all")["attention"]
    assert rows, "seed has no overdue work"
    for row in rows:
        assert row["entityType"]
        assert row["customerId"]
        assert row["dueAt"]
    followups = [r for r in rows if r["entityType"] == "followup"]
    for row in followups:
        promise = db_tx.execute(
            text("SELECT promise_id FROM followups WHERE id = :id"), {"id": row["id"]}
        ).scalar()
        assert row["relatedId"] == promise


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def _interaction(conn, *, handler: str, channel: str = "voice", status: str = "completed",
                 duration: int = 100) -> str:
    iid = _uid("INT")
    conn.execute(
        text(
            "INSERT INTO interactions (id, tenant_id, customer_id, handler_kind, handler_user_id, "
            "channel, direction, status, started_at, duration_sec, source_payload) "
            "VALUES (:id, :t, :c, 'human', :u, :ch, 'outbound', :s, now(), :d, '{}'::jsonb)"
        ),
        {"id": iid, "t": db.current_tenant(), "c": _customer_of(conn, ADMIN), "u": handler,
         "ch": channel, "s": status, "d": duration},
    )
    return iid


def test_calls_handled_counts_completed_human_voice_calls_only(db_tx, as_actor) -> None:
    as_actor(ADMIN)
    before = db.workspace_summary(assignee="me")["stats"]["callsHandled"]
    _interaction(db_tx, handler=ADMIN)
    _interaction(db_tx, handler=ADMIN, channel="whatsapp")
    _interaction(db_tx, handler=ADMIN, status="failed")
    after = db.workspace_summary(assignee="me")["stats"]
    assert after["callsHandled"] == before + 1
    end = datetime.fromisoformat(after["windowEnd"])
    assert abs((end - _now()).total_seconds()) < 120, "the window ends now, not at the last call"


def test_promises_captured_follow_the_call_not_the_current_owner(db_tx, as_actor) -> None:
    as_actor(ADMIN)
    before = db.workspace_summary(assignee="me")["stats"]["promisesCount"]
    iid = _interaction(db_tx, handler=ADMIN)
    customer = _customer_of(db_tx, ADMIN)
    account = db_tx.execute(
        text("SELECT id FROM accounts WHERE customer_id = :c LIMIT 1"), {"c": customer}
    ).scalar()
    db_tx.execute(
        text(
            "INSERT INTO promises (id, customer_id, account_id, interaction_id, owner_kind, "
            "owner_user_id, amount, promised_at, status, reminder_status) VALUES (:id, :c, :a, :i, 'human', :o, "
            "500, now() + interval '3 days', 'upcoming', 'off')"
        ),
        {"id": _uid("PRM"), "c": customer, "a": account, "i": iid, "o": AGENT},
    )
    assert db.workspace_summary(assignee="me")["stats"]["promisesCount"] == before + 1


# ---------------------------------------------------------------------------
# Presence
# ---------------------------------------------------------------------------


def test_reading_presence_does_not_set_anyone_available(db_tx, as_actor) -> None:
    db_tx.execute(text("DELETE FROM agent_presence WHERE user_id = :u"), {"u": AGENT})
    as_actor(AGENT)
    assert db.get_agent_presence() == {"status": "offline", "sinceAt": None}
    assert not db_tx.execute(
        text("SELECT 1 FROM agent_presence WHERE user_id = :u"), {"u": AGENT}
    ).first()
