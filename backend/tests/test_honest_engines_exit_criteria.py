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
        assert schema_ready.retention_ready(db_tx), "0117 missing"
        assert schema_ready.w11_ready(db_tx), "0120 missing"
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
    assert (BACKEND / "alembic" / "versions" / "20260909_0117_retention.py").is_file()
    assert (BACKEND / "alembic" / "versions" / "20260910_0120_promotion_gate.py").is_file()


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


def test_fresh_sql_vocabulary_includes_w8b() -> None:
    sql = (BACKEND / "sql" / "28_retention.sql").read_text(encoding="utf-8")
    # A retention rule without a citation cannot answer why a record died on a
    # particular Tuesday, which is the whole question §14.2 exists to answer.
    assert "citation TEXT NOT NULL CHECK" in sql
    assert "changed_by <> approved_by" in sql
    for cls in ("identified", "pseudonymous", "recording", "processing_log", "evaluation"):
        assert f"'{cls}'" in sql
    assert "recording_holds" in sql
    assert "subject_keys" in sql


def test_fresh_sql_vocabulary_includes_w9() -> None:
    sql = (BACKEND / "sql" / "30_perception.sql").read_text(encoding="utf-8")
    assert "perception_facts" in sql
    assert "perception_runs" in sql
    # R-INJ-1's four classes. Provenance is a column with a CHECK, not a
    # convention: it is what makes "may this enter the EV" answerable at all.
    for cls in (
        "system_of_record",
        "operator_input",
        "borrower_utterance",
        "model_inference",
    ):
        assert f"'{cls}'" in sql
    assert "input_provenance" in sql
    # §12.3 and §13.1: tenant leads the key, or a cross-tenant scan is one
    # planner decision away.
    assert "PRIMARY KEY (tenant_id, id)" in sql
    assert (BACKEND / "alembic" / "versions" / "20260909_0119_perception.py").is_file()


def test_fresh_sql_vocabulary_includes_w11() -> None:
    sql = (BACKEND / "sql" / "31_promotion_gate.sql").read_text(encoding="utf-8")
    assert "treatment_pre_registrations" in sql
    # §8.12 gate 14's contents. A pre-registration missing any of these is a
    # note, and every one of them is what somebody would otherwise decide after
    # seeing the number it is meant to constrain.
    for column in (
        "primary_endpoint",
        "horizon_days",
        "estimator",
        "threshold",
        "family_size",
        "alpha_spending",
        "stopping_rule",
    ):
        assert f"{column} " in sql, column
    # §8.12 gate 15, as a database constraint rather than as application code --
    # the same choice engine_config and retention_rules already made.
    assert "ck_treatment_prereg_maker_checker" in sql
    assert "validator" in sql and "author" in sql
    assert "pre_registration_id" in sql
    assert (
        BACKEND / "alembic" / "versions" / "20260910_0120_promotion_gate.py"
    ).is_file()


def test_the_promotion_gate_has_no_lift_shaped_bypass() -> None:
    """§8.12: "A gate with a documented bypass is worse than no gate, because it
    will be cited as evidence that the property was tested."

    Gate 7 promotes on the confidence sequence's lower bound. An evaluation
    written before W11a carries a ``lift`` and no ``lcb``, and accepting the
    first in place of the second would make the new gate optional for exactly
    the artifacts that predate it -- which is every artifact in the tree.
    """
    src = (
        BACKEND / "agent_core" / "treatment" / "registry.py"
    ).read_text(encoding="utf-8")
    # ``lift`` survives only inside the refusal that names it, never as the
    # quantity compared against the floor.
    assert 'lift = evaluation.get("lift")' not in src
    assert 'evaluation.get("lcb")' in src
    assert "MIN_HOLDOUT_LIFT" in src


def test_usage_events_carries_exactly_one_decision_link() -> None:
    """W6 already delivered this column, and W10a nearly added it twice.

    ``\\d usage_events`` on the running database shows no ``decision_id``,
    because 0113 is deliberately unapplied there. Reading that as "the schema
    lacks the column" is a mistake the fresh-install path makes impossible to
    detect at runtime and easy to make while measuring — so it is asserted
    here instead: the column is declared once, in the W6 mirror, and a second
    file adding it would mean two migrations racing to define one link.
    """
    files = sorted((BACKEND / "sql").glob("*.sql"))
    adders = [
        p.name
        for p in files
        if "ALTER TABLE usage_events" in p.read_text(encoding="utf-8")
        and "decision_id" in p.read_text(encoding="utf-8")
    ]
    assert adders == ["25_decision_substrate.sql"], adders

    sql = (BACKEND / "sql" / "25_decision_substrate.sql").read_text(encoding="utf-8")
    # SET NULL, not CASCADE: a retention sweep that deletes a decision must not
    # delete the record that money was spent on it.
    assert "REFERENCES treatment_decisions(id) ON DELETE SET NULL" in sql


def test_the_mirror_carries_every_migration() -> None:
    """[[fresh-build-stamps-not-migrates]], asserted rather than remembered.

    A fresh install applies ``sql/*.sql`` and runs ``alembic stamp head`` — it
    never replays a migration. So a migration whose DDL exists only in
    ``alembic/versions`` ships to every existing deployment and to no new one,
    and the difference surfaces months later as a table that is missing on
    exactly the databases nobody was testing against.
    """
    versions = BACKEND / "alembic" / "versions"
    mirrors = {p.name for p in (BACKEND / "sql").glob("*.sql")}
    for migration in versions.glob("2026091*_01[12][0-9]_*.py"):
        body = migration.read_text(encoding="utf-8")
        if "exec_driver_sql" not in body:
            continue
        named = [name for name in mirrors if name in body]
        assert named, f"{migration.name} executes SQL that sql/ does not mirror"


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
