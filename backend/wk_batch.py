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
#: W13. The daily capacity solve, its nightly gold-standard check against the
#: monolithic LP, and the objective-mismatch regret measurement §10.4 requires
#: filed before the write switch is flipped.
#:
#: Here rather than in a scheduler of their own because §10.5 asks for exactly
#: what this dispatcher already is: a nightly, idempotent, role-scoped job under
#: a per-job advisory lock, with a row that makes "did it run today" a query
#: rather than an inference. A third job ledger would be the fourth
#: contact-window restatement in a different costume.
CAPACITY_SOLVE = "w13.capacity_solve"
ALLOCATOR_GOLD = "w13.allocator_gold"
ALLOCATOR_REGRET = "w13.allocator_regret"
JOBS = frozenset(
    {
        SNAPSHOT,
        PIT_SKEW,
        COST_ROLLUP,
        RETENTION,
        CAPACITY_SOLVE,
        ALLOCATOR_GOLD,
        ALLOCATOR_REGRET,
    }
)

#: Jobs that read the primary rather than the reporting standby.
#:
#: The three W13 jobs read ``treatment_decisions`` — the decision log as it
#: stands now, not a replica of it — and the solve writes ``capacity_duals``.
#: Demanding a REPORTING_DATABASE_URL for a job that neither reads a replica nor
#: needs one is how a deployment ends up with no capacity price at all.
PRIMARY_SOURCE_JOBS = frozenset({CAPACITY_SOLVE, ALLOCATOR_GOLD, ALLOCATOR_REGRET})


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


def run_now(
    engine: Engine,
    *,
    job_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    """Enqueue one job and run it here, under the same lock and ledger.

    For jobs a human triggers from a script. The alternative -- enqueue and
    then spin `process_one` until it happens to pick this job -- runs whatever
    else is queued first, which is not what somebody at a terminal asked for.

    The row it leaves is the same row the scheduled path leaves, which is the
    point: `allocate.write_switch_objections` counts gold-standard nights out of
    `work_runtime_jobs`, and a run that did not write one did not happen.
    """
    if job_type not in PRIMARY_SOURCE_JOBS:
        raise ValueError(f"run_now_refuses:{job_type}")
    job = enqueue(job_type=job_type, payload=payload, idempotency_key=idempotency_key)
    job_id = str(job["id"])
    lock_name = f"wk-batch:{job_type}:{idempotency_key}"
    with engine.connect() as sink:
        locked = sink.execute(
            text("SELECT pg_try_advisory_lock(hashtextextended(:name, 0))"),
            {"name": lock_name},
        ).scalar()
        sink.commit()
        if locked is not True:
            _finish(engine, job_id, ok=False, error="advisory_lock_busy")
            return {"id": job_id, "status": "failed", "error": "advisory_lock_busy"}
        try:
            with sink.begin():
                result = _run(job_type, payload, sink, sink, source_kind="primary")
            _finish(engine, job_id, ok=True, result=result)
            return {"id": job_id, "status": "completed", "result": result}
        except Exception as exc:
            logger.exception("wk-batch run_now failed job=%s", job_type)
            _finish(engine, job_id, ok=False, error=type(exc).__name__)
            return {"id": job_id, "status": "failed", "error": type(exc).__name__}
        finally:
            sink.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:name, 0))"),
                {"name": lock_name},
            )
            sink.commit()


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
    if str(job["workflow_type"]) in PRIMARY_SOURCE_JOBS:
        source_engine, source_kind, owned_source = engine, "primary", False
    elif source_engine is None:
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
    if job_type in PRIMARY_SOURCE_JOBS:
        from agent_core.treatment import allocator_jobs

        return allocator_jobs.run(job_type, sink, tenant_id=tenant_id, payload=payload)
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
    import actor_context

    actor_context.bind_service_actor("system")
    while True:
        if not process_one(db.engine):
            time.sleep(2.0)


if __name__ == "__main__":
    raise SystemExit(main())
