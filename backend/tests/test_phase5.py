"""Phase 5 — clone cards, canary, A2A mTLS, MCP Apps, OPA export. No Temporal."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from agent_core.tools.catalog import CATALOG


def _require_table(db_tx, name: str) -> None:
    row = db_tx.execute(text("SELECT to_regclass(:n) AS t"), {"n": f"public.{name}"}).mappings().first()
    if not row or not row["t"]:
        pytest.skip(f"{name} missing — apply alembic 20260815_0078")


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
    monkeypatch.setenv("A2A_TRUSTED_PROXY_CIDRS", "127.0.0.1/32")
    from agent_core.a2a import require_partner

    with pytest.raises(PermissionError, match="a2a_mtls_required"):
        require_partner(
            {"authorization": "Bearer secret", "x-ssl-client-verify": "NONE"},
            client_host="127.0.0.1",
        )


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


