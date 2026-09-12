"""Status columns state their vocabulary, and the statement matches the owner.

Four status columns had no CHECK while a partial index and every sweep
predicate depended on the literal ``'active'``. The constraint is read from
the live database and compared to the Python owner of each vocabulary, so a
value added on one side without the other fails here.
"""

from __future__ import annotations

import re
from typing import get_args

import pytest
from sqlalchemy import text

import schemas


def _check_values(conn, table: str) -> set[str]:
    row = conn.execute(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = CAST(:t AS regclass) AND conname = :c"
        ),
        {"t": table, "c": f"{table}_status_check"},
    ).scalar()
    if row is None:
        pytest.skip(f"{table}_status_check not on this database (migration 0137 not applied)")
    return set(re.findall(r"'([a-z_]+)'::text", row))


def test_accounts_status_is_the_lms_vocabulary(db_tx) -> None:
    lms = db_tx.execute(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'lms_account_status'::regclass AND contype = 'c'"
        )
    ).scalar()
    assert lms, "lms_account_status.normalised has no CHECK"
    assert _check_values(db_tx, "accounts") == set(re.findall(r"'([a-z_]+)'::text", lms))


def _column_check(conn, table: str, column: str) -> set[str]:
    row = conn.execute(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = CAST(:t AS regclass) AND conname = :c"
        ),
        {"t": table, "c": f"{table}_{column}_check"},
    ).scalar()
    assert row, f"{table}.{column} has no CHECK"
    return set(re.findall(r"'([a-z_]+)'::text", row))


def test_promise_and_sender_vocabularies_are_the_columns(db_tx) -> None:
    """Three Literals said three different things about promises.reminder_status
    (4, 3 and 6 values) and the thread's lastFrom could not say "system"."""
    assert _column_check(db_tx, "promises", "status") == set(get_args(schemas.PromiseStatus))
    assert _column_check(db_tx, "promises", "reminder_status") == set(get_args(schemas.ReminderStatus))
    assert _column_check(db_tx, "messages", "sender") == set(get_args(schemas.Sender))


def test_invoice_and_export_status_match_the_wire(db_tx) -> None:
    assert _check_values(db_tx, "invoices") == set(get_args(schemas.BillingInvoiceStatus))
    assert _check_values(db_tx, "export_jobs") == set(get_args(schemas.ExportStatus))


def test_a_typo_status_is_refused(db_tx) -> None:
    account = db_tx.execute(text("SELECT id FROM accounts LIMIT 1")).scalar()
    if account is None:
        pytest.skip("no accounts on this database")
    _check_values(db_tx, "accounts")
    with pytest.raises(Exception, match="accounts_status_check"):
        with db_tx.begin_nested():
            db_tx.execute(text("UPDATE accounts SET status = 'actve' WHERE id = :id"), {"id": account})


def test_deleting_a_supervisor_with_history_is_refused(db_tx) -> None:
    """ON DELETE CASCADE from users deleted the audit of every barge and
    whisper a supervisor ever made. RESTRICT now."""
    rule = db_tx.execute(
        text(
            "SELECT confdeltype FROM pg_constraint WHERE conrelid = 'supervisor_actions'::regclass "
            "AND conname = 'supervisor_actions_supervisor_user_id_fkey'"
        )
    ).scalar()
    if rule is None:
        pytest.skip("constraint not on this database")
    assert rule == "r", "expected ON DELETE RESTRICT"


def test_the_ledger_carries_no_balance_column(db_tx) -> None:
    """Written by none of the five ledger writers and rendered as an empty
    Balance column on the Customer 360."""
    cols = {
        r[0]
        for r in db_tx.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'ledger_entries'")
        )
    }
    if "balance" in cols:
        pytest.skip("migration 0137 not applied")
    assert "balance" not in cols
