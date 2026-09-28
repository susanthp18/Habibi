"""Phase 6 — continuous evals, shadow tuners, gateway model canary.

No Temporal. No auto-write of RECO_W_*. No skip-red-team. Twin never stores audio.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text


def _require_table(db_tx, name: str) -> None:
    row = db_tx.execute(text("SELECT to_regclass(:n) AS t"), {"n": f"public.{name}"}).mappings().first()
    if not row or not row["t"]:
        pytest.skip(f"{name} missing — apply alembic 20260815_0080")


def _require_column(db_tx, table: str, column: str) -> None:
    row = db_tx.execute(
        text(
            """
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = :t AND column_name = :c
            """
        ),
        {"t": table, "c": column},
    ).first()
    if not row:
        pytest.skip(f"{table}.{column} missing — apply alembic 20260815_0080")


def test_tuner_is_gone() -> None:
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agent_core.tuner")


def test_disagreement_mining_is_read_only() -> None:
    from agent_core.live_qa.disagreement import disagreements

    out = disagreements(limit=5)
    assert out["applied"] is False


def test_bot_analytics_includes_card_and_skill(db_tx) -> None:
    import db

    payload = db.bot_analytics("30d", "all")
    assert "byCard" in payload
    assert "skillHistogram" in payload
    assert isinstance(payload["byCard"], list)
    assert isinstance(payload["skillHistogram"], list)


