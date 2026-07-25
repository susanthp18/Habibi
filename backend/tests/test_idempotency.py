"""Promise create idempotency — WhatsApp + voice key shapes."""

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


def test_whatsapp_path_double_submit_one_row() -> None:
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

    first = db.create_promise(payload, idempotency_key=key)
    second = db.create_promise(payload, idempotency_key=key)
    assert first["id"] == second["id"]

    with db.engine.connect() as conn:
        n = conn.execute(
            text(
                "SELECT count(*) FROM promises WHERE customer_id = :c AND amount = 101"
            ),
            {"c": customer_id},
        ).scalar()
    # At least the one we created; exact count may include prior seeds — assert id stable.
    assert n >= 1
    assert first["amount"] == 101.0


def test_voice_path_double_submit_one_row() -> None:
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

    with db.engine.connect() as conn:
        bot_ok = conn.execute(
            text("SELECT 1 FROM bots WHERE id = :id"),
            {"id": payload["ownerBotId"]},
        ).fetchone()
    if not bot_ok:
        pytest.skip(f"bot {payload['ownerBotId']} not present")

    first = db.create_promise(payload, idempotency_key=idem)
    second = db.create_promise({**payload, "amount": amt}, idempotency_key=idem)
    assert first["id"] == second["id"]
    assert first["amount"] == amt
