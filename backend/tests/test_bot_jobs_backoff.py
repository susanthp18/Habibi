"""A bot turn that keeps failing waits before it runs again.

Two ways a job could be re-run back to back: a retry's exponent was capped
at 6, so the documented 300 s ceiling was unreachable and every retry after
the sixth waited 64 s; and a job reclaimed from a dead worker got no
`run_after` at all, so one that crashed its worker every time was claimed
again the instant the reaper ran.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

import bot_jobs
from agent_core.clock import utc_now


def _job(conn, *, attempt: int, status: str, locked_age_s: int = 0) -> str:
    conv = conn.execute(text("SELECT id, customer_id FROM conversations LIMIT 1")).mappings().first()
    assert conv, "seed has no conversation"
    jid = f"BJ-BACKOFF-{attempt}-{status}"
    conn.execute(
        text(
            "INSERT INTO bot_turn_jobs (id, conversation_id, customer_id, attempt, status, locked_at, locked_by) "
            "VALUES (:id, :cv, :cu, :attempt, :status, :locked_at, 'probe')"
        ),
        {
            "id": jid,
            "cv": conv["id"],
            "cu": conv["customer_id"],
            "attempt": attempt,
            "status": status,
            "locked_at": utc_now() - timedelta(seconds=locked_age_s),
        },
    )
    return jid


def _run_after_delay(conn, jid: str) -> float:
    row = conn.execute(text("SELECT run_after, now() AS now FROM bot_turn_jobs WHERE id = :id"), {"id": jid}).mappings().first()
    return (row["run_after"] - row["now"]).total_seconds()


def test_a_retry_backs_off_up_to_the_documented_ceiling(db_tx, monkeypatch) -> None:
    monkeypatch.setenv("BOT_JOB_MAX_ATTEMPTS", "12")
    jid = _job(db_tx, attempt=8, status="running")
    assert bot_jobs.mark_failed_or_retry(db_tx, {"id": jid, "attempt": 8}, "boom") == "queued"
    # 2**8 = 256 s under the 300 s cap; the old exponent cap of 6 gave 64 s.
    assert 250 <= _run_after_delay(db_tx, jid) <= 257


def test_a_reclaimed_job_waits_like_a_failed_one(db_tx, monkeypatch) -> None:
    monkeypatch.setenv("BOT_JOB_STALE_RUNNING_SEC", "60")
    jid = _job(db_tx, attempt=3, status="running", locked_age_s=3600)
    bot_jobs.reclaim_stuck_jobs(db_tx)
    row = db_tx.execute(text("SELECT status FROM bot_turn_jobs WHERE id = :id"), {"id": jid}).mappings().first()
    assert row["status"] == "queued"
    assert 7 <= _run_after_delay(db_tx, jid) <= 8
