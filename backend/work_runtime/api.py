"""Public Temporal-shaped API. Adapter is chosen here, not at call sites."""

from __future__ import annotations

from typing import Any

from agent_core.platform_flags import temporal_enabled


def _adapter():
    if temporal_enabled():
        from work_runtime import adapter_temporal as adapter

        return adapter
    from work_runtime import adapter_pg as adapter

    return adapter


def start_workflow(
    *,
    workflow_type: str,
    payload: dict[str, Any] | None = None,
    customer_id: str | None = None,
    idempotency_key: str,
    conn: Any | None = None,
) -> dict[str, Any]:
    return _adapter().start_workflow(
        workflow_type=workflow_type,
        payload=payload or {},
        customer_id=customer_id,
        idempotency_key=idempotency_key,
        conn=conn,
    )


def signal(job_id: str, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return _adapter().signal(job_id, name, payload or {})


def query(job_id: str) -> dict[str, Any] | None:
    return _adapter().query(job_id)
