"""Postgres + worker drain. Survives API process restart via job rows."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text

import db
import request_context

TERMINAL = frozenset({"completed", "failed", "cancelled"})


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workflowType": row["workflow_type"],
        "status": row["status"],
        "customerId": row.get("customer_id"),
        "payload": row.get("payload") or {},
        "result": row.get("result") or {},
        "error": row.get("error"),
        "idempotencyKey": row["idempotency_key"],
        "inputRequiredReason": row.get("input_required_reason"),
        "approvedBy": row.get("approved_by"),
        "createdAt": str(row["created_at"]) if row.get("created_at") else None,
        "updatedAt": str(row["updated_at"]) if row.get("updated_at") else None,
    }


def start_workflow(
    *,
    workflow_type: str,
    payload: dict[str, Any],
    customer_id: str | None,
    idempotency_key: str,
    conn: Any | None = None,
) -> dict[str, Any]:
    if not idempotency_key.strip():
        raise ValueError("idempotency_key_required")
    if not workflow_type.strip():
        raise ValueError("workflow_type_required")
    jid = f"wrj-{uuid.uuid4().hex[:12]}"

    def _write(active: Any) -> dict[str, Any]:
        existing = db._one(
            active.execute(
                text(
                    """
                    SELECT * FROM work_runtime_jobs
                     WHERE tenant_id = :t AND idempotency_key = :k
                    """
                ),
                {"t": db._tenant(), "k": idempotency_key},
            )
        )
        if existing:
            return _public(existing)
        active.execute(
            text(
                """
                INSERT INTO work_runtime_jobs (
                  id, tenant_id, workflow_type, status, customer_id, payload,
                  idempotency_key, request_id
                ) VALUES (
                  :id, :t, :wt, 'submitted', :cid, CAST(:payload AS jsonb), :k, :rid
                )
                """
            ),
            {
                "id": jid,
                "t": db._tenant(),
                "wt": workflow_type,
                "cid": customer_id,
                "payload": db._jsonb(payload),
                "k": idempotency_key,
                "rid": request_context.get_request_id(),
            },
        )
        row = db._one(
            active.execute(
                text("SELECT * FROM work_runtime_jobs WHERE id = :id AND tenant_id = :t"),
                {"id": jid, "t": db._tenant()},
            )
        )
        assert row is not None
        return _public(row)

    if conn is not None:
        return _write(conn)
    with db.engine.begin() as active:
        return _write(active)


def signal(job_id: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    sid = f"wrs-{uuid.uuid4().hex[:12]}"
    with db.engine.begin() as conn:
        row = db._one(
            conn.execute(
                text("SELECT * FROM work_runtime_jobs WHERE id = :id AND tenant_id = :t"),
                {"id": job_id, "t": db._tenant()},
            )
        )
        if not row:
            raise KeyError("work_job_not_found")
        conn.execute(
            text(
                """
                INSERT INTO work_runtime_signals (id, job_id, name, payload)
                VALUES (:id, :jid, :name, CAST(:payload AS jsonb))
                """
            ),
            {"id": sid, "jid": job_id, "name": name, "payload": db._jsonb(payload)},
        )
        if name in {"approve", "reject"} and row["status"] == "input_required":
            nxt = "submitted" if name == "approve" else "cancelled"
            conn.execute(
                text(
                    """
                    UPDATE work_runtime_jobs
                       SET status = :st,
                           approved_by = COALESCE(:uid, approved_by),
                           input_required_reason = CASE WHEN :st = 'cancelled' THEN input_required_reason ELSE NULL END
                     WHERE id = :id
                    """
                ),
                {"st": nxt, "uid": payload.get("userId") or payload.get("user_id"), "id": job_id},
            )
    got = query(job_id)
    assert got is not None
    return got


def query(job_id: str) -> dict[str, Any] | None:
    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(
                text("SELECT * FROM work_runtime_jobs WHERE id = :id AND tenant_id = :t"),
                {"id": job_id, "t": db._tenant()},
            )
        )
    return _public(row) if row else None


def list_jobs(
    *,
    status: str | None = None,
    customer_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM work_runtime_jobs WHERE tenant_id = :t"
    params: dict[str, Any] = {"t": db._tenant(), "lim": max(1, min(limit, 200))}
    if status:
        sql += " AND status = :st"
        params["st"] = status
    if customer_id:
        sql += " AND customer_id = :cid"
        params["cid"] = customer_id
    sql += " ORDER BY created_at DESC LIMIT :lim"
    with db.engine.connect() as conn:
        rows = db._rows(conn.execute(text(sql), params))
    return [_public(r) for r in rows]


def claim_next(
    workflow_types: tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    kind_filter = (
        " AND workflow_type = ANY(CAST(:workflow_types AS text[]))"
        if workflow_types
        else ""
    )
    with db.engine.begin() as conn:
        # `working` is a claim with a lease (`locked_at`), so a job whose
        # worker died is re-claimed once the lease lapses and one whose
        # handler keeps raising is not re-run without bound. Both used to be
        # true: `working` was a label, and this SELECT picked it up on every
        # tick forever. Same shape as bot_turn_jobs.
        row = db._one(
            conn.execute(
                text(
                    f"""
                    SELECT id, attempts FROM work_runtime_jobs
                     WHERE tenant_id = :t
                       AND (status = 'submitted'
                            OR (status = 'working'
                                AND COALESCE(locked_at, updated_at) < now() - :lease * interval '1 second'))
                       {kind_filter}
                     ORDER BY created_at
                     FOR UPDATE SKIP LOCKED
                     LIMIT 1
                    """
                ),
                {
                    "t": db._tenant(),
                    "lease": _lease_seconds(),
                    **({"workflow_types": list(workflow_types)} if workflow_types else {}),
                },
            )
        )
        if not row:
            return None
        if int(row["attempts"] or 0) >= _max_attempts():
            conn.execute(
                text(
                    """
                    UPDATE work_runtime_jobs
                       SET status = 'failed', locked_at = NULL, updated_at = now(),
                           error = left(COALESCE(error, '') || ' [dead: attempts exhausted]', 500)
                     WHERE id = :id
                    """
                ),
                {"id": row["id"]},
            )
            return None
        conn.execute(
            text(
                """
                UPDATE work_runtime_jobs
                   SET status = 'working', locked_at = now(), attempts = attempts + 1,
                       updated_at = now()
                 WHERE id = :id
                """
            ),
            {"id": row["id"]},
        )
    return query(row["id"])


def _lease_seconds() -> int:
    from env_utils import env_int

    return env_int("WORK_RUNTIME_LEASE_SECONDS", 300)


def _max_attempts() -> int:
    from env_utils import env_int

    return env_int("WORK_RUNTIME_MAX_ATTEMPTS", 3)


# `finish` and `park_input_required` used to UPDATE unconditionally, so a late
# worker could move a cancelled or completed job back to `failed`, and a stale
# one could re-park a job an operator had already approved. `finish` now
# requires `working`; `park` accepts a live job (submitted or working).


def finish(job_id: str, *, ok: bool, result: dict[str, Any] | None = None, error: str | None = None) -> bool:
    """Close a working job. False when it was no longer ours to close."""
    with db.engine.begin() as conn:
        res = conn.execute(
            text(
                """
                UPDATE work_runtime_jobs
                   SET status = :st, result = CAST(:result AS jsonb), error = :err,
                       locked_at = NULL, updated_at = now()
                 WHERE id = :id AND tenant_id = :t AND status = 'working'
                """
            ),
            {
                "id": job_id,
                "t": db._tenant(),
                "st": "completed" if ok else "failed",
                "result": db._jsonb(result or {}),
                "err": error,
            },
        )
    return res.rowcount == 1


def park_input_required(job_id: str, reason: str) -> None:
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE work_runtime_jobs
                   SET status = 'input_required', input_required_reason = :r,
                       locked_at = NULL, updated_at = now()
                 WHERE id = :id AND tenant_id = :t AND status IN ('submitted', 'working')
                """
            ),
            {"id": job_id, "t": db._tenant(), "r": reason},
        )


def upsert_job(
    *,
    workflow_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
    status: str = "submitted",
    customer_id: str | None = None,
    conn: Any | None = None,
) -> dict[str, Any]:
    """Insert a job, or replace its payload when the idempotency key exists.

    ``start_workflow`` is enqueue-once. This is the other conflict policy: the
    treatment book-sweep stores its resume cursor as a job row and must move
    that cursor on every batch.
    """
    if not idempotency_key.strip():
        raise ValueError("idempotency_key_required")
    if not workflow_type.strip():
        raise ValueError("workflow_type_required")
    jid = f"wrj-{uuid.uuid4().hex[:12]}"

    def _write(active: Any) -> dict[str, Any]:
        active.execute(
            text(
                """
                INSERT INTO work_runtime_jobs (
                  id, tenant_id, workflow_type, status, customer_id,
                  payload, idempotency_key, request_id
                ) VALUES (
                  :id, :t, :wt, :st, :cid, CAST(:payload AS jsonb), :k, :rid
                )
                ON CONFLICT (tenant_id, idempotency_key) DO UPDATE
                   SET payload = CAST(:payload AS jsonb),
                       updated_at = now()
                """
            ),
            {
                "id": jid,
                "t": db._tenant(),
                "wt": workflow_type,
                "st": status,
                "cid": customer_id,
                "payload": db._jsonb(payload),
                "k": idempotency_key,
                "rid": request_context.get_request_id(),
            },
        )
        row = db._one(
            active.execute(
                text(
                    """
                    SELECT * FROM work_runtime_jobs
                     WHERE tenant_id = :t AND idempotency_key = :k
                    """
                ),
                {"t": db._tenant(), "k": idempotency_key},
            )
        )
        assert row is not None
        return _public(row)

    if conn is not None:
        return _write(conn)
    with db.engine.begin() as active:
        return _write(active)

