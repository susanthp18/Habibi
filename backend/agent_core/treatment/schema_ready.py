"""Detect whether the honest-engines schema has been applied.

The migration is written in this tranche and is applied by the orchestrator.
Callers that INSERT new columns must not fail the live database before that
window; they fall back to the columns that already exist.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

_CACHE: dict[str, bool] = {}


def has_column(conn: Any, table: str, column: str) -> bool:
    key = f"{table}.{column}"
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    try:
        found = conn.execute(
            text(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = :t
                  AND column_name = :c
                """
            ),
            {"t": table, "c": column},
        ).first()
        present = found is not None
    except Exception:
        present = False
    _CACHE[key] = present
    return present


def has_table(conn: Any, table: str) -> bool:
    key = f"table:{table}"
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    try:
        found = conn.execute(
            text("SELECT to_regclass(:n)"), {"n": f"public.{table}"}
        ).scalar()
        present = found is not None
    except Exception:
        present = False
    _CACHE[key] = present
    return present


def reset_cache() -> None:
    _CACHE.clear()


def w2_ready(conn: Any) -> bool:
    return has_column(conn, "treatment_decisions", "arm_propensity")


def w1_ready(conn: Any) -> bool:
    return has_table(conn, "enactment_attempts") and has_column(
        conn, "treatment_decisions", "cancel_reason"
    )


def labels_ready(conn: Any) -> bool:
    return has_column(conn, "treatment_decisions", "reach_outcome")


def w4_ready(conn: Any) -> bool:
    return has_column(conn, "policy_rules", "rule_id") and has_table(
        conn, "policy_rule_kinds"
    )


def w5_ready(conn: Any) -> bool:
    return has_table(conn, "bank_contracts") and has_table(
        conn, "bank_inbound_manifests"
    )


def w7_ready(conn: Any) -> bool:
    return has_table(conn, "analysis_panel")


def w8_ready(conn: Any) -> bool:
    return has_table(conn, "engine_config") and has_table(conn, "config_epoch")


def retention_ready(conn: Any) -> bool:
    """W8b. Separate from ``w8_ready`` so a database carrying only 0116 is
    still a valid W8a database rather than a half-failed W8 one."""
    return (
        has_table(conn, "retention_rules")
        and has_table(conn, "subject_keys")
        and has_table(conn, "recording_holds")
        and has_column(conn, "treatment_decisions", "retain_until")
    )


def w6_ready(conn: Any) -> bool:
    return (
        has_table(conn, "fct_loan_state")
        and has_table(conn, "feature_snapshot_daily")
        and has_table(conn, "treatment_sweep_runs")
        and has_column(conn, "accounts", "shard_key")
        and has_column(conn, "treatment_decisions", "features_known_ts")
        and has_column(conn, "usage_events", "decision_id")
    )
