"""Phase 5 — clone cards, canary, A2A mTLS, MCP Apps, OPA export. No Temporal."""

from __future__ import annotations

import ast
import hashlib
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from agent_core.cards.compile import compile_card
from agent_core.cards.defaults import COLLECTIONS_BOT_ID, FIRST_PARTY_BOT_IDS, card_dump
from voice.flow_export import built_in_collections_graph
from agent_core.cards.templates import templates
from agent_core.tools.catalog import CATALOG


def _require_table(db_tx, name: str) -> None:
    row = db_tx.execute(text("SELECT to_regclass(:n) AS t"), {"n": f"public.{name}"}).mappings().first()
    if not row or not row["t"]:
        pytest.skip(f"{name} missing — apply alembic 20260815_0078")


def _compile(card_raw, **kw):
    return compile_card(
        bot_id=COLLECTIONS_BOT_ID,
        card_raw=card_raw,
        flow=built_in_collections_graph(),
        catalog_names=set(CATALOG.specs),
        known_bot_ids={COLLECTIONS_BOT_ID, "intake-v1", "insurance-v1", "supervisor-brief"},
        **kw,
    )


def test_first_party_mouths_remain_four() -> None:
    assert FIRST_PARTY_BOT_IDS == frozenset(
        {"kaia-v2-4", "intake-v1", "insurance-v1", "supervisor-brief"}
    )
    ids = {t["id"] for t in templates()}
    assert ids == {"collections", "lapse", "hardship", "clerk"}
    assert not ids & FIRST_PARTY_BOT_IDS


def test_g12_full_ship_passes_without_rollback() -> None:
    report = _compile(card_dump(COLLECTIONS_BOT_ID), traffic_pct=100)
    g12 = next(g for g in report.gates if g.gate == "G12")
    assert g12.status == "pass"
    assert report.ok


def test_g12_canary_without_rollback_fails() -> None:
    report = _compile(card_dump(COLLECTIONS_BOT_ID), traffic_pct=10, auto_rollback=[])
    g12 = next(g for g in report.gates if g.gate == "G12")
    assert g12.status == "fail"
    assert report.http_status() == 422


def test_g12_canary_with_rollback_passes() -> None:
    report = _compile(
        card_dump(COLLECTIONS_BOT_ID),
        traffic_pct=10,
        auto_rollback=["eval_fail"],
    )
    g12 = next(g for g in report.gates if g.gate == "G12")
    assert g12.status == "pass"


def test_g13_skipped_when_not_exposing() -> None:
    report = _compile(card_dump(COLLECTIONS_BOT_ID))
    g13 = next(g for g in report.gates if g.gate == "G13")
    assert g13.status == "skipped"


def test_g13_fails_closed_without_cert(monkeypatch) -> None:
    monkeypatch.setenv("A2A_ENABLED", "true")
    dumped = card_dump(COLLECTIONS_BOT_ID)
    dumped["a2a"] = {"expose": True, "skill_ids": []}
    report = _compile(dumped, a2a_cert_ok=False)
    g13 = next(g for g in report.gates if g.gate == "G13")
    assert g13.status == "fail"
    assert "bearer" in g13.detail.lower() or "cert" in g13.detail.lower()


def test_g14_skipped_on_dry_run() -> None:
    report = _compile(card_dump(COLLECTIONS_BOT_ID))
    g14 = next(g for g in report.gates if g.gate == "G14")
    assert g14.status == "skipped"
    assert report.ok


def test_g14_fail_is_403() -> None:
    report = _compile(card_dump(COLLECTIONS_BOT_ID), has_publish=False)
    g14 = next(g for g in report.gates if g.gate == "G14")
    assert g14.status == "fail"
    assert report.http_status() == 403


def test_voice_bot_does_not_import_a2a() -> None:
    src = Path(__file__).resolve().parents[1] / "voice" / "bot.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("agent_core.a2a"):
            raise AssertionError("voice/bot.py must not import agent_core.a2a")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("agent_core.a2a"):
                    raise AssertionError("voice/bot.py must not import agent_core.a2a")


def test_mcp_apps_ui_list(monkeypatch) -> None:
    monkeypatch.setenv("MCP_APPS_ENABLED", "true")
    from agent_core.mcp_http.protocol import handle_rpc

    listed = handle_rpc("ui/list", {}, {"scopes": ["crm.read"]})
    ids = {a["id"] for a in listed["apps"]}
    assert ids == {"handoff-prep", "ptp-confirm"}
    read = handle_rpc("resources/read", {"uri": "ui://handoff-prep"}, {"scopes": ["crm.read"]})
    assert read["contents"][0]["uri"] == "ui://handoff-prep"


def test_policy_export_opa_and_cedar(monkeypatch) -> None:
    monkeypatch.setenv("POLICY_EXPORT_ENABLED", "true")
    from agent_core.policy_export import bundle

    out = bundle(fmt="opa")
    assert "calling_hours_start := 8" in out["text"]
    assert "this card cannot disable DND" not in out["text"]
    cedar = bundle(fmt="cedar")
    assert "permit(" in cedar["text"]
    src = Path(__file__).resolve().parents[1].joinpath("agent_core/policy_export.py").read_text(encoding="utf-8")
    assert "def import_" not in src
    assert "hot-load" in src or "Projection only" in src


def test_a2a_bearer_without_cert_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("A2A_ENABLED", "true")
    from agent_core.a2a import require_partner

    with pytest.raises(PermissionError, match="a2a_mtls_required"):
        require_partner({"authorization": "Bearer secret", "x-ssl-client-verify": "NONE"})


def test_canary_hash_split_and_rollback(db_tx) -> None:
    _require_table(db_tx, "deployment_experiments")
    import db
    from agent_core.canary import pick_deployment_id, record_experiment, rollback_experiment, sweep_rollbacks

    bot_id = COLLECTIONS_BOT_ID
    canary_id = f"DEP-CANARY-{uuid.uuid4().hex[:8]}"
    baseline_id = f"DEP-BASE-{uuid.uuid4().hex[:8]}"
    published = db.get_published_prompt_version(bot_id)
    if published is None:
        pytest.skip("no published collections prompt")
    pv = published["id"]
    tts = "en-IN-NeerjaNeural"
    db_tx.execute(
        text(
            """
            UPDATE bot_deployments
               SET status = 'retired', updated_at = now()
             WHERE bot_id = :b AND environment = 'production' AND status = 'active'
            """
        ),
        {"b": bot_id},
    )
    for dep_id, status, pct in ((baseline_id, "retired", 100), (canary_id, "active", 10)):
        db_tx.execute(
            text(
                """
                INSERT INTO bot_deployments (
                  id, bot_id, prompt_version_id, tts_voice_id, environment, status,
                  traffic_pct, shadow, published_at, created_at, updated_at
                ) VALUES (
                  :id, :b, :pv, :tts, 'production', :st, :pct, false, now(), now(), now()
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": dep_id, "b": bot_id, "pv": pv, "tts": tts, "st": status, "pct": pct},
        )
    record_experiment(
        db_tx,
        bot_id=bot_id,
        canary_deployment_id=canary_id,
        baseline_deployment_id=baseline_id,
        traffic_pct=10,
        shadow=False,
        auto_rollback=["eval_fail"],
    )
    customer = "cust-stable-split"
    digest = hashlib.sha256(f"{bot_id}:{customer}".encode("utf-8")).digest()
    bucket = digest[0] % 100
    picked = pick_deployment_id(bot_id, customer_id=customer)
    if bucket < 10:
        assert picked == canary_id
    else:
        assert picked == baseline_id

    suite = db_tx.execute(text("SELECT id FROM eval_suites WHERE kind = 'redteam' LIMIT 1")).mappings().first()
    if suite:
        db.save_eval_report(
            suite_id=suite["id"],
            bot_id=bot_id,
            status="fail",
            summary={"failed": 1, "total": 1},
        )
        assert sweep_rollbacks() is True
        exp = db_tx.execute(
            text(
                """
                SELECT status, rollback_reason FROM deployment_experiments
                 WHERE bot_id = :b ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"b": bot_id},
        ).mappings().first()
        assert exp["status"] == "rolled_back"
        assert exp["rollback_reason"] == "eval_fail"
        canary = db_tx.execute(
            text("SELECT status FROM bot_deployments WHERE id = :id"), {"id": canary_id}
        ).mappings().first()
        base = db_tx.execute(
            text("SELECT status FROM bot_deployments WHERE id = :id"), {"id": baseline_id}
        ).mappings().first()
        assert canary["status"] == "retired"
        assert base["status"] == "active"
    else:
        rolled = rollback_experiment(
            db_tx.execute(
                text("SELECT id FROM deployment_experiments WHERE bot_id = :b AND status = 'running'"),
                {"b": bot_id},
            ).mappings().first()["id"],
            reason="manual",
        )
        assert rolled["status"] == "rolled_back"


def test_a2a_task_input_required_with_cert(db_tx, monkeypatch) -> None:
    _require_table(db_tx, "a2a_partners")
    monkeypatch.setenv("A2A_ENABLED", "true")
    from agent_core.a2a import create_task, fingerprint_dn, require_partner

    dn = "CN=bank-fraud.example"
    fp = fingerprint_dn(dn)
    db_tx.execute(
        text(
            """
            INSERT INTO a2a_partners (
              id, tenant_id, name, card_url, cert_fingerprint, cert_dn, allowed_skills, status
            ) VALUES (
              :id, :t, 'Fraud desk', 'https://partner.example/card.json', :fp, :dn, '{}', 'active'
            )
            ON CONFLICT (id) DO UPDATE SET cert_fingerprint = EXCLUDED.cert_fingerprint
            """
        ),
        {"id": f"a2a-p-{uuid.uuid4().hex[:6]}", "t": "hdfc.retail", "fp": fp, "dn": dn},
    )
    partner = require_partner({"x-ssl-client-verify": "SUCCESS", "x-ssl-client-dn": dn})
    task = create_task(
        partner=partner,
        skill_id="premium-lapse-chase",
        payload={"inputRequired": True, "reason": "confirm identity"},
        bot_id=COLLECTIONS_BOT_ID,
        cert_dn=dn,
    )
    assert task["status"] == "input-required"
    assert task["certDn"] == dn


def test_a2a_remote_completes_in_work_runtime_not_voice(db_tx) -> None:
    _require_table(db_tx, "work_runtime_jobs")
    _require_table(db_tx, "a2a_tasks")
    from agent_core.clerk import process_one
    from work_runtime import idempotency_key, start_workflow

    tid = f"a2a-{uuid.uuid4().hex[:8]}"
    db_tx.execute(
        text(
            """
            INSERT INTO a2a_tasks (id, tenant_id, skill_id, status, input)
            VALUES (:id, :t, 'premium-lapse-chase', 'submitted', '{}'::jsonb)
            """
        ),
        {"id": tid, "t": "hdfc.retail"},
    )
    start_workflow(
        workflow_type="a2a_remote",
        payload={"taskId": tid},
        customer_id=None,
        idempotency_key=idempotency_key(workflow_type="a2a_remote", trigger_ref=tid),
    )
    assert process_one() is True
    row = db_tx.execute(text("SELECT status FROM a2a_tasks WHERE id = :id"), {"id": tid}).mappings().first()
    assert row["status"] == "completed"


def test_lapse_suite_has_twelve_scenarios() -> None:
    from agent_core.eval.fixtures import LAPSE_REGRESSION_TASKS

    assert len(LAPSE_REGRESSION_TASKS) == 12
    graders = {t["grader"] for t in LAPSE_REGRESSION_TASKS}
    assert "verify_before_ptp" in graders
    assert "dnd" in graders
    assert "bounce_ladder" in graders
