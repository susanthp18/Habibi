"""MCP Tasks — ticket now, clerk/worker later. Never blocks the mouth.

A queue in the bot_turn_jobs sense: a claim takes a lease, a worker that dies
mid-task is reclaimed after ``stale_running_seconds``, a failure retries with
backoff until ``max_attempts`` and then dead-letters. Before this the table
held a status and nothing else, so a crash left a task ``running`` forever
and a failure was final on the first try.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import text

import db
from agent_core.clock import utc_now
from bot_jobs import MAX_JOB_ERROR_CHARS, _worker_id, max_attempts, stale_running_seconds
from agent_core.platform_flags import mcp_tasks_enabled

ALLOWED_KINDS = frozenset({"statement_generate", "bureau_pull", "document_pack"})


def enqueue(*, kind: str, customer_id: str | None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not mcp_tasks_enabled():
        raise PermissionError("mcp_tasks_disabled")
    if kind not in ALLOWED_KINDS:
        raise ValueError("unknown_task_kind")
    tid = f"mcpt-{uuid.uuid4().hex[:12]}"
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO mcp_tasks (id, tenant_id, kind, status, customer_id, payload)
                VALUES (:id, :t, :kind, 'queued', :cid, CAST(:payload AS jsonb))
                """
            ),
            {
                "id": tid,
                "t": db._tenant(),
                "kind": kind,
                "cid": customer_id,
                "payload": db._jsonb(payload or {}),
            },
        )
    return {
        "id": tid,
        "kind": kind,
        "status": "queued",
        "say": "We will send it. You will get a confirmation when it is ready.",
    }


def get_task(task_id: str) -> dict[str, Any] | None:
    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(
                text("SELECT * FROM mcp_tasks WHERE id = :id AND tenant_id = :t"),
                {"id": task_id, "t": db._tenant()},
            )
        )
    if not row:
        return None
    return {
        "id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "customerId": row.get("customer_id"),
        "payload": row.get("payload") or {},
        "result": row.get("result") or {},
        "error": row.get("error"),
        "attempt": int(row.get("attempt") or 0),
        "createdAt": str(row.get("created_at")) if row.get("created_at") else None,
        "updatedAt": str(row.get("updated_at")) if row.get("updated_at") else None,
    }


def list_tasks(*, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    sql = "SELECT * FROM mcp_tasks WHERE tenant_id = :t"
    params: dict[str, Any] = {"t": db._tenant(), "lim": max(1, min(limit, 200))}
    if status:
        sql += " AND status = :st"
        params["st"] = status
    sql += " ORDER BY created_at DESC LIMIT :lim"
    with db.engine.connect() as conn:
        rows = db._rows(conn.execute(text(sql), params))
    return [get_task(r["id"]) for r in rows if get_task(r["id"])]


def reclaim_stale() -> int:
    """A task whose worker died mid-run goes back to the queue with backoff,
    or to ``dead`` once its attempts are spent. Returns how many moved."""
    cutoff = utc_now() - timedelta(seconds=stale_running_seconds())
    with db.engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE mcp_tasks
                   SET status = CASE WHEN attempt >= :cap THEN 'dead' ELSE 'queued' END,
                       locked_at = NULL,
                       locked_by = NULL,
                       run_after = now() + make_interval(secs => LEAST(300, power(2, LEAST(attempt, 12)))),
                       error = left(COALESCE(error, '') || ' [stuck running]', :max_error),
                       updated_at = now()
                 WHERE tenant_id = :t AND status = 'running' AND COALESCE(locked_at, updated_at) < :cutoff
                """
            ),
            {"t": db._tenant(), "cap": max_attempts(), "max_error": MAX_JOB_ERROR_CHARS, "cutoff": cutoff},
        )
    return int(result.rowcount or 0)


def claim_next() -> dict[str, Any] | None:
    """Claim, then COMMIT: the I/O the task does runs outside the lock."""
    with db.engine.begin() as conn:
        row = db._one(
            conn.execute(
                text(
                    """
                    SELECT id FROM mcp_tasks
                     WHERE tenant_id = :t AND status = 'queued' AND run_after <= now()
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
            text(
                """
                UPDATE mcp_tasks
                   SET status = 'running', attempt = attempt + 1,
                       locked_at = now(), locked_by = :w, updated_at = now()
                 WHERE id = :id
                """
            ),
            {"id": row["id"], "w": _worker_id()},
        )
    return get_task(row["id"])


def finish(task_id: str, *, ok: bool, result: dict[str, Any] | None = None, error: str | None = None) -> str:
    """Record the outcome. A failure retries with backoff until the attempt cap,
    then dead-letters; the returned status says which."""
    with db.engine.begin() as conn:
        if ok:
            conn.execute(
                text(
                    """
                    UPDATE mcp_tasks
                       SET status = 'succeeded', result = CAST(:result AS jsonb), error = NULL,
                           locked_at = NULL, locked_by = NULL, updated_at = now()
                     WHERE id = :id AND tenant_id = :t
                    """
                ),
                {"id": task_id, "t": db._tenant(), "result": db._jsonb(result or {})},
            )
            return "succeeded"
        row = db._one(
            conn.execute(
                text(
                    """
                    UPDATE mcp_tasks
                       SET status = CASE WHEN attempt >= :cap THEN 'dead' ELSE 'queued' END,
                           error = left(:err, :max_error),
                           run_after = now() + make_interval(secs => LEAST(300, power(2, LEAST(attempt, 12)))),
                           locked_at = NULL, locked_by = NULL, updated_at = now()
                     WHERE id = :id AND tenant_id = :t
                     RETURNING status
                    """
                ),
                {"id": task_id, "t": db._tenant(), "cap": max_attempts(), "err": error or "", "max_error": MAX_JOB_ERROR_CHARS},
            )
        )
    return str(row["status"]) if row else "failed"


def process_one() -> bool:
    """Worker: turn a queued statement request into a document_request row."""
    reclaim_stale()
    task = claim_next()
    if not task:
        return False
    kind = task["kind"]
    cid = task.get("customerId")
    try:
        if kind == "statement_generate" and cid:
            from agent_core.tools import domain

            domain.request_documents(
                customer_id=cid,
                document_type=str(
                    (task.get("payload") or {}).get("doc_type") or "account_statement"
                ),
                requested_via="mcp",
            )
        finish(task["id"], ok=True, result={"enacted": kind})
    except Exception as exc:
        finish(task["id"], ok=False, error=type(exc).__name__)
    return True
