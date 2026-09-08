"""Daily policy horizon scan and cutover cancel. Never invokes a carrier."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from agent_core.treatment import schema_ready

logger = logging.getLogger(__name__)

HORIZON_DAYS = 14
SCAN_LOCK = 87421001
CUTOVER_LOCK = 87421002


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _claim_run(conn: Any, job_name: str, day_key: str) -> str | None:
    if not schema_ready.has_table(conn, "policy_job_runs"):
        return None
    key = f"{job_name}:{day_key}"
    existing = conn.execute(
        text("SELECT id, state FROM policy_job_runs WHERE idempotency_key = :k"),
        {"k": key},
    ).mappings().first()
    if existing:
        return None if existing["state"] in {"started", "completed", "skipped"} else existing["id"]
    run_id = _id("PJR")
    conn.execute(
        text(
            """
            INSERT INTO policy_job_runs (id, job_name, idempotency_key, state)
            VALUES (:id, :name, :k, 'started')
            """
        ),
        {"id": run_id, "name": job_name, "k": key},
    )
    return run_id


def _finish(conn: Any, run_id: str | None, state: str, result: dict[str, Any]) -> None:
    if not run_id:
        return
    conn.execute(
        text(
            """
            UPDATE policy_job_runs
            SET state = :state, result = CAST(:result AS jsonb), finished_at = now()
            WHERE id = :id
            """
        ),
        {"id": run_id, "state": state, "result": __import__("json").dumps(result)},
    )


def horizon_scan(conn: Any, *, now: datetime | None = None, report_only: bool = True) -> dict[str, Any]:
    """Replay unenacted plans against rules that become effective within 14 days."""
    instant = now or datetime.now(timezone.utc)
    day_key = instant.strftime("%Y-%m-%d")
    if not schema_ready.w4_ready(conn):
        return {"skipped": True, "reason": "schema_not_ready"}
    locked = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": SCAN_LOCK}).scalar()
    if not locked:
        return {"skipped": True, "reason": "lock"}
    run_id = None
    try:
        run_id = _claim_run(conn, "policy_horizon_scan", day_key)
        if run_id is None:
            return {"skipped": True, "reason": "idempotent"}
        horizon_end = instant + timedelta(days=HORIZON_DAYS)
        rules = conn.execute(
            text(
                """
                SELECT r.rule_id, r.kind, lower(r.effective) AS effective_from, r.citation
                FROM policy_rules r
                JOIN policy_rule_sets s ON s.id = r.rule_set_id
                WHERE s.publication_state = 'published'
                  AND lower(r.effective) > :now
                  AND lower(r.effective) <= :end
                """
            ),
            {"now": instant, "end": horizon_end},
        ).mappings().all()
        findings = 0
        for rule in rules:
            plans = conn.execute(
                text(
                    """
                    SELECT id, tenant_id, customer_id FROM treatment_decisions
                    WHERE enacted IS FALSE
                      AND chosen_action IS NOT NULL AND chosen_action <> 'wait'
                      AND scheduled_at >= :from
                      AND scheduled_at < :until
                    LIMIT 200
                    """
                ),
                {"from": rule["effective_from"], "until": horizon_end},
            ).mappings().all()
            for plan in plans:
                findings += 1
                if report_only:
                    conn.execute(
                        text(
                            """
                            INSERT INTO policy_horizon_findings (
                              id, tenant_id, customer_id, decision_id, rule_id,
                              kind, detail
                            ) VALUES (
                              :id, :tid, :cid, :did, :rid, 'reschedule',
                              CAST(:detail AS jsonb)
                            )
                            """
                        ),
                        {
                            "id": _id("PHF"),
                            "tid": plan["tenant_id"],
                            "cid": plan["customer_id"],
                            "did": plan["id"],
                            "rid": rule["rule_id"],
                            "detail": __import__("json").dumps(
                                {"kind": rule["kind"], "citation": rule["citation"]}
                            ),
                        },
                    )
        result = {"findings": findings, "rules": len(rules), "reportOnly": report_only}
        _finish(conn, run_id, "completed", result)
        return result
    except Exception:
        logger.exception("policy_horizon_scan failed")
        _finish(conn, run_id, "failed", {"error": "exception"})
        raise
    finally:
        conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": SCAN_LOCK})


def cutover_cancel(conn: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Cancel unenacted plans whose rules change tomorrow. Never sends."""
    instant = now or datetime.now(timezone.utc)
    day_key = instant.strftime("%Y-%m-%d")
    if not schema_ready.w4_ready(conn):
        return {"skipped": True, "reason": "schema_not_ready"}
    locked = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": CUTOVER_LOCK}).scalar()
    if not locked:
        return {"skipped": True, "reason": "lock"}
    run_id = None
    try:
        run_id = _claim_run(conn, "policy_cutover_cancel", day_key)
        if run_id is None:
            return {"skipped": True, "reason": "idempotent"}
        tomorrow = (instant + timedelta(days=1)).date()
        start = datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        cancelled = conn.execute(
            text(
                """
                UPDATE treatment_decisions
                SET outcome = 'cancelled',
                    cancel_reason = 'policy_effective_change',
                    outcome_at = now()
                WHERE enacted IS FALSE
                  AND chosen_action IS NOT NULL AND chosen_action <> 'wait'
                  AND scheduled_at >= :start AND scheduled_at < :end
                  AND outcome IS NULL
                RETURNING id
                """
            ),
            {"start": start, "end": end},
        ).scalars().all()
        if schema_ready.has_table(conn, "contact_reservations") and cancelled:
            conn.execute(
                text(
                    """
                    UPDATE contact_reservations
                    SET state = 'released', updated_at = now()
                    WHERE decision_id = ANY(:ids) AND state = 'held'
                    """
                ),
                {"ids": list(cancelled)},
            )
        result = {"cancelled": len(cancelled)}
        _finish(conn, run_id, "completed", result)
        return result
    except Exception:
        logger.exception("policy_cutover_cancel failed")
        _finish(conn, run_id, "failed", {"error": "exception"})
        raise
    finally:
        conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": CUTOVER_LOCK})
