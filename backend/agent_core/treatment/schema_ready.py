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


def w11_ready(conn: Any) -> bool:
    """Whether gates 14 and 15 can be evaluated at all on this database."""
    return has_table(conn, "treatment_pre_registrations")


def w12_ready(conn: Any) -> bool:
    """Whether the offer family has somewhere to live in the treatment log.

    Gates the *second* half of W12's dual write. On a database behind
    ``sql/32_offer_absorption.sql`` the reco engine keeps writing
    ``offer_decisions`` alone, which is the state every deployment is in until
    0121 is applied -- and is why the absorption is a window rather than a
    cutover.
    """
    return has_column(conn, "treatment_decisions", "action_family")


def w13_ready(conn: Any) -> bool:
    """Whether a capacity solve can record whether it could be believed.

    ``capacity_duals.feasible`` (sql/33, migration 0122). On a database behind
    it, ``allocate.persist`` has nowhere to write the repair's verdict and
    ``_todays_prices`` cannot filter on it -- so W13's own reads refuse rather
    than serving a price whose feasibility nothing recorded.
    """
    return has_column(conn, "capacity_duals", "feasible")


def suitability_ready(conn: Any) -> bool:
    """Whether a suitability finding can be read at all on this database.

    Separate from :func:`w12_ready` because the two answer different questions
    to different callers, and because an absent table here is a *refusal* rather
    than a degradation: §9.7 makes an offer unenactable without a current row,
    and a database that cannot say whether one exists has not said yes.
    """
    return has_table(conn, "suitability_assessments")


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


def w9_ready(conn: Any) -> bool:
    return has_table(conn, "perception_facts") and has_table(conn, "perception_runs")


def w10_ready(conn: Any) -> bool:
    """Whether an attempt's cost can be attributed to the decision that bought it.

    The column is W6's — ``sql/25_decision_substrate.sql`` adds it and migration
    0113 mirrors it — so this probe is not gating a new migration. It gates the
    fact that 0113 is deliberately unapplied to the running database, which is
    why ``config.observed_costs`` has to ask rather than assume.

    W10a's contribution is not the column. It is that something finally reads
    it: the writer, the context variable and the enactment scope were all in
    place, and ``costs.for_action`` still returned a constant.
    """
    return has_column(conn, "usage_events", "decision_id")


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
