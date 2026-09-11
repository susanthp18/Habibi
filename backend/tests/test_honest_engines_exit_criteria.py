"""W0–W8 exit criteria that fail the profile instead of skipping."""

from __future__ import annotations

import inspect
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


def test_fresh_sql_vocabulary_includes_w12() -> None:
    sql = (BACKEND / "sql" / "32_offer_absorption.sql").read_text(encoding="utf-8")
    assert "suitability_assessments" in sql
    # §9.7's column list. The mis-selling audit trail is what an inspection asks
    # for, and one whose evidence pointer is optional is a note.
    for column in ("assessed_at", "assessor", "policy_version", "verdict", "evidence_ref"):
        assert f"{column} " in sql, column
    assert "ck_suitability_evidence" in sql
    # §15.4: one log. The family column, and the state that keeps the offer off
    # the collections call.
    assert "action_family" in sql
    assert "'deferred_promotional'" in sql
    assert "ck_treatment_decisions_family_shape" in sql
    # §15.2 W0: no ACCESS EXCLUSIVE without NOT VALID or CONCURRENTLY. Both
    # CHECK repairs on the busiest table in the schema go through the two-step.
    assert sql.count("NOT VALID") >= 2
    assert sql.count("VALIDATE CONSTRAINT") >= 2
    assert (
        BACKEND / "alembic" / "versions" / "20260910_0121_offer_absorption.py"
    ).is_file()


def test_fresh_sql_vocabulary_includes_w13() -> None:
    sql = (BACKEND / "sql" / "33_allocator.sql").read_text(encoding="utf-8")
    # §10.1 defects 2, 3 and 4: the columns that say whether a price can be
    # believed. Without them ``converged`` meant only "no bisection moved and
    # nothing hit the ceiling", which is not a statement about optimality.
    for column in (
        "capacity_source",
        "dual_price_raw",
        "dual_bound",
        "primal_value",
        "duality_gap",
        "feasible",
        "damping",
    ):
        assert column in sql, column
    # §10.2: "unconfigured" and "a budget of nothing" stop being the same
    # number. Measured on `collections` 2026-09-11, one row read
    # `capacity = 0.00, demand = 486, converged = t` and meant the first.
    assert "ALTER COLUMN capacity DROP NOT NULL" in sql
    assert "ck_capacity_duals_source" in sql
    assert "'feed'" in sql and "'env'" in sql and "'unset'" in sql
    # §15.2 W0: no ACCESS EXCLUSIVE without NOT VALID or CONCURRENTLY.
    assert "NOT VALID" in sql and "VALIDATE CONSTRAINT" in sql
    assert (
        BACKEND / "alembic" / "versions" / "20260911_0122_allocator.py"
    ).is_file()


def test_the_allocator_write_switch_has_no_bypass() -> None:
    """§8.12: "a gate with a documented bypass is worse than no gate".

    ``TREATMENT_DUAL_PRICING`` gates λ into the cost term, which changes who gets
    contacted. §10.4 puts six measured conditions in front of it, so the source
    of :func:`allocate.enabled` must consult them and must not offer an override
    flag beside them.
    """
    import inspect

    from agent_core.treatment import allocate

    source = inspect.getsource(allocate.enabled)
    assert "write_switch_objections" in source or "_cached_objections" in source, (
        "enabled() reads the environment variable alone, so an operator can "
        "switch on a price no gate has cleared"
    )
    for bypass in ("OVERRIDE", "FORCE", "SKIP_GATE", "IGNORE_GATE"):
        assert bypass not in inspect.getsource(allocate), bypass


def test_the_serving_path_carries_no_solver_import() -> None:
    """``allocate`` is imported by ``costs.for_action`` and therefore by the API.

    Measured 2026-09-11: ``collections_api`` and both batch workers have no
    numpy. A module-level import in this file is an outage, not a slow start.
    Asserted here as well as in the wave suite because this file is the one CI
    runs when it wants to know whether the contracts still hold.
    """
    import ast

    tree = ast.parse(
        (BACKEND / "agent_core" / "treatment" / "allocate.py").read_text("utf-8")
    )
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"numpy", "scipy"}), imported


#: What `offer_decisions` costs today, outside alembic history. W12 opened a
#: dual-write window rather than cutting over, so this number is what says the
#: window is closing rather than a promise that it will.
#:
#: Measured 2026-09-10, immediately after the W12 commit. Lower it when a reader
#: moves; never raise it. A new reader of the retired log is a new thing to
#: migrate later, and "later" is what turned a missing propensity column into a
#: corpus that can never be off-policy evaluated.
OFFER_DECISIONS_REFERENCE_CEILING = 57


def test_the_retired_offer_log_only_ever_loses_readers() -> None:
    """The ratchet that closes W12's dual-write window.

    §15.4 retires `offer_decisions` into `treatment_decisions` as
    `action_family='offer'`, and the write is dual for one window so that no
    reader is missed in a single commit. What stops a window from becoming a
    permanent second source of truth is not a deadline, which nobody enforces,
    but a count that may only go down.
    """
    import re

    # Enumerated rather than rglob'd: `backend/.venv` and `node_modules` make a
    # recursive walk of this tree slow enough to look hung, which the repo has
    # been bitten by before. These are every directory that can hold a reader.
    roots = [BACKEND] + [
        BACKEND / d for d in ("agent_core", "scripts", "voice", "bank_boundary")
    ]
    paths: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        paths.update(root.glob("*.py") if root == BACKEND else root.rglob("*.py"))

    hits = 0
    offenders: list[str] = []
    for path in sorted(paths):
        rel = path.relative_to(BACKEND).as_posix()
        if "__pycache__" in rel:
            continue
        found = len(re.findall(r"offer_decisions", path.read_text(encoding="utf-8")))
        if found:
            hits += found
            offenders.append(f"{rel}:{found}")
    assert hits <= OFFER_DECISIONS_REFERENCE_CEILING, (
        f"{hits} references to the retired offer log, ceiling is "
        f"{OFFER_DECISIONS_REFERENCE_CEILING}. Lower the ceiling when a reader "
        f"moves; never raise it. Current: {offenders}"
    )


def test_no_reachable_say_in_the_offer_path_names_a_product() -> None:
    """W12's exit criterion: 0 code paths in which an offer is utterable on a
    collections call.

    §9.7 makes a promotional utterance inside a recorded collections call three
    breaches at once, and the invariant that makes the absorption lawful is that
    the offer is *scored* on the call and never *spoken* on it. The gate is one
    function -- `reco.engine.RecommendationResult.to_tool_payload` -- because
    both mouths and every future one route through it.
    """
    from agent_core.reco import engine as reco_engine

    for name in ("bot_tools.py", "voice/tools.py", "bot_runtime.py"):
        code = "\n".join(
            line
            for line in (BACKEND / name).read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        for pitch in (
            "mention this ONE product",
            "talkTrack",
            "suggestedAmount",
        ):
            assert pitch not in code, f"{name} can still put a product in a mouth"

    payload_src = inspect.getsource(reco_engine.RecommendationResult.to_tool_payload)
    for leaked in ("productId", "productName", "suggestedAmount", "talkTrack", "roi"):
        assert leaked not in payload_src, f"to_tool_payload still emits {leaked}"
    assert "do not mention any product" in reco_engine.DEFERRED_SAY


def test_the_shrinkage_constant_is_measured_or_refused() -> None:
    """§15.3: no number measured on `simulate_treatment_corpus.py` may select a
    hyperparameter again, and `DEFAULT_SHRINKAGE_K = 750` was.

    §8.10 replaces it with `k = sigma2_within / sigma2_between` from the panel.
    An unmeasurable `k` is a refusal on §8.12's rule, not a fallback to 750 --
    and the refusal is cheap, because no measured `k` means no promoted segments
    and the population model answers for every stratum.
    """
    from agent_core.treatment import hierarchy

    k, band, basis = hierarchy.shrinkage_k([], level="borrower")
    assert k is None and band is None
    assert "750" in basis, "the refusal does not name what it is refusing to use"
    src = inspect.getsource(hierarchy)
    assert "cluster.icc" in src, "k is not measured off the panel's ICC"
    assert "DEFAULT_SHRINKAGE_K" not in src, "the simulator's constant leaked back in"


def test_the_heterogeneity_gate_has_no_bonferroni_left_in_it() -> None:
    """Two multiplicity corrections in one file is a bypass waiting to be cited.

    §8.10 rung 3 asks for Benjamini-Hochberg at FDR 0.10, out of sample, against
    the leave-one-segment-out population, with a cluster-bootstrap SE for the
    difference `[heterogeneity-gate-is-in-sample-and-subset-vs-pool]`.
    """
    src = (BACKEND / "scripts" / "train_treatment_models.py").read_text(encoding="utf-8")
    assert "heterogeneity_z" not in src
    assert "HETEROGENEITY_ALPHA" not in src
    assert "_ate_stderr" not in src.replace("`_ate_stderr`", "")
    assert "bh_reject" in src and "losoAte" in src
    assert "cluster.bootstrap" in src


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
