"""MCP Tasks — ticket now, clerk/worker later. Never blocks the mouth."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text

import db
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


def claim_next() -> dict[str, Any] | None:
    with db.engine.begin() as conn:
        row = db._one(
            conn.execute(
                text(
                    """
                    SELECT id FROM mcp_tasks
                     WHERE tenant_id = :t AND status = 'queued'
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
            text("UPDATE mcp_tasks SET status = 'running' WHERE id = :id"),
            {"id": row["id"]},
        )
    return get_task(row["id"])


def finish(task_id: str, *, ok: bool, result: dict[str, Any] | None = None, error: str | None = None) -> None:
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE mcp_tasks
                   SET status = :st, result = CAST(:result AS jsonb), error = :err
                 WHERE id = :id AND tenant_id = :t
                """
            ),
            {
                "id": task_id,
                "t": db._tenant(),
                "st": "succeeded" if ok else "failed",
                "result": db._jsonb(result or {}),
                "err": error,
            },
        )


def process_one() -> bool:
    """Worker: turn a queued statement request into a document_request row."""
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
