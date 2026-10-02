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


def _customer_of(conn, user_id: str | None, *, accounts: int = 1) -> str:
    """A synthetic customer owned by ``user_id`` (None: unowned), with its own accounts."""
    cid = _uid("CUST")
    conn.execute(
        text(
            "INSERT INTO customers (id, tenant_id, name, risk, assigned_user_id) "
            "VALUES (:id, :t, 'Workspace Fixture', 'low', :u)"
        ),
        {"id": cid, "t": db.current_tenant(), "u": user_id},
    )
    for _ in range(accounts):
        conn.execute(
            text(
                # A balance: the Gate refuses outreach to a settled account first.
                "INSERT INTO accounts (id, customer_id, product_id, outstanding) "
                "VALUES (:id, :c, (SELECT id FROM products ORDER BY id LIMIT 1), 1000)"
            ),
            {"id": _uid("ACC"), "c": cid},
        )
    return cid


def _accounts(conn, customer_id: str) -> list[str]:
    return list(
        conn.execute(
            text("SELECT id FROM accounts WHERE customer_id = :c ORDER BY id"), {"c": customer_id}
        ).scalars()
    )


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
    customer = _customer_of(db_tx, ADMIN, accounts=2)
    second = _accounts(db_tx, customer)[-1]
    cb = _callback(
        db_tx, customer, at=_now() + timedelta(seconds=30), assignee=ADMIN, account_id=second
    )
    as_actor(ADMIN)
    nxt = db.workspace_summary(assignee="me")["nextCallback"]
    assert nxt["id"] == cb
    assert nxt["accountId"] == second


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
    _callback(db_tx, _customer_of(db_tx, ADMIN), at=_now() + timedelta(minutes=30), assignee=ADMIN)
    as_actor(ADMIN)
    rows = db.workspace_summary(assignee="all")["attention"]
    assert rows
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


def test_the_attention_filter_is_overdue_and_due_soon_together(db_tx, as_actor) -> None:
    """"View all" lists everything the attention count counted, not only the overdue half."""
    customer = _customer_of(db_tx, ADMIN)
    soon = _callback(db_tx, customer, at=_now() + timedelta(minutes=30), assignee=ADMIN)
    as_actor(ADMIN)
    rows = db.list_work_items(assignee="all", due="attention", limit=1000)
    counts = db.workspace_summary(assignee="all")["queueCounts"]
    assert soon in {r["id"] for r in rows}
    assert len(rows) == counts["overdue"] + counts["dueSoon"]


def test_a_contact_warning_past_its_check_limit_says_it_is_partial(db_tx, as_actor, monkeypatch) -> None:
    import db_workspace

    _callback(db_tx, _customer_of(db_tx, ADMIN), at=_now() + timedelta(days=1), assignee=ADMIN)
    monkeypatch.setattr(db_workspace, "BLOCKED_CHECK_LIMIT", 0)
    as_actor(ADMIN)
    assert db.workspace_summary(assignee="me")["callbacksBlockedPartial"] is True


def test_undated_work_never_pages_ahead_of_a_deadline(db_tx, as_actor) -> None:
    customer = _customer_of(db_tx, ADMIN)
    _callback(db_tx, customer, at=_now() + timedelta(minutes=30), assignee=ADMIN)
    db_tx.execute(
        text(
            "INSERT INTO disputes (id, customer_id, account_id, type, disputed_amount, source, "
            "status, priority, transcript_snippet, sla_due_at, created_at) VALUES "
            "(:id, :c, (SELECT id FROM accounts WHERE customer_id = :c LIMIT 1), 'wrong_amount', 1, "
            "'agent', 'new', 'normal', 'fixture', NULL, now())"
        ),
        {"id": _uid("DSP"), "c": customer},
    )
    as_actor(ADMIN)
    dues = [r["dueAt"] for r in db.list_work_items(assignee="all", limit=1000)]
    assert None in dues
    assert all(d is None for d in dues[dues.index(None):]), "an undated row sorted ahead of a dated one"


#: One synthetic row of each deep-linkable record, on ``:c`` / ``:a``.
_RECORD_INSERT = {
    "list_callbacks": "INSERT INTO callbacks (id, customer_id, account_id, assignee_user_id, "
    "reason, scheduled_at, status) VALUES (:id, :c, :a, :u, 'general', now() + interval '1 day', "
    "'scheduled')",
    "list_disputes": "INSERT INTO disputes (id, customer_id, account_id, type, disputed_amount, "
    "source, status, priority, transcript_snippet) VALUES (:id, :c, :a, 'wrong_amount', 1, "
    "'agent', 'new', 'normal', 'fixture')",
    "list_documents": "INSERT INTO document_requests (id, customer_id, account_id, doc_type, "
    "delivery_channel, status) VALUES (:id, :c, :a, 'statement', 'email', 'requested')",
    "list_promises": "INSERT INTO promises (id, customer_id, account_id, owner_kind, "
    "owner_user_id, amount, promised_at, status, reminder_status) VALUES (:id, :c, :a, 'human', "
    ":u, 1, now() + interval '1 day', 'upcoming', 'off')",
    "list_leads": "INSERT INTO leads (id, customer_id, account_id, stage) "
    "VALUES (:id, :c, :a, 'interested')",
}


@pytest.mark.parametrize(
    ("fn", "key"),
    [
        ("list_callbacks", "callback_id"),
        ("list_disputes", "dispute_id"),
        ("list_documents", "document_id"),
        ("list_promises", "promise_id"),
        ("list_leads", "lead_id"),
    ],
)
def test_a_deep_link_reads_its_record_whatever_page_it_is_on(db_tx, as_actor, fn, key) -> None:
    """Two of them: a page of one can hold at most one, so an ignored id fails here.
    On two accounts: an account holds one open promise."""
    customer = _customer_of(db_tx, ADMIN, accounts=2)
    ids = [_uid("REC"), _uid("REC")]
    for rid, account in zip(ids, _accounts(db_tx, customer), strict=True):
        db_tx.execute(
            text(_RECORD_INSERT[fn]), {"id": rid, "c": customer, "a": account, "u": ADMIN}
        )
    as_actor(ADMIN)
    for rid in ids:
        assert [r["id"] for r in getattr(db, fn)(limit=1, **{key: rid})] == [rid]
    assert getattr(db, fn)(**{key: "NO-SUCH-ID"}) == []


def test_customer_search_reaches_every_account_past_the_first_page(db_tx, as_actor) -> None:
    customer = _customer_of(db_tx, ADMIN, accounts=2)
    second = _accounts(db_tx, customer)[-1]
    as_actor(ADMIN)
    assert [c["id"] for c in db.list_customers(limit=5, q=second)] == [customer]
    assert [c["id"] for c in db.list_customers(limit=5, q=customer)] == [customer]
    assert db.list_customers(q="NO-SUCH-CUSTOMER-WS") == []
