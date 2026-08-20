"""Postgres + worker drain. Survives API process restart via job rows."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text

import db

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
                  id, tenant_id, workflow_type, status, customer_id, payload, idempotency_key
                ) VALUES (
                  :id, :t, :wt, 'submitted', :cid, CAST(:payload AS jsonb), :k
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


def claim_next() -> dict[str, Any] | None:
    with db.engine.begin() as conn:
        row = db._one(
            conn.execute(
                text(
                    """
                    SELECT id FROM work_runtime_jobs
                     WHERE tenant_id = :t AND status IN ('submitted','working')
                     ORDER BY created_at
                     FOR UPDATE SKIP LOCKED
                     LIMIT 1
                    """
                ),
                {"t": db._tenant()},
            )
        )
        if not row:
            return None
        conn.execute(
            text("UPDATE work_runtime_jobs SET status = 'working' WHERE id = :id"),
            {"id": row["id"]},
        )
    return query(row["id"])


def finish(job_id: str, *, ok: bool, result: dict[str, Any] | None = None, error: str | None = None) -> None:
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE work_runtime_jobs
                   SET status = :st, result = CAST(:result AS jsonb), error = :err
                 WHERE id = :id AND tenant_id = :t
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


def park_input_required(job_id: str, reason: str) -> None:
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE work_runtime_jobs
                   SET status = 'input_required', input_required_reason = :r
                 WHERE id = :id AND tenant_id = :t
                """
            ),
            {"id": job_id, "t": db._tenant(), "r": reason},
        )
