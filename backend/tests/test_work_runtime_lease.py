"""`working` is a claim with a lease, and a job leaves only from `working`.

`claim_next` selected `status IN ('submitted','working')` and set `working`
with nothing else: a job whose worker died was re-selected on every tick
forever, and one whose handler kept raising was re-run without bound. `finish`
and `park_input_required` updated unconditionally, so a late worker could move
a completed or cancelled job back to `failed`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from work_runtime import adapter_pg, idempotency_key, query, start_workflow


def _job(kind: str = "bounce_chase") -> str:
    ref = f"lease-{uuid.uuid4().hex[:8]}"
    return start_workflow(
        workflow_type=kind,
        payload={"triggerRef": ref},
        customer_id=None,
        idempotency_key=idempotency_key(workflow_type=kind, trigger_ref=ref),
    )["id"]


def _set(db_tx, job_id: str, **cols) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in cols)
    db_tx.execute(text(f"UPDATE work_runtime_jobs SET {sets} WHERE id = :id"), {"id": job_id, **cols})


def test_a_fresh_working_job_is_not_reclaimed(db_tx) -> None:
    jid = _job()
    first = adapter_pg.claim_next(("bounce_chase",))
    assert first and first["id"] == jid
    assert adapter_pg.claim_next(("bounce_chase",)) is None


def test_a_stale_working_job_is_reclaimed_after_its_lease(db_tx, monkeypatch) -> None:
    jid = _job()
    assert adapter_pg.claim_next(("bounce_chase",))["id"] == jid
    db_tx.execute(
        text("UPDATE work_runtime_jobs SET locked_at = now() - interval '1 hour' WHERE id = :id"),
        {"id": jid},
    )
    again = adapter_pg.claim_next(("bounce_chase",))
    assert again and again["id"] == jid
    row = db_tx.execute(
        text("SELECT attempts FROM work_runtime_jobs WHERE id = :id"), {"id": jid}
    ).mappings().one()
    assert row["attempts"] == 2


def test_attempts_are_capped(db_tx, monkeypatch) -> None:
    monkeypatch.setenv("WORK_RUNTIME_MAX_ATTEMPTS", "2")
    jid = _job()
    _set(db_tx, jid, attempts=2)
    assert adapter_pg.claim_next(("bounce_chase",)) is None
    row = query(jid)
    assert row is not None and row["status"] == "failed"
    assert "attempts exhausted" in (row.get("error") or "")


def test_finish_closes_only_a_working_job(db_tx) -> None:
    jid = _job()
    assert adapter_pg.finish(jid, ok=True, result={"x": 1}) is False  # still submitted
    assert adapter_pg.claim_next(("bounce_chase",))["id"] == jid
    assert adapter_pg.finish(jid, ok=True, result={"x": 1}) is True
    # A late worker cannot move a completed job back to failed.
    assert adapter_pg.finish(jid, ok=False, error="late") is False
    row = query(jid)
    assert row is not None and row["status"] == "completed"


def test_park_does_not_touch_a_job_that_is_not_working(db_tx) -> None:
    jid = _job()
    _set(db_tx, jid, status="cancelled")
    adapter_pg.park_input_required(jid, "supervisor_approval")
    row = query(jid)
    assert row is not None and row["status"] == "cancelled"


# --- the same rule on the two neighbouring queues ---------------------------


def test_a_finished_turn_cannot_be_cancelled(db_tx) -> None:
    """A takeover after the reply went out used to rewrite `succeeded` as
    `cancelled`, and the trace then said the reply was never sent."""
    import bot_jobs

    msg = db_tx.execute(
        text(
            """
            SELECT m.id AS message_id, c.id AS conversation_id, c.customer_id
              FROM messages m JOIN conversations c ON c.id = m.conversation_id
             WHERE c.customer_id IS NOT NULL LIMIT 1
            """
        )
    ).mappings().first()
    assert msg is not None
    job = bot_jobs.enqueue_bot_turn(
        db_tx,
        conversation_id=msg["conversation_id"],
        customer_id=msg["customer_id"],
        trigger_message_id=msg["message_id"],
        trigger_provider_ref=None,
    )
    assert job is not None
    jid = job["id"]
    db_tx.execute(text("UPDATE bot_turn_jobs SET status = 'succeeded' WHERE id = :id"), {"id": jid})
    assert bot_jobs.mark_cancelled(db_tx, jid, "takeover_mid_flight") is False
    status = db_tx.execute(
        text("SELECT status FROM bot_turn_jobs WHERE id = :id"), {"id": jid}
    ).scalar_one()
    assert status == "succeeded"


