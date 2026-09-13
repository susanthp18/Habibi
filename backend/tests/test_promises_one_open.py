"""One open promise per account, renegotiable with a reason and a history.

The borrower who rings to say "salary is late, can I pay on the 20th" is the
ordinary case, not the edge: the promise keeps its id, its reminders and its
pay link, and the change is written down with why. A second promise on an
account that already has one is refused with the open one attached.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

import db
from agent_core import clock


def _customer(db_tx) -> tuple[str, str]:
    row = db_tx.execute(
        text(
            """
            SELECT c.id, a.id AS account_id
            FROM customers c JOIN accounts a ON a.customer_id = c.id
            WHERE c.id <> 'UNKNOWN-CALLER'
              AND NOT EXISTS (SELECT 1 FROM promises p WHERE p.account_id = a.id
                              AND p.status IN ('upcoming','due_today'))
            ORDER BY c.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("no account without an open promise")
    return row["id"], row["account_id"]


def _day(n: int) -> str:
    return (clock.today_local() + timedelta(days=n)).isoformat()


def _local_day(value) -> str:
    """A stored promised_at (ISO string or datetime), as the calendar day the borrower named."""
    from datetime import datetime

    instant = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return clock.as_utc(instant).astimezone(clock.tenant_tz()).date().isoformat()


def _create(customer_id: str, account_id: str, *, amount: float = 500, days: int = 5) -> dict:
    return db.create_promise(
        {"customerId": customer_id, "accountId": account_id, "amount": amount, "promisedDate": _day(days)},
        idempotency_key=f"one-open-{uuid.uuid4().hex}",
    )


def test_a_second_promise_on_an_open_account_is_refused_with_the_open_one(db_tx) -> None:
    customer_id, account_id = _customer(db_tx)
    first = _create(customer_id, account_id)
    with pytest.raises(ValueError, match=f"promise_already_open:{first['id']}"):
        _create(customer_id, account_id, days=9)


def test_two_concurrent_creates_land_one_row(db_real) -> None:
    """The refusal is a read; the unique index is what holds under a race."""
    import threading

    with db_real.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT c.id, a.id AS account_id FROM customers c JOIN accounts a ON a.customer_id = c.id
                WHERE c.id <> 'UNKNOWN-CALLER'
                  AND NOT EXISTS (SELECT 1 FROM promises p WHERE p.account_id = a.id
                                  AND p.status IN ('upcoming','due_today'))
                ORDER BY c.id DESC LIMIT 1
                """
            )
        ).mappings().first()
    if row is None:
        pytest.skip("no account without an open promise")
    customer_id, account_id = row["id"], row["account_id"]
    outcomes: list[str] = []
    gate = threading.Barrier(2)

    def _one():
        gate.wait()
        try:
            db.create_promise(
                {"customerId": customer_id, "accountId": account_id, "amount": 300, "promisedDate": _day(4)},
                idempotency_key=f"race-{uuid.uuid4().hex}",
            )
            outcomes.append("created")
        except Exception as exc:  # ValueError or IntegrityError -- either is a refusal
            outcomes.append(type(exc).__name__)

    threads = [threading.Thread(target=_one) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    try:
        with db_real.connect() as conn:
            n = conn.execute(
                text("SELECT count(*) FROM promises WHERE account_id = :a AND status IN ('upcoming','due_today')"),
                {"a": account_id},
            ).scalar()
        assert n == 1, outcomes
        assert outcomes.count("created") == 1, outcomes
    finally:
        with db_real.begin() as conn:
            conn.execute(text("DELETE FROM promise_reminders WHERE promise_id IN (SELECT id FROM promises WHERE account_id = :a AND created_at > now() - interval '1 minute')"), {"a": account_id})
            conn.execute(text("DELETE FROM payment_intents WHERE promise_id IN (SELECT id FROM promises WHERE account_id = :a AND created_at > now() - interval '1 minute')"), {"a": account_id})
            conn.execute(text("DELETE FROM activity_events WHERE entity_id IN (SELECT id FROM promises WHERE account_id = :a AND created_at > now() - interval '1 minute')"), {"a": account_id})
            conn.execute(text("DELETE FROM promises WHERE account_id = :a AND created_at > now() - interval '1 minute'"), {"a": account_id})


def test_a_revision_moves_the_promise_and_keeps_the_history(db_tx) -> None:
    customer_id, account_id = _customer(db_tx)
    created = _create(customer_id, account_id, amount=500, days=5)
    revised = db.revise_promise(
        created["id"],
        {"promisedDate": _day(12), "amount": 400, "reason": "salary_delayed", "note": "paid on the 10th"},
    )
    assert revised["id"] == created["id"]
    assert revised["revisionCount"] == 1
    assert float(revised["amount"]) == 400
    assert _local_day(revised["promisedDate"]) == _day(12)
    (rev,) = revised["revisions"]
    assert rev["seq"] == 1 and rev["reason"] == "salary_delayed"
    assert float(rev["priorAmount"]) == 500 and _local_day(rev["priorPromisedDate"]) == _day(5)
    assert rev["actorKind"] == "human" and rev["note"] == "paid on the 10th"
    # the pay link followed the promise: its expiry is derived from the new date
    intent = db_tx.execute(
        text("SELECT amount, expires_at FROM payment_intents WHERE promise_id = :id AND status IN ('created','sent','opened')"),
        {"id": created["id"]},
    ).mappings().first()
    if intent is not None:
        assert float(intent["amount"]) == 400
        assert _local_day(intent["expires_at"]) >= _day(12)


def test_the_revision_cap_holds(db_tx) -> None:
    import policy_rules

    customer_id, account_id = _customer(db_tx)
    created = _create(customer_id, account_id, days=3)
    for i in range(policy_rules.PTP_MAX_REVISIONS):
        db.revise_promise(created["id"], {"promisedDate": _day(4 + i), "reason": "customer_requested_delay"})
    with pytest.raises(ValueError, match="promise_revision_cap"):
        db.revise_promise(created["id"], {"promisedDate": _day(20), "reason": "other"})


def test_a_revision_needs_a_reason_and_a_change(db_tx) -> None:
    customer_id, account_id = _customer(db_tx)
    created = _create(customer_id, account_id, days=3)
    with pytest.raises(ValueError, match="invalid_revision_reason"):
        db.revise_promise(created["id"], {"promisedDate": _day(6), "reason": "felt like it"})
    with pytest.raises(ValueError, match="nothing_to_revise"):
        db.revise_promise(created["id"], {"promisedDate": _day(3), "reason": "other"})


def test_cancelling_frees_the_account(db_tx) -> None:
    customer_id, account_id = _customer(db_tx)
    created = _create(customer_id, account_id, days=3)
    cancelled = db.cancel_promise(created["id"], {"reason": "dispute_raised", "note": "charge disputed"})
    assert cancelled["status"] == "cancelled" and cancelled["cancelReason"] == "dispute_raised"
    pending = db_tx.execute(
        text("SELECT count(*) FROM promise_reminders WHERE promise_id = :id AND status IN ('queued','scheduled')"),
        {"id": created["id"]},
    ).scalar()
    assert pending == 0
    # the account can hold a new commitment; the old one cannot be revised
    with pytest.raises(ValueError, match="promise_not_open:cancelled"):
        db.revise_promise(created["id"], {"promisedDate": _day(6), "reason": "other"})
    again = _create(customer_id, account_id, days=8)
    assert again["id"] != created["id"]


def test_a_promise_is_capped_at_what_is_owed(db_tx) -> None:
    """The pay link could only ever collect the outstanding balance; `kept`
    compared against the uncapped figure, so a generous promise could never
    be kept."""
    customer_id, account_id = _customer(db_tx)
    outstanding = db_tx.execute(text("SELECT outstanding FROM accounts WHERE id = :a"), {"a": account_id}).scalar()
    if not outstanding or float(outstanding) <= 0:
        pytest.skip("account has no outstanding balance")
    created = _create(customer_id, account_id, amount=float(outstanding) + 1000, days=3)
    assert float(created["amount"]) == float(outstanding)
    assert created.get("_capped") is True


def test_a_date_is_not_a_patch(db_tx) -> None:
    """`PATCH` settles; a moved date is a renegotiation with a reason."""
    from schemas.payments import PromisePatchRequest

    assert "promisedDate" not in PromisePatchRequest.model_fields
    customer_id, account_id = _customer(db_tx)
    created = _create(customer_id, account_id, days=3)
    with pytest.raises(ValueError, match="illegal_transition:promise:upcoming->cancelled"):
        db.patch_promise(created["id"], {"status": "cancelled"})
