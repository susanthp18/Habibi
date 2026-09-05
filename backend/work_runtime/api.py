"""Public Temporal-shaped API. Adapter is chosen here, not at call sites."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from agent_core.platform_flags import temporal_enabled


@runtime_checkable
class WorkRuntime(Protocol):
    """Every adapter implements this. Callers never import an adapter module.

    ``start_workflow`` is insert-or-return (idempotent enqueue). ``upsert_job``
    is insert-or-replace-payload — the sweep cursor is a job row whose payload
    *is* the state, not a task to run once.
    """

    def start_workflow(
        self,
        *,
        workflow_type: str,
        payload: dict[str, Any],
        customer_id: str | None,
        idempotency_key: str,
        conn: Any | None = None,
    ) -> dict[str, Any]: ...

    def signal(self, job_id: str, name: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def query(self, job_id: str) -> dict[str, Any] | None: ...

    def list_jobs(
        self,
        *,
        status: str | None = None,
        customer_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...

    def claim_next(self) -> dict[str, Any] | None: ...

    def finish(
        self,
        job_id: str,
        *,
        ok: bool,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None: ...

    def park_input_required(self, job_id: str, reason: str) -> None: ...

    def upsert_job(
        self,
        *,
        workflow_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        status: str = "submitted",
        customer_id: str | None = None,
        conn: Any | None = None,
    ) -> dict[str, Any]: ...


def _adapter() -> WorkRuntime:
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


def list_jobs(
    *,
    status: str | None = None,
    customer_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return _adapter().list_jobs(status=status, customer_id=customer_id, limit=limit)


def claim_next() -> dict[str, Any] | None:
    return _adapter().claim_next()


def finish(
    job_id: str,
    *,
    ok: bool,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    _adapter().finish(job_id, ok=ok, result=result, error=error)


def park_input_required(job_id: str, reason: str) -> None:
    _adapter().park_input_required(job_id, reason)


def upsert_job(
    *,
    workflow_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
    status: str = "submitted",
    customer_id: str | None = None,
    conn: Any | None = None,
) -> dict[str, Any]:
    return _adapter().upsert_job(
        workflow_type=workflow_type,
        payload=payload,
        idempotency_key=idempotency_key,
        status=status,
        customer_id=customer_id,
        conn=conn,
    )
