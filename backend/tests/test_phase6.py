"""Phase 6 — continuous evals, shadow tuners, gateway model canary.

No Temporal. No auto-write of RECO_W_*. No skip-red-team. Twin never stores audio.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from agent_core.eval.fixtures import CAPABILITY_TASKS, REDTEAM_CASES, TWIN_TASKS
from agent_core.eval.harness import run_suite_fixtures
from agent_core.tuner import suggestions
from llm_gateway import canary as gw_canary


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


def test_capability_and_twin_fixtures_pass() -> None:
    cap = run_suite_fixtures(CAPABILITY_TASKS)
    twin = run_suite_fixtures(TWIN_TASKS)
    assert cap["status"] == "pass", cap["trials"]
    assert twin["status"] == "pass", twin["trials"]


def test_injection_fixtures_still_fail_closed_after_upgrade() -> None:
    tasks = [
        {"id": c["id"], "name": c["name"], "grader": c["attack"], "fixture": c["fixture"]}
        for c in REDTEAM_CASES
    ]
    result = run_suite_fixtures(tasks)
    assert result["status"] == "pass", result["trials"]
    assert result["failed"] == 0


def test_schedule_refuses_to_skip_redteam() -> None:
    from agent_core.eval.schedule import run_continuous

    with pytest.raises(ValueError, match="redteam_required"):
        run_continuous(kinds=("regression", "twin"))


def test_tuner_visible_not_auto_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECO_W_FATIGUE", raising=False)
    monkeypatch.delenv("TREATMENT_FATIGUE_COST", raising=False)
    before = {k: os.getenv(k) for k in (
        "RECO_W_AFFINITY",
        "RECO_W_FATIGUE",
        "TREATMENT_FATIGUE_COST",
        "TREATMENT_MAX_ATTEMPTS_PER_CASE",
    )}
    out = suggestions(days=14)
    assert out["mode"] == "shadow"
    assert out["applied"] is False
    assert out["treatment"]["applied"] is False
    for key, val in before.items():
        assert os.getenv(key) == val


def test_canary_rejects_skip_redteam(db_tx) -> None:
    _require_table(db_tx, "gateway_canaries")
    with pytest.raises(ValueError, match="redteam_required"):
        gw_canary.propose("azure/gpt-new", skip_redteam=True)
    with pytest.raises(ValueError, match="redteam_required"):
        gw_canary.promote("gwc-x", skip_redteam=True)


def test_gateway_canary_analysis_then_text_then_voice(monkeypatch: pytest.MonkeyPatch, db_tx) -> None:
    _require_table(db_tx, "gateway_canaries")

    monkeypatch.setattr(
        gw_canary,
        "run_named_suite",
        lambda sid, origin="canary": {"status": "pass", "reportId": None, "kind": sid},
    )
    monkeypatch.setattr(gw_canary, "_injection_closed", lambda: True)
    monkeypatch.setattr(gw_canary, "_voice_slo_ms", lambda: 400)

    row = gw_canary.propose("azure/gpt-new")
    assert row["stage"] == "analysis"
    assert row["status"] == "pass"
    assert row["injectionClosed"] is True
    assert row["appliedEnv"] is False
    assert gw_canary.model_for("analysis") == "azure/gpt-new"
    assert gw_canary.model_for("text") is None
    assert gw_canary.model_for("voice") is None

    row = gw_canary.promote(row["id"])
    assert row["stage"] == "text"
    assert row["status"] == "pass"
    assert gw_canary.model_for("text") == "azure/gpt-new"
    assert gw_canary.model_for("voice") is None

    row = gw_canary.promote(row["id"])
    assert row["stage"] == "voice"
    assert row["status"] == "promoted"
    assert row["gates"]["voiceSloOk"] is True
    assert gw_canary.model_for("voice") == "azure/gpt-new"
    assert row["appliedEnv"] is False
    assert os.getenv("LLM_GATEWAY_VOICE_MODEL") != "azure/gpt-new" or os.getenv("LLM_GATEWAY_VOICE_MODEL") is None


def test_canary_blocks_when_redteam_fails(monkeypatch: pytest.MonkeyPatch, db_tx) -> None:
    _require_table(db_tx, "gateway_canaries")

    def fake_run(sid, origin="canary"):
        if "redteam" in sid:
            return {"status": "fail", "reportId": None}
        return {"status": "pass", "reportId": None}

    monkeypatch.setattr(gw_canary, "run_named_suite", fake_run)
    monkeypatch.setattr(gw_canary, "_injection_closed", lambda: True)
    monkeypatch.setattr(gw_canary, "_voice_slo_ms", lambda: 100)

    row = gw_canary.propose("azure/smarter")
    assert row["status"] == "fail"
    assert row["gates"]["redteam"] is False
    with pytest.raises(ValueError, match="stage_not_green"):
        gw_canary.promote(row["id"])
    assert gw_canary.model_for("voice") is None


def test_canary_blocks_slo_miss_on_voice(monkeypatch: pytest.MonkeyPatch, db_tx) -> None:
    _require_table(db_tx, "gateway_canaries")
    monkeypatch.setattr(
        gw_canary,
        "run_named_suite",
        lambda sid, origin="canary": {"status": "pass", "reportId": None},
    )
    monkeypatch.setattr(gw_canary, "_injection_closed", lambda: True)
    monkeypatch.setattr(gw_canary, "_voice_slo_ms", lambda: 400)

    row = gw_canary.propose("azure/gpt-slo")
    row = gw_canary.promote(row["id"])
    monkeypatch.setattr(gw_canary, "_voice_slo_ms", lambda: 2400)
    row = gw_canary.promote(row["id"])
    assert row["stage"] == "voice"
    assert row["status"] == "fail"
    assert row["gates"]["voiceSloOk"] is False
    assert gw_canary.model_for("voice") is None


def test_twin_corpus_from_outcomes_not_audio(db_tx) -> None:
    from agent_core.eval.corpus import _scrub, grow_from_kept_promises, list_corpus

    _require_table(db_tx, "twin_corpus")
    dirty = _scrub({"amount": 12, "audio": "AAAA", "raw_audio": "nope", "promiseId": "p1"})
    assert "audio" not in dirty
    assert "raw_audio" not in dirty
    assert dirty["amount"] == 12

    grown = grow_from_kept_promises(limit=5)
    assert grown["source"] == "ptp_kept"
    for row in list_corpus(limit=20):
        assert "audio" not in (row.get("outcome") or {})
        assert "raw_audio" not in (row.get("outcome") or {})


def test_capability_graduation_does_not_sign_skills(db_tx) -> None:
    from agent_core.eval.fixtures import CAPABILITY_COLLECTIONS_ID, REGRESSION_COLLECTIONS_ID
    from agent_core.eval.graduate import graduate_task

    _require_column(db_tx, "eval_tasks", "graduated_at")
    tenant = db_tx.execute(text("SELECT id FROM tenants WHERE id = :t"), {"t": __import__("db").current_tenant()}).scalar()
    if not tenant:
        pytest.skip("no tenant")
    db_tx.execute(
        text(
            """
            INSERT INTO eval_suites (id, tenant_id, kind, name, description)
            VALUES (:id, :t, 'capability', 'cap', '')
            ON CONFLICT (id) DO UPDATE SET kind = 'capability'
            """
        ),
        {"id": CAPABILITY_COLLECTIONS_ID, "t": tenant},
    )
    db_tx.execute(
        text(
            """
            INSERT INTO eval_suites (id, tenant_id, kind, name, description)
            VALUES (:id, :t, 'regression', 'reg', '')
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": REGRESSION_COLLECTIONS_ID, "t": tenant},
    )
    db_tx.execute(
        text(
            """
            INSERT INTO eval_tasks (id, suite_id, name, grader, fixture)
            VALUES ('task-cap-grad-test', :suite, 'hill', 'ptp_row', '{}'::jsonb)
            ON CONFLICT (id) DO UPDATE SET graduated_at = NULL
            """
        ),
        {"suite": CAPABILITY_COLLECTIONS_ID},
    )
    out = graduate_task("task-cap-grad-test")
    assert out["signedSkill"] is False
    assert out["suiteId"] == REGRESSION_COLLECTIONS_ID
    copied = db_tx.execute(
        text("SELECT 1 FROM eval_tasks WHERE id = :id AND suite_id = :s"),
        {"id": out["regressionTaskId"], "s": REGRESSION_COLLECTIONS_ID},
    ).first()
    assert copied


def test_skill_critique_does_not_write_production(db_tx) -> None:
    from agent_core.eval.critique import list_critiques
    from agent_core.eval.fixtures import REGRESSION_COLLECTIONS_ID

    _require_table(db_tx, "skill_critiques")
    tenant = db_tx.execute(text("SELECT id FROM tenants WHERE id = :t"), {"t": __import__("db").current_tenant()}).scalar()
    if not tenant:
        pytest.skip("no tenant")
    db_tx.execute(
        text(
            """
            INSERT INTO eval_suites (id, tenant_id, kind, name, description)
            VALUES (:id, :t, 'regression', 'reg', '')
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": REGRESSION_COLLECTIONS_ID, "t": tenant},
    )
    import db

    saved = db.save_eval_report(
        suite_id=REGRESSION_COLLECTIONS_ID,
        bot_id=None,
        status="fail",
        summary={"failed": 1, "total": 1},
        trials=[
            {
                "taskId": "task-verify-before-ptp",
                "passed": False,
                "verdict": {"grader": "verify_before_ptp", "passed": False},
            }
        ],
        origin="scheduled",
    )
    from agent_core.eval.critique import critique_from_report

    rows = critique_from_report(saved["id"])
    assert rows
    assert rows[0]["writesProduction"] is False
    assert rows[0]["status"] == "draft"
    listed = list_critiques()
    assert any(r["id"] == rows[0]["id"] for r in listed)


def test_disagreement_mining_is_read_only() -> None:
    from agent_core.eval.disagreement import disagreements

    out = disagreements(limit=5)
    assert out["applied"] is False


def test_bot_analytics_includes_card_and_skill(db_tx) -> None:
    import db

    payload = db.bot_analytics("30d", "all")
    assert "byCard" in payload
    assert "skillHistogram" in payload
    assert isinstance(payload["byCard"], list)
    assert isinstance(payload["skillHistogram"], list)


def test_eval_report_origin_persists(db_tx) -> None:
    from agent_core.eval.fixtures import REGRESSION_COLLECTIONS_ID

    _require_column(db_tx, "eval_reports", "origin")
    tenant = db_tx.execute(text("SELECT id FROM tenants WHERE id = :t"), {"t": __import__("db").current_tenant()}).scalar()
    if not tenant:
        pytest.skip("no tenant")
    db_tx.execute(
        text(
            """
            INSERT INTO eval_suites (id, tenant_id, kind, name, description)
            VALUES (:id, :t, 'regression', 'reg', '')
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": REGRESSION_COLLECTIONS_ID, "t": tenant},
    )
    import db

    saved = db.save_eval_report(
        suite_id=REGRESSION_COLLECTIONS_ID,
        bot_id=None,
        status="pass",
        summary={"failed": 0, "total": 1},
        origin="scheduled",
    )
    row = db_tx.execute(
        text("SELECT origin FROM eval_reports WHERE id = :id"), {"id": saved["id"]}
    ).mappings().first()
    assert row["origin"] == "scheduled"
