"""The hosted checkout at the HTTP layer: open, pay, pay again, unknown link.

The two ``/pay`` routes were the only money-moving surface with no request
ever sent at them from a test; their behaviour was pinned by reading the
handler. Now the handler is one call into ``payments`` and the assertions
are on what a browser sees.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import db


@pytest.fixture()
def client(monkeypatch, db_tx):
    from fastapi.testclient import TestClient

    import actor_context
    import main as app_main

    monkeypatch.setenv("API_KEY", "hosted-pay-test-key")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("PAYMENT_PROVIDER", "hosted")
    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    actor_context.reload_api_key_map()
    return TestClient(app_main.app)


HEADERS = {"X-API-Key": "hosted-pay-test-key", "X-Actor-User-Id": "priya-nair"}


def _intent(db_tx) -> tuple[str, str]:
    row = db_tx.execute(
        text(
            """
            SELECT c.id, a.id AS account_id
              FROM customers c
              JOIN accounts a ON a.customer_id = c.id
             WHERE c.id <> 'UNKNOWN-CALLER' AND c.tenant_id = :t
             ORDER BY c.id
             LIMIT 1
            """
        ),
        {"t": db.current_tenant()},
    ).mappings().first()
    if not row:
        pytest.skip("no customer with an account seeded")
    intent_id = f"pi-http-{uuid.uuid4().hex[:10]}"
    token = f"tok-{uuid.uuid4().hex}"
    db_tx.execute(
        text(
            """
            INSERT INTO payment_intents (
              id, tenant_id, customer_id, account_id, amount, public_token, status
            ) VALUES (:id, :t, :cid, :aid, 250.00, :tok, 'sent')
            """
        ),
        {"id": intent_id, "t": db.current_tenant(), "cid": row["id"], "aid": row["account_id"], "tok": token},
    )
    return intent_id, token


def _status(db_tx, intent_id: str) -> str:
    return db_tx.execute(
        text("SELECT status FROM payment_intents WHERE id = :id"), {"id": intent_id}
    ).scalar()


def test_opening_the_link_renders_the_page_and_marks_the_intent_opened(client, db_tx) -> None:
    intent_id, token = _intent(db_tx)
    res = client.get(f"/pay/{token}", headers=HEADERS)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/html")
    assert "250" in res.text
    assert _status(db_tx, intent_id) == "opened"


def test_completing_pays_once_and_the_second_click_is_idempotent(client, db_tx) -> None:
    intent_id, token = _intent(db_tx)
    res = client.post(f"/pay/{token}/complete", headers=HEADERS)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "paid"
    assert _status(db_tx, intent_id) == "paid"
    again = client.post(f"/pay/{token}/complete", headers=HEADERS)
    assert again.status_code == 200, again.text
    assert again.json()["idempotent"] is True


def test_a_browser_form_post_gets_the_page_back(client, db_tx) -> None:
    _, token = _intent(db_tx)
    res = client.post(
        f"/pay/{token}/complete",
        headers={**HEADERS, "accept": "text/html"},
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/html")


def test_an_unknown_link_is_404_on_both_routes(client) -> None:
    assert client.get("/pay/no-such-token", headers=HEADERS).status_code == 404
    assert client.post("/pay/no-such-token/complete", headers=HEADERS).status_code == 404


def test_every_response_carries_the_browser_headers_and_the_pay_page_a_csp(client) -> None:
    """A page a borrower opens from an SMS was framable by anyone and its
    token leaked through the referrer. Nosniff, frame-deny and no-referrer
    on every response; the pay page adds a CSP that admits no script (it is
    one form) and is never cached."""
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert "Content-Security-Policy" not in r.headers

    r = client.get("/pay/not-a-real-token")
    assert r.status_code in (404, 410)
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp
    assert r.headers["Cache-Control"] == "no-store"
    assert r.headers["X-Frame-Options"] == "DENY"
