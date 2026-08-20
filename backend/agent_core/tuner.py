"""Tuner — shadow ``RECO_W_*`` suggestions from decision logs. Never writes env."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

# The live knobs. Suggestions are deltas a human copies; nothing here mutates
# ``os.environ`` or a secrets store.
_KNOBS = (
    "RECO_W_AFFINITY",
    "RECO_W_AFFORDABILITY",
    "RECO_W_CREDIT",
    "RECO_W_INTENT",
    "RECO_W_SENTIMENT",
    "RECO_W_CAMPAIGN",
    "RECO_W_FATIGUE",
    "RECO_W_EXIT_INTENT",
)


def suggestions(*, days: int = 14) -> dict[str, Any]:
    import os

    import db
    from agent_core.reco import config as reco_config

    weights = reco_config.weights()
    current = {
        "RECO_W_AFFINITY": weights.affinity,
        "RECO_W_AFFORDABILITY": weights.affordability,
        "RECO_W_CREDIT": weights.credit_health,
        "RECO_W_INTENT": weights.in_call_intent,
        "RECO_W_SENTIMENT": weights.sentiment,
        "RECO_W_CAMPAIGN": weights.campaign_priority,
        "RECO_W_FATIGUE": weights.fatigue_penalty,
        "RECO_W_EXIT_INTENT": weights.exit_intent_penalty,
    }
    declined = 0
    presented = 0
    try:
        with db.engine.connect() as conn:
            row = db._one(
                conn.execute(
                    text(
                        """
                        SELECT
                          COUNT(*) FILTER (WHERE presented AND response = 'declined') AS declined,
                          COUNT(*) FILTER (WHERE presented) AS presented
                        FROM offer_decisions
                        WHERE created_at >= now() - (:d * interval '1 day')
                        """
                    ),
                    {"d": max(1, days)},
                )
            )
        if row:
            declined = int(row.get("declined") or 0)
            presented = int(row.get("presented") or 0)
    except Exception:
        declined = 0
        presented = 0

    proposed = dict(current)
    note = "insufficient_log"
    if presented >= 20 and declined / presented > 0.6:
        proposed["RECO_W_FATIGUE"] = min(0.25, current["RECO_W_FATIGUE"] + 0.05)
        proposed["RECO_W_INTENT"] = max(0.05, current["RECO_W_INTENT"] - 0.05)
        note = "high_decline_rate"
    elif presented >= 20 and declined / presented < 0.2:
        proposed["RECO_W_INTENT"] = min(0.35, current["RECO_W_INTENT"] + 0.03)
        note = "low_decline_rate"

    return {
        "mode": "shadow",
        "applied": False,
        "note": note,
        "current": current,
        "suggested": proposed,
        "copyToEnv": [
            {"name": k, "value": proposed[k], "current": current[k]}
            for k in _KNOBS
            if proposed[k] != current[k]
        ],
        "evidence": {"presented": presented, "declined": declined, "days": days},
        "envPresent": {k: os.getenv(k) for k in _KNOBS},
        "treatment": _treatment(days=days),
    }


def _treatment(*, days: int) -> dict[str, Any]:
    """Shadow treatment knobs. Never writes ``TREATMENT_*`` env."""
    import os

    from agent_core.treatment import config as tcfg

    policy = tcfg.policy()
    current = {
        "TREATMENT_FATIGUE_COST": policy.fatigue_cost,
        "TREATMENT_MAX_ATTEMPTS_PER_CASE": policy.max_attempts_per_case,
        "TREATMENT_FIELD_DIGITAL_EXHAUSTION": policy.field_digital_exhaustion,
    }
    proposed = dict(current)
    note = "insufficient_log"
    field_n = 0
    actionable = 0
    try:
        import db

        with db.engine.connect() as conn:
            row = db._one(
                conn.execute(
                    text(
                        """
                        SELECT
                          COUNT(*) FILTER (
                            WHERE chosen_action IS NOT NULL AND chosen_action <> 'wait'
                          ) AS actionable,
                          COUNT(*) FILTER (WHERE chosen_action = 'field_visit') AS field_n
                        FROM treatment_decisions
                        WHERE created_at >= now() - (:d * interval '1 day')
                        """
                    ),
                    {"d": max(1, days)},
                )
            )
        if row:
            field_n = int(row.get("field_n") or 0)
            actionable = int(row.get("actionable") or 0)
    except Exception:
        field_n = 0
        actionable = 0
    if actionable >= 20 and field_n / actionable > 0.15:
        proposed["TREATMENT_FATIGUE_COST"] = current["TREATMENT_FATIGUE_COST"] + 2.0
        proposed["TREATMENT_FIELD_DIGITAL_EXHAUSTION"] = current["TREATMENT_FIELD_DIGITAL_EXHAUSTION"] + 1
        note = "high_field_share"
    copy = [
        {"name": k, "value": proposed[k], "current": current[k]}
        for k in current
        if proposed[k] != current[k]
    ]
    return {
        "mode": "shadow",
        "applied": False,
        "note": note,
        "current": current,
        "suggested": proposed,
        "copyToEnv": copy,
        "evidence": {"actionable": actionable, "fieldVisits": field_n, "days": days},
        "envPresent": {k: os.getenv(k) for k in current},
    }
