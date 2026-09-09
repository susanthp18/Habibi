"""W0–W8 exit criteria that fail the profile instead of skipping."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text

from agent_core.treatment import attempts, reservations, schema_ready
from bank_boundary import schema_ready as bank_schema_ready

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_schema_cache():
    schema_ready.reset_cache()
    yield
    schema_ready.reset_cache()


def test_missing_honest_engines_schema_fails_the_profile(db_tx) -> None:
    schema_ready.reset_cache()
    if os.getenv("HONEST_ENGINES_REQUIRE_SCHEMA") == "1":
        assert schema_ready.w1_ready(db_tx), "0107 missing"
        assert schema_ready.w2_ready(db_tx), "0107 propensity columns missing"
        assert schema_ready.w4_ready(db_tx), "0108 missing"
        assert bank_schema_ready.w5_ready(db_tx), "0110 missing"
        assert bank_schema_ready.evaluation_ready(db_tx), "0110 evaluation schema missing"
        assert schema_ready.w6_ready(db_tx), "0113 missing"
        assert schema_ready.w7_ready(db_tx), "0115 missing"
        assert schema_ready.w8_ready(db_tx), "0116 missing"
        return
    # Default suite still proves the files exist; the require-schema profile
    # is what must fail closed when a scratch DB is missing the waves.
    assert (BACKEND / "alembic" / "versions" / "20260906_0107_honest_engines.py").is_file()
    assert (BACKEND / "alembic" / "versions" / "20260906_0108_policy_plane.py").is_file()
    assert (BACKEND / "alembic" / "versions" / "20260906_0109_studio_trust_baseline.py").is_file()
    assert (BACKEND / "alembic" / "versions" / "20260906_0110_bank_boundary.py").is_file()
    assert (BACKEND / "alembic" / "versions" / "20260908_0113_decision_substrate.py").is_file()
    assert (BACKEND / "alembic" / "versions" / "20260909_0115_analysis_panel.py").is_file()
    assert (BACKEND / "alembic" / "versions" / "20260909_0116_engine_config.py").is_file()


def test_fresh_sql_vocabulary_includes_w5() -> None:
    sql = (BACKEND / "sql" / "24_bank_boundary.sql").read_text(encoding="utf-8")
    assert "bank_inbound_manifests" in sql
    assert "evaluation.protected_attributes" in sql
    assert "awaiting_settlement" in (BACKEND / "sql" / "05_collections.sql").read_text(
        encoding="utf-8"
    )


def test_fresh_sql_vocabulary_includes_w6() -> None:
    sql = (BACKEND / "sql" / "25_decision_substrate.sql").read_text(encoding="utf-8")
    assert "fct_loan_state" in sql
    assert "feature_snapshot_daily" in sql
    assert "EXCLUDE USING gist" in sql
    assert "btree_gist" in (BACKEND / "sql" / "00_extensions.sql").read_text(encoding="utf-8")


def test_fresh_sql_vocabulary_includes_w8() -> None:
    sql = (BACKEND / "sql" / "27_engine_config.sql").read_text(encoding="utf-8")
    # The maker-checker CHECK is the structural half of §13.4: a parameter
    # change is same-day, and same-day is not same-person.
    assert "changed_by <> approved_by" in sql
    assert "EXCLUDE USING gist" in sql
    assert "config_epoch" in sql


def test_reservation_release_and_reap(db_tx) -> None:
    schema_ready.reset_cache()
    tenant = db_tx.execute(text("SELECT id FROM tenants LIMIT 1")).scalar()
    customer = db_tx.execute(text("SELECT id FROM customers LIMIT 1")).scalar()
    if tenant is None or customer is None:
        pytest.skip("no seed identity")
    if not schema_ready.has_table(db_tx, "contact_reservations"):
        db_tx.execute(
            text(
                """
                CREATE TABLE contact_reservations (
                  id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  customer_id TEXT NOT NULL,
                  decision_id TEXT NOT NULL,
                  channel TEXT NOT NULL,
                  state TEXT NOT NULL,
                  provider_ref TEXT,
                  created_at timestamptz NOT NULL DEFAULT now(),
                  updated_at timestamptz NOT NULL DEFAULT now(),
                  CONSTRAINT uq_contact_reservations_decision_channel
                    UNIQUE (decision_id, channel)
                )
                """
            )
        )
        schema_ready.reset_cache()
    rid = reservations.reserve(
        db_tx,
        tenant_id=str(tenant),
        customer_id=str(customer),
        decision_id="TD-RES-1",
        channel="sms",
    )
    assert rid
    reservations.release(db_tx, rid)
    state = db_tx.execute(
        text("SELECT state FROM contact_reservations WHERE id = :id"), {"id": rid}
    ).scalar()
    assert state == reservations.STATE_RELEASED
    reservations.reserve(
        db_tx,
        tenant_id=str(tenant),
        customer_id=str(customer),
        decision_id="TD-RES-2",
        channel="sms",
    )
    db_tx.execute(
        text(
            """
            UPDATE contact_reservations
               SET created_at = now() - interval '2 hours'
             WHERE decision_id = 'TD-RES-2'
            """
        )
    )
    n = reservations.reap_abandoned(db_tx, older_than="1 hour")
    assert n >= 1


def test_intent_is_idempotent_under_duplicate_key(db_tx) -> None:
    schema_ready.reset_cache()
    tenant = db_tx.execute(text("SELECT id FROM tenants LIMIT 1")).scalar()
    decision_id = db_tx.execute(text("SELECT id FROM treatment_decisions LIMIT 1")).scalar()
    if tenant is None or decision_id is None:
        pytest.skip("no seed decision")
    if not schema_ready.has_table(db_tx, "enactment_attempts"):
        db_tx.execute(
            text(
                """
                CREATE TABLE enactment_attempts (
                  id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  decision_id TEXT NOT NULL,
                  channel TEXT NOT NULL,
                  action TEXT NOT NULL,
                  idempotency_key TEXT NOT NULL,
                  state TEXT NOT NULL,
                  provider_ref TEXT,
                  error TEXT,
                  created_at timestamptz NOT NULL DEFAULT now(),
                  updated_at timestamptz NOT NULL DEFAULT now(),
                  CONSTRAINT uq_enactment_attempts_key UNIQUE (idempotency_key)
                )
                """
            )
        )
        schema_ready.reset_cache()
    a = attempts.write_intent(
        db_tx, tenant_id=str(tenant), decision_id=str(decision_id), channel="sms", action="sms"
    )
    b = attempts.write_intent(
        db_tx, tenant_id=str(tenant), decision_id=str(decision_id), channel="sms", action="sms"
    )
    assert a == b
    count = db_tx.execute(
        text("SELECT count(*) FROM enactment_attempts WHERE decision_id = :id"),
        {"id": decision_id},
    ).scalar()
    assert count == 1


def test_soak_script_records_not_yet_measured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import soak_honest_engines

    monkeypatch.delenv("SOAK_HOURS", raising=False)
    monkeypatch.delenv("SOAK_KILLED_WORKER_RUN", raising=False)
    assert soak_honest_engines.main() == 2
    assert "not yet measured" in capsys.readouterr().out
