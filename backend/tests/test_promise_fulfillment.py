"""PTP pay-link fulfillment — intent, consent veto, ledger keep/break."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text


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


def _require_intents(db_tx) -> None:
    row = db_tx.execute(
        text("SELECT to_regclass('public.payment_intents') AS t")
    ).mappings().first()
    if not row or not row["t"]:
        pytest.skip("payment_intents table missing — apply alembic 20260812_0065")


def _opt_out(db_tx, customer_id: str, channels: tuple[str, ...] = ("whatsapp", "sms")) -> None:
    db_tx.execute(
        text(
            """
            UPDATE channel_consents cc
            SET status = 'opted_out', captured_at = now()
            FROM consent_records cr
            WHERE cc.consent_id = cr.id
              AND cr.customer_id = :cid
              AND cc.channel = ANY(:channels)
            """
        ),
        {"cid": customer_id, "channels": list(channels)},
    )


def _create(customer_id: str, account_id: str | None, *, amount: float = 121.0, days: int = 9, key: str | None = None):
    from agent_core.tools import create_promise_to_pay

    promised = (date.today() + timedelta(days=days)).isoformat()
    return create_promise_to_pay(
        customer_id=customer_id,
        amount=amount,
        promised_date=promised,
        account_id=account_id,
        channel="voice",
        idempotency_key=key or f"ptp-test-{uuid.uuid4().hex}",
    )


def test_fulfill_idempotent_one_intent(db_tx) -> None:
    _require_intents(db_tx)
    customer_id, account_id = _customer(db_tx)
    key = f"ptp-idem-{uuid.uuid4().hex}"
    first = _create(customer_id, account_id, key=key)
    second = _create(customer_id, account_id, key=key)
    assert first.ok and second.ok
    assert first.data["promiseId"] == second.data["promiseId"]
    n = db_tx.execute(
        text("SELECT count(*) FROM payment_intents WHERE promise_id = :id"),
        {"id": first.data["promiseId"]},
    ).scalar()
    assert n == 1
    assert "http" not in (first.spoken_summary or "").lower()
    assert "http" not in (second.spoken_summary or "").lower()


def test_voice_double_call_one_intent(db_tx) -> None:
    """Same voice idempotency key as the live handler: one promise, one intent."""
    _require_intents(db_tx)
    customer_id, account_id = _customer(db_tx)
    promised = (date.today() + timedelta(days=5)).isoformat()
    key = f"voice-ptp:IX-TEST:{customer_id}:88.00:{promised}"
    from agent_core.tools import create_promise_to_pay

    a = create_promise_to_pay(
        customer_id=customer_id,
        amount=88.0,
        promised_date=promised,
        account_id=account_id,
        channel="voice",
        idempotency_key=key,
    )
    b = create_promise_to_pay(
        customer_id=customer_id,
        amount=88.0,
        promised_date=promised,
        account_id=account_id,
        channel="voice",
        idempotency_key=key,
    )
    assert a.ok and b.ok
    assert a.data["promiseId"] == b.data["promiseId"]
    n = db_tx.execute(
        text("SELECT count(*) FROM payment_intents WHERE promise_id = :id"),
        {"id": a.data["promiseId"]},
    ).scalar()
    assert n == 1


def test_consent_suppresses_outbound(db_tx) -> None:
    _require_intents(db_tx)
    customer_id, account_id = _customer(db_tx)
    _opt_out(db_tx, customer_id)
    before = db_tx.execute(text("SELECT count(*) FROM whatsapp_outbound_jobs")).scalar() or 0
    result = _create(customer_id, account_id, amount=55.0)
    assert result.ok
    assert result.data.get("suppressed") is True
    assert result.data.get("payLinkSent") is False
    after = db_tx.execute(text("SELECT count(*) FROM whatsapp_outbound_jobs")).scalar() or 0
    assert after == before
    row = db_tx.execute(
        text(
            """
            SELECT suppression_reason, confirm_channel, status
            FROM payment_intents WHERE promise_id = :id
            """
        ),
        {"id": result.data["promiseId"]},
    ).mappings().first()
    assert row is not None
    assert row["suppression_reason"]
    assert row["confirm_channel"] is None
    spoken = (result.spoken_summary or "").lower()
    assert "opted out" in spoken or "could not send" in spoken
    assert "http" not in spoken


def test_record_payment_marks_kept(db_tx) -> None:
    _require_intents(db_tx)
    import payments

    customer_id, account_id = _customer(db_tx)
    result = _create(customer_id, account_id, amount=200.0)
    assert result.ok
    intent = db_tx.execute(
        text("SELECT id, amount FROM payment_intents WHERE promise_id = :id"),
        {"id": result.data["promiseId"]},
    ).mappings().first()
    assert intent is not None
    out = payments.record_payment(db_tx, intent_id=intent["id"], amount=intent["amount"], provider_ref="test-kept")
    assert out["ok"] is True
    row = db_tx.execute(
        text("SELECT status, paid_amount FROM promises WHERE id = :id"),
        {"id": result.data["promiseId"]},
    ).mappings().first()
    assert row["status"] == "kept"
    assert Decimal(str(row["paid_amount"])) >= Decimal(str(intent["amount"]))
    st = db_tx.execute(
        text("SELECT status FROM payment_intents WHERE id = :id"),
        {"id": intent["id"]},
    ).scalar()
    assert st == "paid"


def test_record_payment_partial(db_tx) -> None:
    _require_intents(db_tx)
    import payments

    customer_id, account_id = _customer(db_tx)
    result = _create(customer_id, account_id, amount=400.0)
    intent = db_tx.execute(
        text("SELECT id, amount FROM payment_intents WHERE promise_id = :id"),
        {"id": result.data["promiseId"]},
    ).mappings().first()
    half = float(Decimal(str(intent["amount"])) / 2)
    payments.record_payment(db_tx, intent_id=intent["id"], amount=half, provider_ref="test-partial")
    row = db_tx.execute(
        text("SELECT status, paid_amount FROM promises WHERE id = :id"),
        {"id": result.data["promiseId"]},
    ).mappings().first()
    assert row["status"] == "partial"
    assert float(row["paid_amount"]) == pytest.approx(half)


def test_auto_break_after_due(db_tx) -> None:
    _require_intents(db_tx)
    import db
    import promise_fulfillment

    customer_id, account_id = _customer(db_tx)
    # Created for a real (future) date — the tool refuses a promise that was
    # already past when it was made, since its pay link would expire before the
    # customer could use it. Overdue is a state the row *reaches*, so the
    # UPDATE below back-dates it, which is what this test is actually about.
    result = _create(customer_id, account_id, amount=90.0, days=1)
    assert result.ok
    pid = result.data["promiseId"]
    db_tx.execute(
        text(
            """
            UPDATE promises
            SET promised_at = (((now() AT TIME ZONE 'Asia/Kolkata')::date - 1)::timestamp)
                              AT TIME ZONE 'Asia/Kolkata'
            WHERE id = :id
            """
        ),
        {"id": pid},
    )
    stats = promise_fulfillment.settle_promises(db.engine)
    # settle_promises opens engine.begin(); db_tx patches that to this connection.
    row = db_tx.execute(
        text("SELECT status FROM promises WHERE id = :id"),
        {"id": pid},
    ).mappings().first()
    assert row["status"] == "broken"
    assert stats["broken"] >= 1
    fu = db_tx.execute(
        text("SELECT status FROM followups WHERE promise_id = :id"),
        {"id": pid},
    ).mappings().first()
    assert fu is not None
    assert fu["status"] == "open"


def test_settle_due_today(db_tx) -> None:
    _require_intents(db_tx)
    import db
    import promise_fulfillment

    customer_id, account_id = _customer(db_tx)
    result = _create(customer_id, account_id, amount=70.0, days=0)
    pid = result.data["promiseId"]
    db_tx.execute(
        text(
            """
            UPDATE promises
            SET promised_at = (((now() AT TIME ZONE 'Asia/Kolkata')::date + interval '10 hours'))
                              AT TIME ZONE 'Asia/Kolkata',
                status = 'upcoming'
            WHERE id = :id
            """
        ),
        {"id": pid},
    )
    promise_fulfillment.settle_promises(db.engine)
    row = db_tx.execute(
        text("SELECT status FROM promises WHERE id = :id"),
        {"id": pid},
    ).mappings().first()
    assert row["status"] == "due_today"


def test_patch_kept_requires_payment(db_tx) -> None:
    _require_intents(db_tx)
    import db

    customer_id, account_id = _customer(db_tx)
    result = _create(customer_id, account_id, amount=150.0)
    with pytest.raises(ValueError, match="kept_requires_payment"):
        db.patch_promise(result.data["promiseId"], {"status": "kept"})


def test_webhook_hmac_rejects_bad_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    import payments

    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", "s3cret")
    assert (
        payments.verify_webhook_signature(
            provider_name="hosted",
            raw_body=b'{"amount":1}',
            header="deadbeef",
        )
        is False
    )
    import hashlib
    import hmac

    sig = hmac.new(b"s3cret", b'{"amount":1}', hashlib.sha256).hexdigest()
    assert (
        payments.verify_webhook_signature(
            provider_name="hosted",
            raw_body=b'{"amount":1}',
            header=sig,
        )
        is True
    )
