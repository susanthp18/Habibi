"""The decision engine's clock: what runs when, so nothing depends on a person.

Before this, every batch job the engine relies on existed and none was
scheduled: the feature snapshot (so every decision on a migrated database was
``stale_snapshot`` and could contact nobody), the analysis panel, the capacity
solve, retention, training and evaluation. Each one refused politely forever.

Two kinds of job:

* **Queued** on ``work_runtime_jobs`` for ``wk_batch`` (its advisory locks,
  its ledger): snapshot, cost rollup, retention, capacity solve / gold /
  regret.
* **Inline** here, on the primary, because they are small and read the live
  log: the analysis panel, the learned response rates, and the weekly
  train → evaluate chain (its result is filed on the same ledger so "did it
  run, and what did it say" is a query).

Every enqueue is keyed by tenant and period, so two workers or a restart
cannot run a night twice.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: Nightly jobs, after the Indian business day (02:00 IST).
NIGHTLY_UTC = (20, 30)
#: The weekly slow loop: Sunday night.
WEEKLY_UTC = (21, 30)
WEEKLY_WEEKDAY = 6
#: The snapshot is fresh for four hours (``substrate.SNAPSHOT_MAX_AGE``), so it
#: is rebuilt every three.
SNAPSHOT_EVERY_HOURS = 3

#: Seconds between signal sweeps over newly finished conversations.
SIGNAL_EVERY_S = 300
_last_signal_sweep = 0.0

TRAIN = "di.train"
EVALUATE = "di.evaluate"
LEARN = "di.learn"
ADVISE = "di.advise"

BACKEND = Path(__file__).resolve().parent


def _tenants(conn: Any) -> list[str]:
    return [str(t) for t in conn.execute(text("SELECT id FROM tenants ORDER BY id")).scalars()]


def _enqueue(job_type: str, payload: dict[str, Any], key: str) -> None:
    import wk_batch

    try:
        wk_batch.enqueue(job_type=job_type, payload=payload, idempotency_key=key)
    except Exception:
        logger.exception("could not enqueue %s", key)


def _file(job_type: str, key: str, result: dict[str, Any], *, ok: bool) -> None:
    """Record an inline run on the job ledger, where the health view reads it."""
    import json

    import db
    from work_runtime import start_workflow

    job = start_workflow(workflow_type=job_type, payload={}, idempotency_key=key)
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE work_runtime_jobs
                   SET status = :s, result = CAST(:r AS jsonb), updated_at = now()
                 WHERE id = :id
                """
            ),
            {"id": job["id"], "s": "completed" if ok else "failed", "r": json.dumps(result, default=str)},
        )


def snapshots(now: datetime) -> None:
    """Rebuild today's feature snapshot, every few hours, per tenant."""
    import db
    import tenant_context
    import wk_batch
    from agent_core.treatment import schema_ready

    block = now.hour // SNAPSHOT_EVERY_HOURS
    day = now.date().isoformat()
    with db.engine.connect() as conn:
        if not schema_ready.w6_ready(conn):
            return
        tenants = _tenants(conn)
    for tenant in tenants:
        with tenant_context.bind(tenant):
            _enqueue(
                wk_batch.SNAPSHOT,
                {"tenant_id": tenant, "as_of_date": day},
                f"{wk_batch.SNAPSHOT}:{tenant}:{day}:{block}",
            )


def nightly(now: datetime) -> dict[str, Any]:
    """The nightly chain for every tenant. Returns what it did, per tenant."""
    import db
    import tenant_context
    import wk_batch
    from agent_core.treatment import beliefs, panel, schema_ready

    day = now.date().isoformat()
    yesterday = (now.date() - timedelta(days=1)).isoformat()
    with db.engine.connect() as conn:
        tenants = _tenants(conn)
        w6 = schema_ready.w6_ready(conn)
        w7 = schema_ready.w7_ready(conn)
        retention = schema_ready.retention_ready(conn)
    report: dict[str, Any] = {}
    for tenant in tenants:
        with tenant_context.bind(tenant):
            if w6:
                _enqueue(wk_batch.COST_ROLLUP, {"tenant_id": tenant, "usage_date": yesterday},
                         f"{wk_batch.COST_ROLLUP}:{tenant}:{yesterday}")
            if retention:
                _enqueue(wk_batch.RETENTION, {"tenant_id": tenant}, f"{wk_batch.RETENTION}:{tenant}:{day}")
            for job in (wk_batch.CAPACITY_SOLVE, wk_batch.ALLOCATOR_GOLD, wk_batch.ALLOCATOR_REGRET):
                _enqueue(job, {"tenant_id": tenant}, f"{job}:{tenant}:{day}")
            done: dict[str, Any] = {}
            try:
                # Buying signals are marketing inferences: kept 180 days, then
                # gone. Erasure of a customer removes them at once (cascade).
                with db.engine.begin() as conn:
                    done["signalsPurged"] = conn.execute(
                        text(
                            "DELETE FROM customer_signals WHERE tenant_id = :t"
                            " AND created_at < now() - interval '180 days'"
                        ),
                        {"t": tenant},
                    ).rowcount
            except Exception:
                logger.exception("signal purge failed for %s", tenant)
            try:
                from agent_core.signals import opportunity

                # Fresh buying signals become offer decisions; the sender
                # delivers them on the promotional channel.
                done["opportunities"] = opportunity.sweep(tenant_id=tenant)
            except Exception:
                logger.exception("opportunity sweep failed for %s", tenant)
            try:
                with db.engine.begin() as conn:
                    if w7:
                        done["panel"] = panel.build(conn, now=now, since=now - timedelta(days=120), tenant_id=tenant)
                    done["learned"] = beliefs.refresh(conn, tenant_id=tenant)
                _file(LEARN, f"{LEARN}:{tenant}:{day}", done, ok=True)
            except Exception as exc:
                logger.exception("nightly learning failed for %s", tenant)
                _file(LEARN, f"{LEARN}:{tenant}:{day}", {"error": type(exc).__name__}, ok=False)
            report[tenant] = done
    return report


def _script(args: list[str], timeout: int = 3600) -> dict[str, Any]:
    """Run one of the engine's scripts; its exit code and last lines are the record."""
    proc = subprocess.run(
        [sys.executable, *args], cwd=BACKEND, capture_output=True, text=True, timeout=timeout
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-15:]
    return {"exitCode": proc.returncode, "tail": tail}


def weekly(now: datetime) -> None:
    """The slow loop: fit challengers, then evaluate them off-policy.

    Both refuse, with their reasons, until the book holds enough labelled
    outcomes; the refusal is filed so the screen can say how far off it is.
    Nothing here promotes: promotion needs a pre-registration validated by a
    second person (``prereg``), exactly as before.
    """
    import db
    import decision_ai
    import tenant_context

    week = now.strftime("%G-W%V")
    with db.engine.connect() as conn:
        tenants = _tenants(conn)
    for tenant in tenants:
        with tenant_context.bind(tenant):
            try:
                result = decision_ai.advise(tenant_id=tenant)
                _file(ADVISE, f"{ADVISE}:{tenant}:{week}", result, ok="error" not in result)
            except Exception as exc:
                logger.exception("advisor failed for %s", tenant)
                _file(ADVISE, f"{ADVISE}:{tenant}:{week}", {"error": type(exc).__name__}, ok=False)
    for job, args in (
        (TRAIN, ["scripts/train_treatment_models.py", "--out-dir", "models/challengers"]),
        (EVALUATE, ["scripts/evaluate_policy.py"]),
    ):
        try:
            result = _script(args)
            _file(job, f"{job}:{week}", result, ok=result["exitCode"] == 0)
        except Exception as exc:
            logger.exception("%s failed", job)
            _file(job, f"{job}:{week}", {"error": type(exc).__name__}, ok=False)


def tick(daily: Callable[[str, int, int], bool], now: datetime) -> None:
    """One worker tick. ``daily`` is the worker's once-a-day claim."""
    global _last_signal_sweep
    import time

    if time.monotonic() - _last_signal_sweep >= SIGNAL_EVERY_S:
        _last_signal_sweep = time.monotonic()
        try:
            from agent_core.signals import scan

            scan.sweep()
        except Exception:
            logger.exception("signal sweep failed")
    try:
        if daily(f"di_snapshot_{now.hour // SNAPSHOT_EVERY_HOURS}", now.hour // SNAPSHOT_EVERY_HOURS * SNAPSHOT_EVERY_HOURS, 0):
            snapshots(now)
        if daily("di_nightly", *NIGHTLY_UTC):
            nightly(now)
        if now.weekday() == WEEKLY_WEEKDAY and daily("di_weekly", *WEEKLY_UTC):
            weekly(now)
    except Exception:
        logger.exception("decision jobs tick failed")
