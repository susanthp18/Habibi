"""A nightly runs once across replicas; an MCP task is leased, retried and dead-lettered.

A module global was the marker for the worker's daily jobs, so two replicas
ran every nightly twice and a restart ran the night again. mcp_tasks had a
status and nothing else: a worker that died mid-task left it running
forever, and a failure was final on the first try.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

import bot_jobs
import db
from agent_core.clock import utc_now
from agent_core.mcp_http import tasks


def test_a_day_is_claimed_by_exactly_one_caller(db_tx) -> None:
    assert bot_jobs.claim_daily(db.engine, "probe_nightly", "2026-09-13")
    # A second replica, or the same worker after a restart.
    assert not bot_jobs.claim_daily(db.engine, "probe_nightly", "2026-09-13")
    # Another job, and another day, are their own claims.
    assert bot_jobs.claim_daily(db.engine, "probe_other", "2026-09-13")
    assert bot_jobs.claim_daily(db.engine, "probe_nightly", "2026-09-14")


def _task(conn, *, status: str, attempt: int, locked_age_s: int = 0) -> str:
    tid = f"mcpt-probe-{status}-{attempt}-{locked_age_s}"
    conn.execute(
        text(
            """
            INSERT INTO mcp_tasks (id, tenant_id, kind, status, attempt, locked_at, locked_by, payload)
            VALUES (:id, :t, 'statement_generate', :status, :attempt, :locked_at, 'probe', '{}'::jsonb)
            """
        ),
        {
            "id": tid,
            "t": db._tenant(),
            "status": status,
            "attempt": attempt,
            "locked_at": utc_now() - timedelta(seconds=locked_age_s),
        },
    )
    return tid


def _status(conn, tid: str) -> str:
    return conn.execute(text("SELECT status FROM mcp_tasks WHERE id = :id"), {"id": tid}).scalar_one()


def test_a_claim_takes_a_lease_and_counts_the_attempt(db_tx) -> None:
    tid = _task(db_tx, status="queued", attempt=0)
    claimed = tasks.claim_next()
    assert claimed and claimed["id"] == tid
    row = db_tx.execute(
        text("SELECT status, attempt, locked_at, locked_by FROM mcp_tasks WHERE id = :id"), {"id": tid}
    ).mappings().one()
    assert row["status"] == "running" and row["attempt"] == 1
    assert row["locked_at"] is not None and row["locked_by"]


def test_a_failure_retries_with_backoff_then_dead_letters(db_tx, monkeypatch) -> None:
    monkeypatch.setenv("BOT_JOB_MAX_ATTEMPTS", "2")
    tid = _task(db_tx, status="running", attempt=1)
    assert tasks.finish(tid, ok=False, error="boom") == "queued"
    run_after = db_tx.execute(text("SELECT run_after FROM mcp_tasks WHERE id = :id"), {"id": tid}).scalar_one()
    assert run_after > utc_now()
    # Not claimable until the backoff has passed.
    assert tasks.claim_next() is None
    db_tx.execute(text("UPDATE mcp_tasks SET run_after = now() WHERE id = :id"), {"id": tid})
    assert tasks.claim_next()["id"] == tid
    assert tasks.finish(tid, ok=False, error="boom again") == "dead"
    assert _status(db_tx, tid) == "dead"


def test_a_task_whose_worker_died_is_reclaimed(db_tx, monkeypatch) -> None:
    monkeypatch.setenv("BOT_JOB_STALE_RUNNING_SEC", "60")
    monkeypatch.setenv("BOT_JOB_MAX_ATTEMPTS", "5")
    stuck = _task(db_tx, status="running", attempt=1, locked_age_s=600)
    fresh = _task(db_tx, status="running", attempt=1, locked_age_s=5)
    spent = _task(db_tx, status="running", attempt=5, locked_age_s=600)
    assert tasks.reclaim_stale() == 2
    assert _status(db_tx, stuck) == "queued"
    assert _status(db_tx, fresh) == "running"
    assert _status(db_tx, spent) == "dead"
