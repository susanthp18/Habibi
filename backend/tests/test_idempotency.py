"""CRM write idempotency — WhatsApp + voice key shapes.

Every voice write tool that can be double-called by the model needs a stable
key. Only ``create_promise_to_pay`` had one; a duplicated ``flag_dispute`` /
``request_callback`` / ``request_documents`` wrote a second row, which for
documents means the same statement generated and delivered twice.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest


def _pick_customer() -> tuple[str, str | None]:
    import db

    customers = db.list_customers()
    if not customers:
        pytest.skip("no customers seeded")
    c = customers[0]
    return c["id"], c.get("accountId") or None


def test_whatsapp_path_double_submit_one_row(db_tx) -> None:
    """Writes go through db_tx so the promise + idempotency_keys rows roll back."""
    import db
    from sqlalchemy import text

    customer_id, account_id = _pick_customer()
    key = f"wa-ptp-test-{uuid.uuid4().hex}"
    promised = (date.today() + timedelta(days=7)).isoformat()
    payload = {
        "customerId": customer_id,
        "accountId": account_id,
        "amount": 101.0,
        "promisedDate": promised,
        "channel": "whatsapp",
        "ownerUserId": "priya-nair" if db.user_exists("priya-nair") else None,
    }
    if not payload["ownerUserId"]:
        pytest.skip("priya-nair required for human-owned PTP")

    before = db_tx.execute(
        text("SELECT count(*) FROM promises WHERE customer_id = :c AND amount = 101"),
        {"c": customer_id},
    ).scalar()
    first = db.create_promise(payload, idempotency_key=key)
    second = db.create_promise(payload, idempotency_key=key)
    assert first["id"] == second["id"]

    n = db_tx.execute(
        text("SELECT count(*) FROM promises WHERE customer_id = :c AND amount = 101"),
        {"c": customer_id},
    ).scalar()
    assert n == before + 1
    assert first["amount"] == 101.0


def test_voice_path_double_submit_one_row(db_tx) -> None:
    """Mirrors voice/tools.py idempotency key shape."""
    import db

    customer_id, account_id = _pick_customer()
    interaction_id = None
    # Prefer an existing interaction for FK honesty; optional for create_promise.
    promised = (date.today() + timedelta(days=5)).isoformat()
    amt = 202.0
    idem = f"voice-ptp:{interaction_id or 'no-ix'}:{customer_id}:{amt:.2f}:{promised}"

    payload = {
        "customerId": customer_id,
        "accountId": account_id,
        "interactionId": interaction_id,
        "amount": amt,
        "promisedDate": promised,
        "channel": "voice",
        "ownerBotId": getattr(db, "DEFAULT_BOT_ID", None),
    }
    if not payload["ownerBotId"]:
        pytest.skip("DEFAULT_BOT_ID missing")

    # Bot must exist
    from sqlalchemy import text

    bot_ok = db_tx.execute(
        text("SELECT 1 FROM bots WHERE id = :id"),
        {"id": payload["ownerBotId"]},
    ).fetchone()
    if not bot_ok:
        pytest.skip(f"bot {payload['ownerBotId']} not present")

    first = db.create_promise(payload, idempotency_key=idem)
    # Deliberately different amount on the replay: a key collision must return
    # the FIRST request's stored response, not silently apply the new payload.
    # Replaying an identical payload proved nothing — it passed even if the
    # second call executed a fresh write.
    second = db.create_promise({**payload, "amount": amt + 50}, idempotency_key=idem)
    assert first["id"] == second["id"]
    assert first["amount"] == amt
    assert second["amount"] == amt


def _row_count(db_tx, table: str, customer_id: str) -> int:
    from sqlalchemy import text

    return db_tx.execute(
        text(f"SELECT count(*) FROM {table} WHERE customer_id = :c"),  # noqa: S608 - literal
        {"c": customer_id},
    ).scalar()


def test_voice_dispute_key_is_stable_across_retries(db_tx) -> None:
    """Mirrors the voice-dispute key shape in voice/tools.py."""
    import db

    customer_id, account_id = _pick_customer()
    idem = f"voice-dispute:no-ix:{customer_id}:paid_already:250.00"
    payload = {
        "customerId": customer_id,
        "accountId": account_id,
        "type": "paid_already",
        "amount": 250.0,
        "priority": "normal",
    }

    before = _row_count(db_tx, "disputes", customer_id)
    first = db.create_dispute(payload, idempotency_key=idem)
    # Different type on the replay: a key hit must return the stored response,
    # not apply the new payload.
    second = db.create_dispute({**payload, "type": "wrong_amount"}, idempotency_key=idem)

    assert first["id"] == second["id"]
    assert _row_count(db_tx, "disputes", customer_id) == before + 1


def test_voice_callback_key_is_stable_across_retries(db_tx) -> None:
    import db

    customer_id, account_id = _pick_customer()
    when = f"{(date.today() + timedelta(days=2)).isoformat()}T10:00:00+05:30"
    idem = f"voice-callback:no-ix:{customer_id}:{when}"
    payload = {
        "customerId": customer_id,
        "accountId": account_id,
        "reason": "general",
        "scheduledAt": when,
        "windowMins": 30,
        "priority": "normal",
    }

    before = _row_count(db_tx, "callbacks", customer_id)
    first = db.create_callback(payload, idempotency_key=idem)
    second = db.create_callback({**payload, "reason": "hardship_review"}, idempotency_key=idem)

    assert first["id"] == second["id"]
    assert _row_count(db_tx, "callbacks", customer_id) == before + 1


def test_voice_document_key_is_stable_across_retries(db_tx) -> None:
    """A duplicate here means the same statement is generated and sent twice."""
    import db

    customer_id, account_id = _pick_customer()
    idem = f"voice-doc:no-ix:{customer_id}:statement:2026-07"
    payload = {
        "customerId": customer_id,
        "accountId": account_id,
        "docType": "statement",
        "period": "2026-07",
        "requestedVia": "bot_voice",
    }

    before = _row_count(db_tx, "document_requests", customer_id)
    first = db.create_document_request(payload, idempotency_key=idem)
    second = db.create_document_request(
        {**payload, "period": "2026-06"}, idempotency_key=idem
    )

    assert first["id"] == second["id"]
    assert _row_count(db_tx, "document_requests", customer_id) == before + 1


def test_writes_without_a_key_are_not_deduplicated(db_tx) -> None:
    """Guard against the fix over-reaching: no key must still mean no dedupe."""
    import db

    customer_id, account_id = _pick_customer()
    payload = {
        "customerId": customer_id,
        "accountId": account_id,
        "type": "wrong_amount",
        "amount": 99.0,
        "priority": "normal",
    }
    first = db.create_dispute(payload)
    second = db.create_dispute(payload)
    assert first["id"] != second["id"]
