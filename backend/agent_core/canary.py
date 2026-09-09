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
    """Hash-split when an experiment is running.

    A missing customer id used to mean "send this call to the canary", which is
    the opposite of a cohort: unmatched inbound, sandbox, and anything that
    lost its ANI all landed on the unproven mouth. Missing identity now follows
    the baseline. Shadow experiments are not a runtime path — they also follow
    the baseline until the experiment is closed.
    """
    active = db.get_active_deployment(bot_id=bot_id, environment=environment)
    exp = running_experiment(bot_id, environment)
    if not exp:
        return (active or {}).get("id")
    canary_id = exp.get("canary_deployment_id")
    baseline_id = exp.get("baseline_deployment_id")
    pct = int(exp.get("traffic_pct") or 0)
    if exp.get("shadow"):
        return baseline_id or (active or {}).get("id")
    if pct >= 100:
        return canary_id or (active or {}).get("id")
    if not customer_id:
        return baseline_id or (active or {}).get("id")
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
    if shadow:
        # Shadow is stored on the card for authors who ticked it historically,
        # but it is not an execution path: there is no non-customer-serving
        # mouth. Refuse to open an experiment that would pretend otherwise.
        logger.warning(
            "refusing shadow experiment for bot=%s — shadow is not a runtime path",
            bot_id,
        )
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
        try:
            from agent_core import change_log

            change_log.record_experiment_rollback(
                conn,
                tenant_id=db.current_tenant(),
                actor_user_id=db._actor_user_id() or "system",
                entry_id=db._id("AUD"),
                bot_id=str(exp.get("bot_id") or ""),
                experiment_id=experiment_id,
                reason=reason,
                baseline_restored=bool(baseline),
            )
        except Exception:
            logger.exception("experiment rollback was not written to the change log")
        return {**dict(row), "baselineRestored": bool(baseline)}


def _scope(deployment_id: str | None) -> tuple[str, dict[str, Any]]:
    if deployment_id:
        return " AND i.deployment_id = :d", {"d": deployment_id}
    return "", {}


def _live_qa_burn(conn: Any, bot_id: str, *, deployment_id: str | None = None) -> float:
    extra, params = _scope(deployment_id)
    row = conn.execute(
        text(
            f"""
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
              {extra}
            """
        ),
        {"b": bot_id, **params},
    ).mappings().first()
    if not row:
        return 0.0
    prior = float(row.get("prior") or 0)
    recent = float(row.get("recent") or 0)
    if prior <= 0:
        return 1.0 if recent >= 3 else 0.0
    return recent / prior


def _abandoned(conn: Any, bot_id: str, *, deployment_id: str | None = None) -> int:
    """Calls where our side dropped after connecting. Target is zero, literally.

    Section 8.1 is explicit that this is not a rate to be managed down: a
    delinquent borrower whose phone rings, who answers, who hears silence and
    hangs up is the exact conduct the RBI amendment was written to stop. The
    design makes it structurally impossible by acquiring the slot before the
    dial, so any occurrence at all means something in that chain broke — which
    is why the threshold is one and not a percentage.
    """
    extra = " AND deployment_id = :d" if deployment_id else ""
    params: dict[str, Any] = {"b": bot_id}
    if deployment_id:
        params["d"] = deployment_id
    return int(
        conn.execute(
            text(
                f"""
                SELECT count(*) FROM call_attempts
                WHERE bot_id = :b
                  AND state = 'abandoned'
                  AND updated_at > now() - interval '15 minutes'
                  {extra}
                """
            ),
            params,
        ).scalar()
        or 0
    )


def _third_party_leaks(conn: Any, bot_id: str, *, deployment_id: str | None = None) -> int:
    """Times this bot said something about a debt to somebody who is not the borrower.

    ``third-party-leak`` is already in ``_LIVE_ALERT_FLAGS`` and can barge the
    call in progress, so the detection exists and works. What did not exist was
    anything that treated a canary producing them as a canary to pull.
    """
    extra, params = _scope(deployment_id)
    return int(
        conn.execute(
            text(
                f"""
                SELECT count(*)
                FROM interaction_flags f
                JOIN interactions i ON i.id = f.interaction_id
                WHERE i.handler_bot_id = :b
                  AND f.flag = 'third-party-leak'
                  AND f.created_at > now() - interval '15 minutes'
                  {extra}
                """
            ),
            {"b": bot_id, **params},
        ).scalar()
        or 0
    )


def _optouts(conn: Any, bot_id: str, *, deployment_id: str | None = None) -> int:
    """Borrowers who asked to be left alone after speaking to this bot."""
    extra = " AND a.deployment_id = :d" if deployment_id else ""
    params: dict[str, Any] = {"b": bot_id}
    if deployment_id:
        params["d"] = deployment_id
    return int(
        conn.execute(
            text(
                f"""
                SELECT count(*)
                FROM call_outcomes o
                JOIN call_attempts a ON a.id = o.attempt_id
                WHERE a.bot_id = :b
                  AND o.business = 'opt_out_requested'
                  AND o.created_at > now() - interval '15 minutes'
                  {extra}
                """
            ),
            params,
        ).scalar()
        or 0
    )


def _slo_miss(conn: Any, bot_id: str, *, deployment_id: str | None = None) -> bool:
    """p95 LLM time-to-first-byte, not whole-call duration.

    Whole-call length is almost always above VOICE_SLO_MS (800ms) — a
    two-minute conversation is 120,000ms — so the old signal fired on every
    answered call.
    """
    extra, params = _scope(deployment_id)
    row = conn.execute(
        text(
            f"""
            SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY t.llm_ttfb_ms) AS p95
              FROM interaction_transcript t
              JOIN interactions i ON i.id = t.interaction_id
             WHERE i.handler_bot_id = :b
               AND i.channel = 'voice'
               AND i.started_at > now() - interval '15 minutes'
               AND t.llm_ttfb_ms IS NOT NULL
               {extra}
            """
        ),
        {"b": bot_id, **params},
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


def close_running_experiments(
    conn: Any,
    *,
    bot_id: str,
    environment: str = "production",
    reason: str,
) -> None:
    """Mark every running experiment for this mouth rolled_back.

    A deployment rollback that left the experiment `running` kept the canary
    router hashing callers onto a mouth that was no longer active.
    """
    if not _require_table(conn):
        return
    conn.execute(
        text(
            """
            UPDATE deployment_experiments
               SET status = 'rolled_back', rollback_reason = :r, updated_at = now()
             WHERE bot_id = :b AND environment = :e AND status = 'running'
               AND tenant_id = :t
            """
        ),
        {
            "b": bot_id,
            "e": environment,
            "r": reason,
            "t": db.current_tenant(),
        },
    )


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
                        SELECT id, bot_id, auto_rollback, canary_deployment_id, shadow
                          FROM deployment_experiments
                         WHERE status = 'running' AND tenant_id = :t
                        """
                    ),
                    {"t": db.current_tenant()},
                )
            )
        acted = False
        for exp in rows:
            if exp.get("shadow"):
                rollback_experiment(exp["id"], reason="shadow_not_supported")
                acted = True
                continue
            triggers = exp.get("auto_rollback") or []
            if isinstance(triggers, str):
                import json

                try:
                    triggers = json.loads(triggers)
                except json.JSONDecodeError:
                    triggers = []
            reason = None
            canary = exp.get("canary_deployment_id")
            with db.engine.connect() as conn:
                if "eval_fail" in triggers:
                    # Scoped to the candidate's own prompt version, like every
                    # other trigger is scoped to the candidate's deployment.
                    # Un-scoped, the *baseline's* red-team failure pulled a
                    # healthy canary — and a candidate that fixed the failure
                    # kept being rolled back by the report it was fixing.
                    candidate_version = None
                    if canary:
                        row = db._one(
                            conn.execute(
                                text(
                                    "SELECT prompt_version_id FROM bot_deployments WHERE id = :d"
                                ),
                                {"d": canary},
                            )
                        )
                        candidate_version = (row or {}).get("prompt_version_id")
                    report = None
                    if candidate_version:
                        report = db.get_latest_eval_report(
                            bot_id=exp["bot_id"],
                            kind="redteam",
                            prompt_version_id=candidate_version,
                        )
                    # Falling back to the bot's newest report when the candidate
                    # has none of its own is deliberate, and it is the safe
                    # direction. Scoping alone would mean a report filed without
                    # provenance — every report predating that column — could
                    # never pull a canary, and a watchdog that goes quiet is a
                    # worse failure than one that pulls a healthy candidate.
                    if report is None:
                        report = db.get_latest_eval_report(
                            bot_id=exp["bot_id"], kind="redteam"
                        )
                    if report and str(report.get("status") or "") == "fail":
                        reason = "eval_fail"
                if reason is None and "slo_miss" in triggers:
                    try:
                        if _slo_miss(conn, exp["bot_id"], deployment_id=canary):
                            reason = "slo_miss"
                    except Exception:
                        logger.exception("canary slo sample failed")
                if reason is None and "live_qa_burn" in triggers:
                    try:
                        if _live_qa_burn(conn, exp["bot_id"], deployment_id=canary) > 1.5:
                            reason = "live_qa_burn"
                    except Exception:
                        logger.exception("canary live-qa sample failed")
                # The outbound three, checked last only because they are the
                # newest; each is independently sufficient and none of them is a
                # ratio against a baseline. There is no acceptable rate of
                # telling a stranger about somebody's debt.
                if reason is None and "abandon_rate" in triggers:
                    try:
                        if _abandoned(conn, exp["bot_id"], deployment_id=canary) > 0:
                            reason = "abandon_rate"
                    except Exception:
                        logger.exception("canary abandon sample failed")
                if reason is None and "third_party_leak" in triggers:
                    try:
                        if _third_party_leaks(conn, exp["bot_id"], deployment_id=canary) > 0:
                            reason = "third_party_leak"
                    except Exception:
                        logger.exception("canary leak sample failed")
                if reason is None and "optout_spike" in triggers:
                    try:
                        if _optouts(conn, exp["bot_id"], deployment_id=canary) >= OPTOUT_SPIKE_THRESHOLD:
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
