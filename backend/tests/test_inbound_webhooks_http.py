"""The PSP payment webhook and Meta's WhatsApp webhook, at the HTTP layer.

Both are public routes whose authentication is the HMAC in the request; both
had every assertion made by reading the handler. Signature, body and effect
are pinned here with real requests.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest
from sqlalchemy import text

import db

PAY_SECRET = "test-psp-webhook-secret"
WA_SECRET = "test-whatsapp-app-secret"
WA_VERIFY = "test-verify-token"


@pytest.fixture()
def client(monkeypatch, db_tx):
    from fastapi.testclient import TestClient

    import actor_context
    import main as app_main

    monkeypatch.setenv("API_KEY", "webhook-test-key")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("PAYMENT_PROVIDER", "hosted")
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", PAY_SECRET)
    monkeypatch.setenv("WHATSAPP_APP_SECRET", WA_SECRET)
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", WA_VERIFY)
    actor_context.reload_api_key_map()
    return TestClient(app_main.app)


def _sig(secret: str, raw: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def _intent(db_tx) -> tuple[str, str]:
    row = db_tx.execute(
        text(
            """
            SELECT c.id, a.id AS account_id
              FROM customers c JOIN accounts a ON a.customer_id = c.id
             WHERE c.id <> 'UNKNOWN-CALLER' AND c.tenant_id = :t
             ORDER BY c.id LIMIT 1
            """
        ),
        {"t": db.current_tenant()},
    ).mappings().first()
    if not row:
        pytest.skip("no customer with an account seeded")
    intent_id = f"pi-wh-{uuid.uuid4().hex[:10]}"
    token = f"tok-{uuid.uuid4().hex}"
    db_tx.execute(
        text(
            """
            INSERT INTO payment_intents (id, tenant_id, customer_id, account_id, amount, public_token, status)
            VALUES (:id, :t, :cid, :aid, 250.00, :tok, 'sent')
            """
        ),
        {"id": intent_id, "t": db.current_tenant(), "cid": row["id"], "aid": row["account_id"], "tok": token},
    )
    return intent_id, token


# --- POST /webhooks/payments/{provider} -------------------------------------


def test_payment_webhook_refuses_an_unsigned_or_missigned_body(client) -> None:
    raw = b'{"amount": 250}'
    assert client.post("/webhooks/payments/hosted", content=raw).status_code == 401
    bad = client.post(
        "/webhooks/payments/hosted", content=raw, headers={"X-Payment-Signature": "sha256=" + "0" * 64}
    )
    assert bad.status_code == 401
    assert bad.json()["detail"] == "invalid_signature"


def test_payment_webhook_records_the_payment_against_the_intent(client, db_tx) -> None:
    intent_id, token = _intent(db_tx)
    raw = json.dumps({"token": token, "amount": 250, "providerRef": "psp-ref-1"}).encode()
    res = client.post(
        "/webhooks/payments/hosted", content=raw, headers={"X-Payment-Signature": _sig(PAY_SECRET, raw)}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True and body["intentId"] == intent_id and body["status"] == "paid"
    assert (
        db_tx.execute(text("SELECT status FROM payment_intents WHERE id = :id"), {"id": intent_id}).scalar()
        == "paid"
    )


def test_payment_webhook_maps_bad_input_to_400_and_unknown_intent_to_404(client) -> None:
    raw = b"not json"
    assert (
        client.post("/webhooks/payments/hosted", content=raw, headers={"X-Payment-Signature": _sig(PAY_SECRET, raw)}).status_code
        == 400
    )
    raw = b'{"token": "tok-nobody"}'
    no_amount = client.post(
        "/webhooks/payments/hosted", content=raw, headers={"X-Payment-Signature": _sig(PAY_SECRET, raw)}
    )
    assert no_amount.status_code == 400 and no_amount.json()["detail"] == "amount_required"
    raw = b'{"token": "tok-nobody", "amount": 1}'
    unknown = client.post(
        "/webhooks/payments/hosted", content=raw, headers={"X-Payment-Signature": _sig(PAY_SECRET, raw)}
    )
    assert unknown.status_code == 404, unknown.text


# --- GET /webhooks/whatsapp ---------------------------------------------------


def test_whatsapp_verification_echoes_the_challenge_only_for_the_right_token(client) -> None:
    ok = client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": WA_VERIFY, "hub.challenge": "12345"},
    )
    assert ok.status_code == 200 and ok.text == "12345"
    assert ok.headers["content-type"].startswith("text/plain")
    wrong = client.get(
        "/webhook/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "12345"},
    )
    assert wrong.status_code == 403


# --- POST /webhooks/whatsapp --------------------------------------------------


def test_whatsapp_receive_refuses_a_bad_signature_and_accepts_a_good_one(client, db_tx) -> None:
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": "919999900001", "profile": {"name": "HTTP Test"}}],
                            "messages": [
                                {
                                    "id": f"wamid.{uuid.uuid4().hex}",
                                    "from": "919999900001",
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": "hello from the webhook test"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    raw = json.dumps(payload).encode()
    forged = client.post(
        "/webhooks/whatsapp", content=raw, headers={"X-Hub-Signature-256": "sha256=" + "f" * 64}
    )
    assert forged.status_code == 403
    res = client.post(
        "/webhooks/whatsapp",
        content=raw,
        headers={"X-Hub-Signature-256": "sha256=" + _sig(WA_SECRET, raw), "Content-Type": "application/json"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert len(body["results"]) == 1
    assert body["results"][0].get("status") != "skipped"
