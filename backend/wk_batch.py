"""Role-scoped W6 batch dispatcher; no carrier or borrower-facing operations."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime
from typing import Any

os.environ.setdefault("DB_PROCESS_ROLE", "worker")

from sqlalchemy import engine_from_config, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

import db
import tenant_context
from agent_core.treatment import substrate
from env_utils import NON_PROD_ENVS, env_bool, env_name

logger = logging.getLogger("wk_batch")

SNAPSHOT = "w6.snapshot_daily"
PIT_SKEW = "w6.pit_skew"
COST_ROLLUP = "w6.cost_rollup"
#: W8b. Runs on the primary, not the reporting replica -- it writes. It is
#: here rather than in its own worker because it is the same shape as the
#: other three: nightly, idempotent, and nothing borrower-facing.
RETENTION = "w8.retention_sweep"
JOBS = frozenset({SNAPSHOT, PIT_SKEW, COST_ROLLUP, RETENTION})


def reporting_engine() -> tuple[Engine, str]:
    """Return the dedicated standby engine or an explicitly allowed scratch source."""
    url = (os.getenv("REPORTING_DATABASE_URL") or "").strip()
    if not url:
        if env_name() in NON_PROD_ENVS and env_bool("W6_ALLOW_PRIMARY_REPORTING"):
            return db.engine, "scratch"
        raise RuntimeError("REPORTING_DATABASE_URL_required")
    if url == db.DATABASE_URL:
        raise RuntimeError("reporting_source_must_not_be_primary")
    options = (
        "-c statement_timeout=1800000 "
        f"-c {tenant_context.GUC}={tenant_context.validate(db.current_tenant())}"
    )
    engine = engine_from_config(
        {"sqlalchemy.url": url},
        prefix="sqlalchemy.",
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args={"options": options},
    )
    return engine, "reporting"


def enqueue(
    *,
    job_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
    conn: Any | None = None,
) -> dict[str, Any]:
    if job_type not in JOBS:
        raise ValueError(f"unknown_w6_job:{job_type}")
    from work_runtime import start_workflow

    return start_workflow(
        workflow_type=job_type,
        payload=payload,
        idempotency_key=idempotency_key,
        conn=conn,
    )


def process_one(engine: Engine, *, source_engine: Engine | None = None) -> bool:
    """Claim one W6 job, run it under one session advisory lock, and finish it."""
    with engine.begin() as conn:
        job = conn.execute(
            text(
                """
                SELECT *
                  FROM work_runtime_jobs
                 WHERE workflow_type = ANY(:types)
                   AND status = 'submitted'
                 ORDER BY created_at
                 LIMIT 1
                 FOR UPDATE SKIP LOCKED
                """
            ),
            {"types": sorted(JOBS)},
        ).mappings().first()
        if job is None:
            return False
        conn.execute(
            text(
                """
                UPDATE work_runtime_jobs
                   SET status = 'working', updated_at = now(), error = NULL
                 WHERE id = :id
                """
            ),
            {"id": job["id"]},
        )

    owned_source = source_engine is None
    source_kind = "reporting"
    if source_engine is None:
        source_engine, source_kind = reporting_engine()
    lock_name = f"wk-batch:{job['workflow_type']}:{job['idempotency_key']}"
    try:
        with engine.connect() as sink:
            locked = sink.execute(
                text("SELECT pg_try_advisory_lock(hashtextextended(:name, 0))"),
                {"name": lock_name},
            ).scalar()
            sink.commit()
            if locked is not True:
                _finish(engine, str(job["id"]), ok=False, error="advisory_lock_busy")
                return True
            try:
                with source_engine.connect() as source, sink.begin():
                    result = _run(
                        str(job["workflow_type"]),
                        dict(job["payload"] or {}),
                        source,
                        sink,
                        source_kind=source_kind,
                    )
                _finish(engine, str(job["id"]), ok=True, result=result)
            except Exception as exc:
                logger.exception("wk-batch job failed id=%s", job["id"])
                _finish(engine, str(job["id"]), ok=False, error=type(exc).__name__)
            finally:
                sink.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:name, 0))"),
                    {"name": lock_name},
                )
                sink.commit()
    finally:
        if owned_source and source_engine is not db.engine:
            source_engine.dispose()
    return True


def _run(
    job_type: str,
    payload: dict[str, Any],
    source: Any,
    sink: Any,
    *,
    source_kind: str,
) -> dict[str, Any]:
    tenant_id = str(payload.get("tenant_id") or db.current_tenant())
    if job_type == SNAPSHOT:
        return substrate.build_daily_snapshot(
            source,
            sink,
            tenant_id=tenant_id,
            portfolio_id=str(payload.get("portfolio_id") or ""),
            as_of_date=date.fromisoformat(str(payload["as_of_date"])),
            source_kind=source_kind,
        )
    if job_type == PIT_SKEW:
        return substrate.run_pit_skew(
            source,
            sink,
            tenant_id=tenant_id,
            sampled_from=datetime.fromisoformat(str(payload["sampled_from"])),
            sampled_to=datetime.fromisoformat(str(payload["sampled_to"])),
            source_kind=source_kind,
            sample_percent=int(payload.get("sample_percent") or 1),
        )
    if job_type == RETENTION:
        from agent_core import retention

        if str(payload.get("backfill") or "") == "1":
            for kind in retention.DEFAULTS:
                retention.backfill(sink, tenant_id=tenant_id, record_kind=kind)
        return {
            "kinds": retention.sweep(
                sink,
                tenant_id=tenant_id,
                record_kind=(payload.get("record_kind") or None),
                limit=int(payload.get("limit") or 5000),
            )
        }
    if job_type == COST_ROLLUP:
        count = substrate.rollup_decision_costs(
            source, sink, usage_date=date.fromisoformat(str(payload["usage_date"]))
        )
        return {"rows": count}
    raise ValueError(f"unknown_w6_job:{job_type}")


def _finish(
    engine: Engine,
    job_id: str,
    *,
    ok: bool,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE work_runtime_jobs
                   SET status = :status, result = CAST(:result AS jsonb),
                       error = :error, updated_at = now()
                 WHERE id = :id
                """
            ),
            {
                "id": job_id,
                "status": "completed" if ok else "failed",
                "result": json.dumps(result or {}, default=str),
                "error": error,
            },
        )


def main() -> int:
    while True:
        if not process_one(db.engine):
            time.sleep(2.0)


if __name__ == "__main__":
    raise SystemExit(main())
