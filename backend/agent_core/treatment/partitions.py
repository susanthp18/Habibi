"""Expand/contract scaffolding for treatment_decisions payload partitions.

Dual-write and cutover are independently switchable and default off. Nothing
here is activated until the orchestrator verifies the cutover on a scratch
database. The CREATE lives in sql/05_collections.sql as a commented block so
a fresh install does not silently partition.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from env_utils import env_bool


def dual_write_enabled() -> bool:
    return env_bool("TREATMENT_PAYLOAD_DUAL_WRITE")


def maybe_dual_write(
    conn: Any,
    *,
    decision_id: str,
    features: str,
    candidates: str,
    excluded: str,
) -> None:
    """Copy jsonb blobs to the sidecar table when the flag is on.

    Failures are swallowed: the canonical row is treatment_decisions, and a
    sidecar miss must not lose a decision.
    """
    if not dual_write_enabled():
        return
    try:
        conn.execute(
            text(
                """
                INSERT INTO treatment_decision_payloads (
                  decision_id, features, candidates, excluded, created_at
                ) VALUES (
                  :id, CAST(:features AS jsonb), CAST(:candidates AS jsonb),
                  CAST(:excluded AS jsonb), now()
                )
                ON CONFLICT (decision_id) DO NOTHING
                """
            ),
            {
                "id": decision_id,
                "features": features,
                "candidates": candidates,
                "excluded": excluded,
            },
        )
    except Exception:
        return
