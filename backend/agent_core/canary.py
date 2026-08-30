"""Canary traffic split + auto-rollback. Mouth never waits on this module."""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from sqlalchemy import text

import db

logger = logging.getLogger(__name__)

# Imported, not restated. This module evaluated all six while
# cards/schema.py's Literal carried only the first three, so the outbound
# three could never reach a published card and the branches below that check
# them were unreachable. The vocabulary lives in one place now.
from agent_core.cards.schema import ROLLBACK_TRIGGERS  # noqa: E402

#: Opt-out requests in the sample window above which a canary is pulled. Not
#: zero: a borrower asking to be left alone is a legitimate outcome and an agent
#: that never produced one would be the more worrying artefact. Three inside
#: fifteen minutes on one bot is a pattern.
OPTOUT_SPIKE_THRESHOLD = 3
VOICE_SLO_MS = 800


def _require_table(conn: Any) -> bool:
    row = conn.execute(text("SELECT to_regclass('public.deployment_experiments') AS t")).mappings().first()
    return bool(row and row["t"])


def running_experiment(bot_id: str, environment: str = "production") -> dict[str, Any] | None:
    with db.engine.connect() as conn:
        if not _require_table(conn):
            return None
        row = db._one(
            conn.execute(
                text(
                    """
                    SELECT id, bot_id, environment, canary_deployment_id, baseline_deployment_id,
                           traffic_pct, shadow, auto_rollback, status, rollback_reason
                      FROM deployment_experiments
                     WHERE bot_id = :b AND environment = :e AND status = 'running'
                       AND tenant_id = :t
                     LIMIT 1
                    """
                ),
                {"b": bot_id, "e": environment, "t": db.current_tenant()},
            )
        )
    return dict(row) if row else None


def pick_deployment_id(
    bot_id: str,
    *,
    environment: str = "production",
    customer_id: str | None = None,
) -> str | None:
    """Hash-split when an experiment is running. No customer id → canary/active."""
    active = db.get_active_deployment(bot_id=bot_id, environment=environment)
    exp = running_experiment(bot_id, environment)
    if not exp:
        return (active or {}).get("id")
    canary_id = exp.get("canary_deployment_id")
    baseline_id = exp.get("baseline_deployment_id")
    pct = int(exp.get("traffic_pct") or 0)
    if pct >= 100 or not customer_id:
        return canary_id or (active or {}).get("id")
    digest = hashlib.sha256(f"{bot_id}:{customer_id}".encode("utf-8")).digest()
    bucket = digest[0] % 100
    if bucket < pct:
        return canary_id or (active or {}).get("id")
    return baseline_id or canary_id or (active or {}).get("id")


def record_experiment(
    conn: Any,
    *,
    bot_id: str,
    canary_deployment_id: str,
    baseline_deployment_id: str | None,
    traffic_pct: int,
    shadow: bool,
    auto_rollback: list[str],
    environment: str = "production",
) -> dict[str, Any] | None:
    if not _require_table(conn):
        return None
    pct = max(0, min(100, int(traffic_pct)))
    triggers = [t for t in auto_rollback if t in ROLLBACK_TRIGGERS]
    eid = f"exp-{uuid.uuid4().hex[:12]}"
    conn.execute(
        text(
            """
            UPDATE deployment_experiments
               SET status = 'promoted', updated_at = now()
             WHERE bot_id = :b AND environment = :e AND status = 'running'
               AND tenant_id = :t
            """
        ),
        {"b": bot_id, "e": environment, "t": db.current_tenant()},
    )
    if pct >= 100:
        return None
    conn.execute(
        text(
            """
            INSERT INTO deployment_experiments (
              id, tenant_id, bot_id, environment, canary_deployment_id,
              baseline_deployment_id, traffic_pct, shadow, auto_rollback, status
            ) VALUES (
              :id, :t, :b, :e, :canary, :base, :pct, :shadow,
              CAST(:ar AS jsonb), 'running'
            )
            """
        ),
        {
            "id": eid,
            "t": db.current_tenant(),
            "b": bot_id,
            "e": environment,
            "canary": canary_deployment_id,
            "base": baseline_deployment_id,
            "pct": pct,
            "shadow": bool(shadow),
            "ar": db._jsonb(triggers),
        },
    )
    return {"id": eid, "trafficPct": pct, "status": "running"}


def rollback_experiment(experiment_id: str, *, reason: str) -> dict[str, Any]:
    """Swap active back to baseline. Canary is retired.

    The returned row carries ``baselineRestored``, which is the difference
    between the two things this function can do. With a baseline it retires the
    canary and reactivates the previous deployment — a rollback. Without one
    (a first canary, nothing to go back to) it only marks the experiment
    ``rolled_back`` and *nothing is reactivated*: the canary keeps serving.

    Both used to return the same shape, so the console reported both as "Canary
    rolled back to baseline" and an operator watching a bad canary was told the
    traffic had been moved off it when it had not.
    """
    with db.engine.begin() as conn:
        if not _require_table(conn):
            raise KeyError("deployment_experiments_missing")
        exp = db._one(
            conn.execute(
                text("SELECT * FROM deployment_experiments WHERE id = :id AND tenant_id = :t"),
                {"id": experiment_id, "t": db.current_tenant()},
            )
        )
        if not exp:
            raise KeyError("experiment_not_found")
        if exp["status"] != "running":
            # Already rolled back or finished. Nothing was restored by *this*
            # call, whatever a previous one did.
            return {**dict(exp), "baselineRestored": False}
        baseline = exp.get("baseline_deployment_id")
        canary = exp.get("canary_deployment_id")
        if baseline:
            conn.execute(
                text("UPDATE bot_deployments SET status = 'retired', updated_at = now() WHERE id = :id"),
                {"id": canary},
            )
            conn.execute(
                text("UPDATE bot_deployments SET status = 'active', updated_at = now() WHERE id = :id"),
                {"id": baseline},
            )
        conn.execute(
            text(
                """
                UPDATE deployment_experiments
                   SET status = 'rolled_back', rollback_reason = :r, updated_at = now()
                 WHERE id = :id
                """
            ),
            {"id": experiment_id, "r": reason},
        )
        row = (
            db._one(
                conn.execute(text("SELECT * FROM deployment_experiments WHERE id = :id"), {"id": experiment_id})
            )
            or exp
        )
        return {**dict(row), "baselineRestored": bool(baseline)}


def _live_qa_burn(conn: Any, bot_id: str) -> float:
    row = conn.execute(
        text(
            """
            SELECT
              count(*) FILTER (WHERE lq.created_at > now() - interval '15 minutes')::float AS recent,
              count(*) FILTER (
                WHERE lq.created_at > now() - interval '30 minutes'
                  AND lq.created_at <= now() - interval '15 minutes'
              )::float AS prior
            FROM live_qa_decisions lq
            JOIN interactions i ON i.id = lq.interaction_id
            WHERE i.handler_bot_id = :b
              AND lq.verdict IN ('fail_critical','fail_soft')
            """
        ),
        {"b": bot_id},
    ).mappings().first()
    if not row:
        return 0.0
    prior = float(row.get("prior") or 0)
    recent = float(row.get("recent") or 0)
    if prior <= 0:
        return 1.0 if recent >= 3 else 0.0
    return recent / prior


def _abandoned(conn: Any, bot_id: str) -> int:
    """Calls where our side dropped after connecting. Target is zero, literally.

    Section 8.1 is explicit that this is not a rate to be managed down: a
    delinquent borrower whose phone rings, who answers, who hears silence and
    hangs up is the exact conduct the RBI amendment was written to stop. The
    design makes it structurally impossible by acquiring the slot before the
    dial, so any occurrence at all means something in that chain broke — which
    is why the threshold is one and not a percentage.
    """
    return int(
        conn.execute(
            text(
                """
                SELECT count(*) FROM call_attempts
                WHERE bot_id = :b
                  AND state = 'abandoned'
                  AND updated_at > now() - interval '15 minutes'
                """
            ),
            {"b": bot_id},
        ).scalar()
        or 0
    )


def _third_party_leaks(conn: Any, bot_id: str) -> int:
    """Times this bot said something about a debt to somebody who is not the borrower.

    ``third-party-leak`` is already in ``_LIVE_ALERT_FLAGS`` and can barge the
    call in progress, so the detection exists and works. What did not exist was
    anything that treated a canary producing them as a canary to pull.
    """
    return int(
        conn.execute(
            text(
                """
                SELECT count(*)
                FROM interaction_flags f
                JOIN interactions i ON i.id = f.interaction_id
                WHERE i.handler_bot_id = :b
                  AND f.flag = 'third-party-leak'
                  AND f.created_at > now() - interval '15 minutes'
                """
            ),
            {"b": bot_id},
        ).scalar()
        or 0
    )


def _optouts(conn: Any, bot_id: str) -> int:
    """Borrowers who asked to be left alone after speaking to this bot."""
    return int(
        conn.execute(
            text(
                """
                SELECT count(*)
                FROM call_outcomes o
                JOIN call_attempts a ON a.id = o.attempt_id
                WHERE a.bot_id = :b
                  AND o.business = 'opt_out_requested'
                  AND o.created_at > now() - interval '15 minutes'
                """
            ),
            {"b": bot_id},
        ).scalar()
        or 0
    )


def _slo_miss(conn: Any, bot_id: str) -> bool:
    row = conn.execute(
        text(
            """
            SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_sec * 1000.0) AS p95
              FROM interactions
             WHERE handler_bot_id = :b
               AND channel = 'voice'
               AND started_at > now() - interval '15 minutes'
               AND duration_sec IS NOT NULL
            """
        ),
        {"b": bot_id},
    ).mappings().first()
    p95 = (row or {}).get("p95")
    return p95 is not None and float(p95) > VOICE_SLO_MS


def list_experiments(*, bot_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with db.engine.connect() as conn:
        if not _require_table(conn):
            return []
        sql = """
            SELECT * FROM deployment_experiments
             WHERE tenant_id = :t
        """
        params: dict[str, Any] = {"t": db.current_tenant(), "n": max(1, min(limit, 200))}
        if bot_id:
            sql += " AND bot_id = :b"
            params["b"] = bot_id
        sql += " ORDER BY created_at DESC LIMIT :n"
        rows = db._rows(conn.execute(text(sql), params))
    out = []
    for row in rows:
        triggers = row.get("auto_rollback") or []
        if isinstance(triggers, str):
            import json

            try:
                triggers = json.loads(triggers)
            except json.JSONDecodeError:
                triggers = []
        out.append(
            {
                "id": row["id"],
                "botId": row["bot_id"],
                "environment": row.get("environment"),
                "canaryDeploymentId": row.get("canary_deployment_id"),
                "baselineDeploymentId": row.get("baseline_deployment_id"),
                "trafficPct": int(row.get("traffic_pct") or 0),
                "shadow": bool(row.get("shadow")),
                "autoRollback": list(triggers),
                "status": row.get("status"),
                "rollbackReason": row.get("rollback_reason"),
            }
        )
    return out


def sweep_rollbacks() -> bool:
    """Drain-cadence check. Returns True when an experiment rolled back."""
    try:
        with db.engine.connect() as conn:
            if not _require_table(conn):
                return False
            rows = db._rows(
                conn.execute(
                    text(
                        """
                        SELECT id, bot_id, auto_rollback
                          FROM deployment_experiments
                         WHERE status = 'running' AND tenant_id = :t
                        """
                    ),
                    {"t": db.current_tenant()},
                )
            )
        acted = False
        for exp in rows:
            triggers = exp.get("auto_rollback") or []
            if isinstance(triggers, str):
                import json

                try:
                    triggers = json.loads(triggers)
                except json.JSONDecodeError:
                    triggers = []
            reason = None
            with db.engine.connect() as conn:
                if "eval_fail" in triggers:
                    report = db.get_latest_eval_report(bot_id=exp["bot_id"], kind="redteam")
                    if report and str(report.get("status") or "") == "fail":
                        reason = "eval_fail"
                if reason is None and "slo_miss" in triggers:
                    try:
                        if _slo_miss(conn, exp["bot_id"]):
                            reason = "slo_miss"
                    except Exception:
                        logger.exception("canary slo sample failed")
                if reason is None and "live_qa_burn" in triggers:
                    try:
                        if _live_qa_burn(conn, exp["bot_id"]) > 1.5:
                            reason = "live_qa_burn"
                    except Exception:
                        logger.exception("canary live-qa sample failed")
                # The outbound three, checked last only because they are the
                # newest; each is independently sufficient and none of them is a
                # ratio against a baseline. There is no acceptable rate of
                # telling a stranger about somebody's debt.
                if reason is None and "abandon_rate" in triggers:
                    try:
                        if _abandoned(conn, exp["bot_id"]) > 0:
                            reason = "abandon_rate"
                    except Exception:
                        logger.exception("canary abandon sample failed")
                if reason is None and "third_party_leak" in triggers:
                    try:
                        if _third_party_leaks(conn, exp["bot_id"]) > 0:
                            reason = "third_party_leak"
                    except Exception:
                        logger.exception("canary leak sample failed")
                if reason is None and "optout_spike" in triggers:
                    try:
                        if _optouts(conn, exp["bot_id"]) >= OPTOUT_SPIKE_THRESHOLD:
                            reason = "optout_spike"
                    except Exception:
                        logger.exception("canary opt-out sample failed")
            if reason:
                rollback_experiment(exp["id"], reason=reason)
                acted = True
        return acted
    except Exception:
        logger.exception("canary sweep failed")
        return False
