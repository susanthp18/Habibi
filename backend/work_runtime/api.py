"""Public Temporal-shaped API. The one module that imports an adapter.

``start_workflow`` is insert-or-return (idempotent enqueue). ``upsert_job`` is
insert-or-replace-payload — the sweep cursor is a job row whose payload *is*
the state, not a task to run once.

There is one adapter, Postgres job rows, and this file names it directly. A
``WorkRuntime`` Protocol and a second adapter that raised on every call used to
sit between the two; nothing selected it, ``TEMPORAL_ENABLED`` was never turned
on, and the package docstring already explains why it should not be — the
approvals this runtime parks are same-shift, not multi-day. Callers still reach
these functions rather than the adapter, so re-introducing a selector later is
an edit to this file alone.
"""

from __future__ import annotations

from typing import Any

from work_runtime import adapter_pg as adapter


def start_workflow(
    *,
    workflow_type: str,
    payload: dict[str, Any] | None = None,
    customer_id: str | None = None,
    idempotency_key: str,
    conn: Any | None = None,
) -> dict[str, Any]:
    return adapter.start_workflow(
        workflow_type=workflow_type,
        payload=payload or {},
        customer_id=customer_id,
        idempotency_key=idempotency_key,
        conn=conn,
    )


def signal(job_id: str, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return adapter.signal(job_id, name, payload or {})


def query(job_id: str) -> dict[str, Any] | None:
    return adapter.query(job_id)


def list_jobs(
    *,
    status: str | None = None,
    customer_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return adapter.list_jobs(status=status, customer_id=customer_id, limit=limit)


def claim_next(
    workflow_types: tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    return adapter.claim_next(workflow_types)


def finish(
    job_id: str,
    *,
    ok: bool,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    adapter.finish(job_id, ok=ok, result=result, error=error)


def park_input_required(job_id: str, reason: str) -> None:
    adapter.park_input_required(job_id, reason)


def upsert_job(
    *,
    workflow_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
    status: str = "submitted",
    customer_id: str | None = None,
    conn: Any | None = None,
) -> dict[str, Any]:
    return adapter.upsert_job(
        workflow_type=workflow_type,
        payload=payload,
        idempotency_key=idempotency_key,
        status=status,
        customer_id=customer_id,
        conn=conn,
    )
