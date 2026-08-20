"""Where the authority matrix meets the rest of the product.

The matrix on its own is a function that returns a rupee ceiling. What makes
it a feature is that the bot, the specialist desk, Handoff and the ledger all
consult the same one — and that shadow mode never posts a rupee.
"""

from __future__ import annotations

import secrets

import pytest
from sqlalchemy import text

import db

TENANT = "hdfc.retail"


@pytest.fixture
def customer(db_tx):
    row = db_tx.execute(
        text(
            """
            SELECT a.id AS account_id, a.customer_id, a.outstanding
            FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE c.tenant_id = :t
              AND a.dpd BETWEEN 1 AND 30
            ORDER BY a.id LIMIT 1
            """
        ),
        {"t": TENANT},
    ).mappings().first()
    if row is None:
        pytest.skip("seed has no early-bucket account")
    return dict(row)


def _prepare_eligible(conn, customer: dict) -> None:
    conn.execute(
        text(
            """
            UPDATE accounts
            SET dpd = 12,
                outstanding = 25000,
                opened_on = now() - interval '18 months'
            WHERE id = :id
            """
        ),
        {"id": customer["account_id"]},
    )
    conn.execute(
        text("DELETE FROM ledger_entries WHERE account_id = :id AND type = 'waiver'"),
        {"id": customer["account_id"]},
    )
    conn.execute(
        text(
            """
            DELETE FROM treatment_holds
            WHERE customer_id = :cid AND released_at IS NULL
            """
        ),
        {"cid": customer["customer_id"]},
    )
    conn.execute(
        text(
            """
            INSERT INTO ledger_entries (id, account_id, type, description, amount, posted_at)
            VALUES (:id, :aid, 'fee', 'Late fee', 800, now())
            """
        ),
        {"id": f"LED-AUTH-{secrets.token_hex(4).upper()}", "aid": customer["account_id"]},
    )


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    import actor_context
    import main as app_main

    monkeypatch.setenv("API_KEY", "authority-test-key")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    actor_context.reload_api_key_map()
    return TestClient(app_main.app)


HEADERS = {"X-API-Key": "authority-test-key", "X-Actor-User-Id": "priya-nair"}


def _ledger_waivers(conn, account_id: str) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            text(
                """
                SELECT id, amount, description
                FROM ledger_entries
                WHERE account_id = :aid AND type = 'waiver'
                ORDER BY posted_at
                """
            ),
            {"aid": account_id},
        ).mappings().all()
    ]


def test_shadow_mode_decides_and_does_not_post(db_tx, customer, monkeypatch) -> None:
    monkeypatch.setenv("AUTHORITY_MODE", "shadow")
    _prepare_eligible(db_tx, customer)
    from agent_core.authority import recommend_authority
    from agent_core.authority.enact import AuthorityError, apply_goodwill

    result = recommend_authority(
        customer_id=customer["customer_id"],
        account_id=customer["account_id"],
        asked_amount=400,
        conn=db_tx,
    )
    assert result.verdict == "auto_approve"
    assert result.approved_amount == 400
    assert result.decision_id
    assert result.actionable is False
    assert not _ledger_waivers(db_tx, customer["account_id"])

    with pytest.raises(AuthorityError, match="shadow_mode"):
        apply_goodwill(decision_id=result.decision_id, conn=db_tx)
    assert not _ledger_waivers(db_tx, customer["account_id"])


def test_live_apply_posts_ledger_and_resolves_a_dispute(db_tx, customer, monkeypatch) -> None:
    monkeypatch.setenv("AUTHORITY_MODE", "live")
    _prepare_eligible(db_tx, customer)
    from agent_core.authority import recommend_authority
    from agent_core.authority.enact import apply_goodwill

    before = float(
        db_tx.execute(
            text("SELECT outstanding FROM accounts WHERE id = :id"),
            {"id": customer["account_id"]},
        ).scalar()
        or 0
    )
    result = recommend_authority(
        customer_id=customer["customer_id"],
        account_id=customer["account_id"],
        asked_amount=400,
        conn=db_tx,
    )
    assert result.actionable is True
    posted = apply_goodwill(decision_id=result.decision_id, amount=400, conn=db_tx)
    assert posted["amount"] == 400
    waivers = _ledger_waivers(db_tx, customer["account_id"])
    assert len(waivers) == 1
    assert float(waivers[0]["amount"]) == -400
    after = float(
        db_tx.execute(
            text("SELECT outstanding FROM accounts WHERE id = :id"),
            {"id": customer["account_id"]},
        ).scalar()
        or 0
    )
    assert after == pytest.approx(before - 400)
    dispute_status = db_tx.execute(
        text("SELECT status, resolution_code FROM disputes WHERE id = :id"),
        {"id": posted["disputeId"]},
    ).mappings().first()
    assert dispute_status["status"] == "resolved"
    assert dispute_status["resolution_code"] == "valid_waive_fee"

    from agent_core.authority.enact import AuthorityError

    with pytest.raises(AuthorityError, match="already_applied"):
        apply_goodwill(decision_id=result.decision_id, conn=db_tx)
    assert len(_ledger_waivers(db_tx, customer["account_id"])) == 1


def test_apply_refuses_an_amount_above_the_cap(db_tx, customer, monkeypatch) -> None:
    monkeypatch.setenv("AUTHORITY_MODE", "live")
    _prepare_eligible(db_tx, customer)
    from agent_core.authority import recommend_authority
    from agent_core.authority.enact import AuthorityError, apply_goodwill

    result = recommend_authority(
        customer_id=customer["customer_id"],
        account_id=customer["account_id"],
        asked_amount=400,
        conn=db_tx,
    )
    with pytest.raises(AuthorityError, match="amount_above_cap"):
        apply_goodwill(decision_id=result.decision_id, amount=2000, conn=db_tx)
    assert not _ledger_waivers(db_tx, customer["account_id"])


def test_specialist_valid_waive_fee_posts_the_ledger(db_tx, customer) -> None:
    _prepare_eligible(db_tx, customer)
    dispute = db.create_dispute(
        {
            "customerId": customer["customer_id"],
            "accountId": customer["account_id"],
            "type": "fee_waiver",
            "amount": 350,
        }
    )
    db.patch_dispute(
        dispute["id"],
        {"status": "resolved", "resolutionCode": "valid_waive_fee"},
    )
    waivers = _ledger_waivers(db_tx, customer["account_id"])
    assert len(waivers) == 1
    assert float(waivers[0]["amount"]) == -350
    assert dispute["id"] in (waivers[0]["description"] or "")

    db.patch_dispute(
        dispute["id"],
        {"status": "resolved", "resolutionCode": "valid_waive_fee"},
    )
    assert len(_ledger_waivers(db_tx, customer["account_id"])) == 1


def test_next_endpoint_logs_a_shadow_decision(db_tx, customer, client, monkeypatch) -> None:
    monkeypatch.setenv("AUTHORITY_MODE", "shadow")
    _prepare_eligible(db_tx, customer)
    res = client.get(
        "/authority/next",
        params={
            "customerId": customer["customer_id"],
            "accountId": customer["account_id"],
            "askedAmount": 400,
        },
        headers=HEADERS,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["verdict"] == "auto_approve"
    assert body["approvedAmount"] == 400
    assert body["suppressed"] is True
    assert body["decisionId"]


def test_apply_endpoint_refuses_shadow(db_tx, customer, client, monkeypatch) -> None:
    monkeypatch.setenv("AUTHORITY_MODE", "shadow")
    _prepare_eligible(db_tx, customer)
    from agent_core.authority import recommend_authority

    result = recommend_authority(
        customer_id=customer["customer_id"],
        account_id=customer["account_id"],
        asked_amount=400,
        conn=db_tx,
    )
    res = client.post(
        "/authority/apply",
        json={"decisionId": result.decision_id},
        headers=HEADERS,
    )
    assert res.status_code == 409
    assert "shadow_mode" in res.text
    assert not _ledger_waivers(db_tx, customer["account_id"])
