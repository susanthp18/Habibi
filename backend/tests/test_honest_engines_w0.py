"""W0 — stop corrupting the corpus."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]


def test_migration_repairs_both_constraint_spellings_not_valid() -> None:
    src = (BACKEND / "alembic" / "versions" / "20260906_0107_honest_engines.py").read_text(
        encoding="utf-8"
    )
    assert "NOT VALID" in src
    assert "VALIDATE CONSTRAINT" in src
    assert "ck_treatment_decisions_mode" in src
    assert "treatment_decisions_mode_check" in src
    assert "represent_mandate" in src
    assert "simulated" in src
    assert "unresolved" in src
    assert "CREATE INDEX CONCURRENTLY" not in src


def test_fresh_sql_has_honest_vocabulary() -> None:
    sql = (BACKEND / "sql" / "05_collections.sql").read_text(encoding="utf-8")
    assert "'simulated'" in sql
    assert "'represent_mandate'" in sql
    assert "'unresolved'" in sql
    assert "'parked'" in (BACKEND / "sql" / "22_campaigns.sql").read_text(encoding="utf-8")


def test_preview_writes_zero_decision_rows(db_tx) -> None:
    row = db_tx.execute(
        text(
            """
            SELECT a.id, a.customer_id FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE a.dpd BETWEEN 1 AND 30 AND c.phone_primary IS NOT NULL
            ORDER BY a.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("no seed account")
    before = db_tx.execute(text("SELECT count(*) FROM treatment_decisions")).scalar()
    from agent_core.treatment import Trigger, recommend_treatment

    recommend_treatment(
        customer_id=row["customer_id"],
        account_id=row["id"],
        trigger=Trigger(kind="manual"),
        conn=db_tx,
        persist="preview",
    )
    after = db_tx.execute(text("SELECT count(*) FROM treatment_decisions")).scalar()
    assert after == before


def test_tuner_and_rerank_are_gone() -> None:
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agent_core.tuner")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agent_core.treatment.rerank")
    main = (BACKEND / "main.py").read_text(encoding="utf-8")
    assert "tuner-suggestions" not in main
    assert "ALLOW_UNHARDENED_PRODUCTION" not in main


def test_bot_worker_uses_redacting_setup() -> None:
    src = (BACKEND / "bot_worker.py").read_text(encoding="utf-8")
    assert "observability.setup_logging()" in src
    assert "logging.basicConfig" not in src


def test_get_and_snapshot_are_preview() -> None:
    holds = (BACKEND / "db_treatment_holds.py").read_text(encoding="utf-8")
    assert 'persist="preview"' in holds
    db = (BACKEND / "db.py").read_text(encoding="utf-8")
    assert 'persist="preview"' in db
    engine = (BACKEND / "agent_core" / "treatment" / "engine.py").read_text(
        encoding="utf-8"
    )
    assert "begin_nested" in engine
    assert "PERSIST_PREVIEW" in engine


def test_trainers_refuse_the_serving_path() -> None:
    treatment = (BACKEND / "scripts" / "train_treatment_models.py").read_text(
        encoding="utf-8"
    )
    reco = (BACKEND / "scripts" / "train_propensity.py").read_text(encoding="utf-8")
    assert "refusing to write" in treatment
    assert "models/challengers" in treatment
    assert "refusing to write" in reco
    assert "models/challengers/propensity.json" in reco
    compose = (BACKEND / "docker-compose.yml").read_text(encoding="utf-8")
    assert "HABIBI_DEPLOYED" in compose
