"""A status column is a state machine, and PATCH honours it.

Four writers took any status for any other -- a resolved dispute back to
`new`, a completed callback back to `scheduled`, a sent document back to
`requested`, a done follow-up straight to `snoozed`. Each carries a table
now, and `db_core.assert_transition` refuses what the table does not allow
(a 409 at the route). Same status is a no-op, not a transition.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

import db
import db_callbacks
import db_core
import db_documents
import db_leads


def test_the_helper_refuses_what_the_table_does_not_allow() -> None:
    table = {"a": frozenset({"b"})}
    db_core.assert_transition("x", "a", "b", table)
    db_core.assert_transition("x", "a", "a", table)
    db_core.assert_transition("x", "b", None, table)
    with pytest.raises(ValueError, match="illegal_transition:x:b->a"):
        db_core.assert_transition("x", "b", "a", table)


def _first(conn, sql: str):
    row = conn.execute(text(sql)).mappings().first()
    if row is None:
        pytest.skip("seed has no row for this case")
    return row


def _customer(conn) -> str:
    return str(conn.execute(text("SELECT id FROM customers WHERE id <> 'UNKNOWN-CALLER' LIMIT 1")).scalar())


def test_a_resolved_dispute_does_not_reopen_to_new(db_tx) -> None:
    row = _first(db_tx, "SELECT id FROM disputes WHERE status = 'resolved' LIMIT 1")
    with pytest.raises(ValueError, match="illegal_transition:dispute:resolved->new"):
        db.patch_dispute(row["id"], {"status": "new"})
    assert db.patch_dispute(row["id"], {"status": "resolved"})["status"] == "resolved"


def test_a_completed_callback_is_not_rescheduled_into_the_past(db_tx) -> None:
    db_tx.execute(
        text(
            "INSERT INTO callbacks (id, customer_id, reason, scheduled_at, status) "
            "VALUES ('CB-TRANSITION-PROBE', :c, 'probe', now(), 'completed')"
        ),
        {"c": _customer(db_tx)},
    )
    with pytest.raises(ValueError, match="illegal_transition:callback:completed->scheduled"):
        db_callbacks.patch_callback("CB-TRANSITION-PROBE", {"status": "scheduled"})


def test_a_sent_document_is_not_requested_again_in_place(db_tx) -> None:
    row = _first(db_tx, "SELECT id FROM document_requests WHERE status = 'sent' LIMIT 1")
    with pytest.raises(ValueError, match="illegal_transition:document_request:sent->requested"):
        db_documents.patch_document_request(row["id"], {"status": "requested"})


def test_a_done_followup_reopens_only_to_open(db_tx) -> None:
    row = _first(db_tx, "SELECT id FROM followups WHERE status = 'open' LIMIT 1")
    assert db_leads.patch_followup(row["id"], {"status": "done"})["status"] == "done"
    with pytest.raises(ValueError, match="illegal_transition:followup:done->snoozed"):
        db_leads.patch_followup(row["id"], {"status": "snoozed"})
    assert db_leads.patch_followup(row["id"], {"status": "open"})["status"] == "open"


def test_a_resolved_violation_reopens_only_into_review(db_tx) -> None:
    """The four other PATCHes got a transition table in pass 6; this one still
    took any->any, so a resolved breach could be flipped straight to open."""
    import db_violations
    from sqlalchemy import text

    vid = db_tx.execute(text("SELECT id FROM violations WHERE status <> 'resolved' LIMIT 1")).scalar()
    if vid is None:
        pytest.skip("no open violation seeded")
    db_violations.patch_violation(vid, {"status": "resolved"})
    with pytest.raises(ValueError, match="illegal_transition:violation:resolved->open"):
        db_violations.patch_violation(vid, {"status": "open"})
    assert db_violations.patch_violation(vid, {"status": "in_review"})["status"] == "in_review"
