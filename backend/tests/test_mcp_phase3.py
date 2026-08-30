"""Phase 3 — HTTP MCP, vault, connectors, G10, gateway kill-switch.

HTTP tests hit the Starlette app from ``agent_core.mcp_http.http_app.build_app``,
never FastAPI. Mutators stay 403. ``enqueue_task`` is not on CHANNEL_MCP.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import mcp_tools
from agent_core.cards.compile import compile_card
from agent_core.cards.defaults import COLLECTIONS_BOT_ID, card_dump
from voice.flow_export import built_in_collections_graph
from agent_core.connectors.strip import strip_result
from agent_core.tools.catalog import CATALOG
from agent_core.tools.schema import CHANNEL_MCP
from llm_gateway.client import maybe_chat


def _compile(card_raw):
    return compile_card(
        bot_id=COLLECTIONS_BOT_ID,
        card_raw=card_raw,
        flow=built_in_collections_graph(),
        catalog_names=set(CATALOG.specs),
        known_bot_ids={COLLECTIONS_BOT_ID, "intake-v1", "insurance-v1", "supervisor-brief"},
    )


def _require_table(db_tx, name: str) -> None:
    row = db_tx.execute(text("SELECT to_regclass(:n) AS t"), {"n": f"public.{name}"}).mappings().first()
    if not row or not row["t"]:
        pytest.skip(f"{name} missing — apply alembic 20260815_0076")


def _customer(db_tx) -> tuple[str, str | None]:
    row = db_tx.execute(
        text(
            """
            SELECT c.id, a.id AS account_id
            FROM customers c
            LEFT JOIN accounts a ON a.customer_id = c.id
            WHERE c.id <> 'UNKNOWN-CALLER'
            ORDER BY c.id
            LIMIT 1
            """
        )
    ).mappings().first()
    if not row:
        pytest.skip("no customers seeded")
    return row["id"], row["account_id"]


def test_enqueue_task_is_not_on_mcp_catalog() -> None:
    exposed = {s.name for s in CATALOG.for_channel(CHANNEL_MCP)}
    assert "enqueue_task" not in exposed
    assert exposed == {
        "get_customer_context",
        "get_payment_history",
        "get_emi_schedule",
        "check_product_eligibility",
        "search_knowledge_base",
    }


def test_strip_drops_confused_deputy_keys() -> None:
    out = strip_result(
        {
            "ok": True,
            "status": "paid",
            "say": "We see the UPI success.",
            "tools": ["create_promise_to_pay"],
            "extraTool": "apply_goodwill",
        }
    )
    assert out["say"] == "We see the UPI success."
    assert out["status"] == "paid"
    assert "tools" not in out
    assert "extraTool" not in out


def test_maybe_chat_none_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_GATEWAY_ENABLED", raising=False)
    monkeypatch.setenv("LITELLM_BASE_URL", "http://127.0.0.1:4000")
    assert maybe_chat([{"role": "user", "content": "hi"}], profile="voice") is None


def test_maybe_chat_none_when_url_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_GATEWAY_ENABLED", "true")
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    assert maybe_chat([{"role": "user", "content": "hi"}]) is None


def test_g10_skipped_when_client_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_CLIENT_ENABLED", raising=False)
    report = _compile(card_dump(COLLECTIONS_BOT_ID))
    g10 = next(g for g in report.gates if g.gate == "G10")
    assert g10.status == "skipped"


def test_g10_fails_http_remote_when_client_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_CLIENT_ENABLED", "true")
    dumped = card_dump(COLLECTIONS_BOT_ID)
    dumped["connectors"] = [{"connector_id": "evil", "allow_prefixes": ["ext.evil."]}]

    def fake_get(_cid: str):
        return {
            "status": "approved",
            "kind": "remote_mcp",
            "url": "http://evil.example/mcp",
            "dataClass": ["pii"],
            "health": "healthy",
        }

    monkeypatch.setattr("agent_core.connectors.persist.get_connector", fake_get)
    report = _compile(dumped)
    g10 = next(g for g in report.gates if g.gate == "G10")
    assert g10.status == "fail"
    assert any("url_not_https" in str(issue) for issue in g10.issues)


def test_scope_denied_without_crm_read() -> None:
    from agent_core.mcp_http.protocol import handle_rpc

    with pytest.raises(PermissionError, match="scope_denied"):
        handle_rpc(
            "tools/call",
            {"name": "get_customer_context", "arguments": {"customer_id": "x"}},
            {"id": "k", "scopes": ["kb.search"]},
        )


def test_http_mutator_403(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_API_KEY", "test-mcp-key")
    from starlette.testclient import TestClient

    from agent_core.mcp_http.http_app import build_app

    client = TestClient(build_app())
    resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "create_promise_to_pay",
                "arguments": {"customer_id": "anyone", "amount": 1, "promised_date": "2099-01-01"},
            },
        },
        headers={"Authorization": "Bearer test-mcp-key"},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["message"] == "mutating_tools_denied"


def test_http_unauthorized_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    from starlette.testclient import TestClient

    from agent_core.mcp_http.http_app import build_app

    client = TestClient(build_app())
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp.status_code == 401


def test_http_scoped_key_lists_and_reads_context(monkeypatch: pytest.MonkeyPatch, db_tx) -> None:
    monkeypatch.setenv("MCP_API_KEY", "scoped-crm-key")
    customer_id, _ = _customer(db_tx)
    from starlette.testclient import TestClient

    from agent_core.mcp_http.http_app import build_app

    client = TestClient(build_app())
    headers = {"Authorization": "Bearer scoped-crm-key"}
    listed = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers=headers,
    )
    assert listed.status_code == 200
    names = {t["name"] for t in listed.json()["result"]["tools"]}
    assert "get_customer_context" in names
    assert "create_promise_to_pay" not in names
    assert "enqueue_task" not in names

    called = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_customer_context", "arguments": {"customer_id": customer_id}},
        },
        headers=headers,
    )
    assert called.status_code == 200
    text_payload = called.json()["result"]["content"][0]["text"]
    assert customer_id in text_payload or "outstanding" in text_payload.lower() or "name" in text_payload.lower()


@pytest.mark.parametrize("name", sorted(mcp_tools.DENIED))
def test_http_every_denied_tool_is_403(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_API_KEY", "test-mcp-key")
    from starlette.testclient import TestClient

    from agent_core.mcp_http.http_app import build_app

    client = TestClient(build_app())
    resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": {"customer_id": "x"}},
        },
        headers={"Authorization": "Bearer test-mcp-key"},
    )
    assert resp.status_code == 403


def test_paylink_says_upi_success_from_paid_row(db_tx) -> None:
    row = db_tx.execute(text("SELECT to_regclass('public.payment_intents') AS t")).mappings().first()
    if not row or not row["t"]:
        pytest.skip("payment_intents missing")
    customer_id, account_id = _customer(db_tx)
    if not account_id:
        pytest.skip("no account")
    import db

    intent_id = f"pi-test-{uuid.uuid4().hex[:10]}"
    db_tx.execute(
        text(
            """
            INSERT INTO payment_intents (
              id, tenant_id, customer_id, account_id, amount, public_token,
              status, paid_at, provider_ref
            ) VALUES (
              :id, :t, :cid, :aid, 250.00, :tok, 'paid', now(), 'upi-ok'
            )
            """
        ),
        {
            "id": intent_id,
            "t": db._tenant(),
            "cid": customer_id,
            "aid": account_id,
            "tok": f"tok-{uuid.uuid4().hex}",
        },
    )
    from agent_core.connectors.first_party import paylink_status

    out = paylink_status(customer_id)
    assert out["status"] == "paid"
    assert out["say"] == "We see the UPI success."
    assert "tools" not in out


def test_enqueue_task_returns_id_without_blocking(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    _require_table(db_tx, "mcp_tasks")
    monkeypatch.setenv("MCP_TASKS_ENABLED", "true")
    customer_id, _ = _customer(db_tx)
    from agent_core.mcp_http import tasks

    ticket = tasks.enqueue(kind="statement_generate", customer_id=customer_id, payload={"doc_type": "account_statement"})
    assert ticket["id"].startswith("mcpt-")
    assert ticket["status"] == "queued"
    assert "send" in ticket["say"].lower()
    row = tasks.get_task(ticket["id"])
    assert row is not None
    assert row["status"] == "queued"


def test_vault_round_trip_hides_ciphertext(db_tx) -> None:
    _require_table(db_tx, "vault_refs")
    from agent_core.vault.persist import list_refs, put_secret, reveal

    public = put_secret(name=f"test-ref-{uuid.uuid4().hex[:8]}", purpose="other", secret="super-secret-token")
    assert "ciphertext" not in public
    assert "secret" not in public
    assert "token" not in public
    assert public["hasSecret"] is True
    listed = list_refs()
    match = next(r for r in listed if r["id"] == public["id"])
    dumped = str(match)
    assert "super-secret-token" not in dumped
    assert reveal(public["id"]) == "super-secret-token"


def test_vault_seal_round_trip() -> None:
    from agent_core.vault.seal import open_sealed, seal

    token = seal("rotate-me")
    assert "rotate-me" not in token
    assert not token.startswith("vault://")
    assert open_sealed(token) == "rotate-me"
