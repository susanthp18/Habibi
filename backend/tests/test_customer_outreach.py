"""360 outreach creates a thread if missing and reuses the inbox send path."""

from __future__ import annotations

import inspect

from sqlalchemy import text

import db_inbox


def test_outreach_route_reads_the_idempotency_header() -> None:
    from routers import crm, outbound

    assert "idempotency_key" in inspect.signature(crm.send_customer_outreach).parameters
    assert "idempotency_key" in inspect.signature(outbound.treatment_decision_enact).parameters


def test_send_customer_outreach_sms_is_idempotent_and_mocks_no_provider(db_tx, monkeypatch) -> None:
    row = db_tx.execute(
        text(
            """
            SELECT a.customer_id FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE c.phone_primary IS NOT NULL
            ORDER BY a.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        import pytest

        pytest.skip("seed has no customer with a phone")
    cid = row["customer_id"]

    class _Ok:
        allowed = True
        reason = None

    monkeypatch.setattr("contact_policy.require_admit", lambda *a, **k: _Ok())
    sent: list[dict] = []

    def _enqueue(*_a, **kwargs):
        sent.append(kwargs)
        return {"id": "WA-JOB"}

    monkeypatch.setattr("whatsapp_outbound.enqueue_agent_send", _enqueue)

    first = db_inbox.send_customer_outreach(
        cid, {"channel": "sms", "text": "Please call us"}, idempotency_key="outreach-sms-1"
    )
    second = db_inbox.send_customer_outreach(
        cid, {"channel": "sms", "text": "Please call us"}, idempotency_key="outreach-sms-1"
    )
    assert first["channel"] == "sms"
    assert first["conversationId"]
    assert first["messageId"]
    assert second == first
    assert sent == []


def test_send_customer_outreach_whatsapp_enqueues_with_mocked_provider(db_tx, monkeypatch) -> None:
    row = db_tx.execute(
        text(
            """
            SELECT a.customer_id FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE c.phone_primary IS NOT NULL
            ORDER BY a.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        import pytest

        pytest.skip("seed has no customer with a phone")
    cid = row["customer_id"]

    class _Ok:
        allowed = True
        reason = None

    monkeypatch.setattr("contact_policy.require_admit", lambda *a, **k: _Ok())
    sent: list[dict] = []

    def _enqueue(*_a, **kwargs):
        sent.append(kwargs)
        return {"id": "WA-JOB"}

    monkeypatch.setattr("whatsapp_outbound.enqueue_agent_send", _enqueue)

    out = db_inbox.send_customer_outreach(
        cid,
        {"channel": "whatsapp", "text": "Please call us"},
        idempotency_key="outreach-wa-1",
    )
    assert out["channel"] == "whatsapp"
    assert len(sent) == 1
    assert sent[0]["purpose"] == "outreach"
    assert sent[0]["source"] == "customer_outreach"
    replay = db_inbox.send_customer_outreach(
        cid,
        {"channel": "whatsapp", "text": "Please call us"},
        idempotency_key="outreach-wa-1",
    )
    assert replay == out
    assert len(sent) == 1
