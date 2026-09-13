"""What the borrower is told is re-derived from the live record.

One message actually sent, from the live table::

    "We've recorded your promise to pay ₹4,800 by 28 Aug 2026.
     Pay securely here: … This link is valid until 23 Aug 2026, 11:59 PM IST."

A payment link that dies five days before the money is due, in a sentence that
contradicts itself. `_confirm_copy` reads the date off the *promise* and the
expiry off the *intent*, and the two records had stopped agreeing: the promise
was rescheduled from 22 to 28 August, and `create_pay_intent`'s reuse path did
`return dict(existing)` — discarding the `amount` and `expires_at` its caller
had just computed correctly from the live promise.

    PI-E71780FF85  promise PTP-SUSANTH-1  promised_at 2026-08-28
                                          expires_at  2026-08-23

Nothing else in the tree ever updated those columns, and `patch_promise` — the
only path that moves `promised_at` — never re-entered fulfilment at all.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal


import promise_fulfillment as pf


class _Conn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):  # noqa: ANN001
        self.calls.append((str(getattr(stmt, "text", stmt)), dict(params or {})))
        return None

    def sql(self) -> str:
        return " ".join(s for s, _ in self.calls)


def _intent(amount="4800.00", expires=datetime(2026, 8, 23, 18, 29, 59, tzinfo=timezone.utc)):
    return {
        "id": "PI-TEST",
        "amount": Decimal(str(amount)),
        "expires_at": expires,
        "pay_url": "https://pay.example/x",
        "status": "sent",
    }


# ---------------------------------------------------------------------------
# Reuse re-derives
# ---------------------------------------------------------------------------


def test_a_rescheduled_promise_moves_the_links_expiry() -> None:
    """The exact shape of PI-E71780FF85."""
    conn = _Conn()
    new_expiry = datetime(2026, 8, 29, 18, 29, 59, tzinfo=timezone.utc)
    row = pf._refreshed(
        conn, _intent(), amount=Decimal("4800.00"), expires_at=new_expiry
    )
    assert row["expires_at"] == new_expiry
    assert "UPDATE payment_intents" in conn.sql()
    assert "expires_at = :expires_at" in conn.sql()


def test_a_changed_amount_is_re_derived_too() -> None:
    """`_get_or_create_intent` clamps the amount to the live outstanding."""
    conn = _Conn()
    row = pf._refreshed(
        conn, _intent(), amount=Decimal("3200.00"),
        expires_at=_intent()["expires_at"],
    )
    assert row["amount"] == Decimal("3200.00")
    assert "amount = :amount" in conn.sql()


def test_an_unchanged_intent_is_not_rewritten() -> None:
    """Reuse is the common case; it must not churn a row every send."""
    conn = _Conn()
    existing = _intent()
    row = pf._refreshed(
        conn, existing, amount=existing["amount"], expires_at=existing["expires_at"]
    )
    assert conn.calls == []
    assert row["id"] == "PI-TEST"


def test_the_pay_url_is_never_rotated_on_reuse() -> None:
    """The borrower may already be holding this link."""
    conn = _Conn()
    row = pf._refreshed(
        conn, _intent(), amount=Decimal("1.00"),
        expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )
    assert row["pay_url"] == "https://pay.example/x"
    assert "public_token" not in conn.sql()
    assert "pay_url" not in conn.sql()


def test_every_reuse_path_goes_through_the_refresher() -> None:
    """Three of them: by promise, by payment event, and the raced insert."""
    import inspect

    src = inspect.getsource(pf.create_pay_intent)
    assert src.count("_refreshed(conn") == 3
    assert "return dict(existing)" not in src
    assert "return dict(raced)" not in src


# ---------------------------------------------------------------------------
# The copy the borrower reads cannot contradict itself
# ---------------------------------------------------------------------------


def test_the_confirm_copy_is_internally_consistent_after_a_refresh() -> None:
    promised_at = datetime(2026, 8, 28, 11, 0, tzinfo=timezone.utc)
    expires = pf._intent_expiry(promised_at, now=datetime(2026, 8, 20, tzinfo=timezone.utc))
    body = pf._confirm_copy(
        amount=Decimal("4800.00"), promised_at=promised_at,
        pay_url="https://pay.example/x", expires_at=expires,
    )
    assert "28 Aug 2026" in body
    # The link must outlive the date it is asking to be paid by.
    assert expires > promised_at, body


def test_a_revision_re_enters_fulfilment(db_tx) -> None:
    """Moving the date moves what the pay link has to say: the open intent's
    expiry is re-derived from the new promise date, not left at the old one.
    (Was a source pin on patch_promise; the date now moves through revise.)"""
    import uuid
    from datetime import timedelta

    import db
    import pytest
    from agent_core import clock
    from sqlalchemy import text

    row = db_tx.execute(
        text(
            """
            SELECT c.id, a.id AS account_id FROM customers c JOIN accounts a ON a.customer_id = c.id
            WHERE c.id <> 'UNKNOWN-CALLER'
              AND NOT EXISTS (SELECT 1 FROM promises p WHERE p.account_id = a.id
                              AND p.status IN ('upcoming','due_today'))
            ORDER BY c.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("no account without an open promise")
    day = lambda n: (clock.today_local() + timedelta(days=n)).isoformat()  # noqa: E731
    created = db.create_promise(
        {"customerId": row["id"], "accountId": row["account_id"], "amount": 300, "promisedDate": day(4)},
        idempotency_key=f"refulfil-{uuid.uuid4().hex}",
    )
    before = db_tx.execute(
        text("SELECT expires_at FROM payment_intents WHERE promise_id = :id AND status IN ('created','sent','opened')"),
        {"id": created["id"]},
    ).scalar()
    if before is None:
        pytest.skip("no pay intent minted (payments not configured)")
    db.revise_promise(created["id"], {"promisedDate": day(14), "reason": "salary_delayed"})
    after = db_tx.execute(
        text("SELECT expires_at FROM payment_intents WHERE promise_id = :id AND status IN ('created','sent','opened')"),
        {"id": created["id"]},
    ).scalar()
    assert after is not None and after > before


# ---------------------------------------------------------------------------
# A dead link is not sent
# ---------------------------------------------------------------------------


def test_the_reminder_drain_refuses_an_expired_intent() -> None:
    """It read the latest intent with no OPEN_INTENT filter, unlike every
    other read of this table, so the expiry sweep could hand it a dead URL to
    quote alongside a validity date that had already passed."""
    import inspect

    src = inspect.getsource(pf)
    marker = 'return {"outcome": "failed", "reason": "intent_not_found"}'
    after = src[src.index(marker):]
    assert "intent[\"status\"] not in OPEN_INTENT" in after[:600]


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def test_falling_back_to_a_generic_template_is_never_silent(monkeypatch, caplog) -> None:
    """This deployment's fallback is Meta's sample grocery-order template.

    Meta validates the parameter count, so arity is guarded for us. The body
    text is not: a template registered for something else sends cleanly and says
    the wrong thing to a borrower.
    """
    import logging

    monkeypatch.delenv("WHATSAPP_PTP_TEMPLATE_NAME", raising=False)
    monkeypatch.setenv("WHATSAPP_FALLBACK_TEMPLATE_NAME", "jaspers_market_order_confirmation_v1")
    # Named logger, not the root: `caplog.at_level(WARNING)` alone relies on
    # propagation still being intact, and an earlier test in the same session
    # can leave it otherwise. This failed in a full run and passed in isolation,
    # which is the signature.
    caplog.set_level(logging.WARNING, logger=pf.logger.name)
    caplog.clear()
    name, lang = pf.resolve_template("WHATSAPP_PTP_TEMPLATE_NAME", "WHATSAPP_PTP_TEMPLATE_LANG")
    assert name == "jaspers_market_order_confirmation_v1"
    warned = [r for r in caplog.records if "fallback in use" in (r.message or "")]
    assert warned, "an operator must not have to guess that a fallback was used"
    # getMessage(), not args: once observability's redacting filter is on the
    # handler (any earlier test that set logging up), it renders the message
    # and clears args, which is what made this pass alone and fail in a run.
    assert any("WHATSAPP_PTP_TEMPLATE_NAME" in r.getMessage() for r in warned)


def test_a_purpose_template_is_used_without_complaint(monkeypatch, caplog) -> None:
    import logging

    monkeypatch.setenv("WHATSAPP_PTP_TEMPLATE_NAME", "hdfc_ptp_confirm_v1")
    caplog.set_level(logging.WARNING, logger=pf.logger.name)
    caplog.clear()
    name, _ = pf.resolve_template("WHATSAPP_PTP_TEMPLATE_NAME", "WHATSAPP_PTP_TEMPLATE_LANG")
    assert name == "hdfc_ptp_confirm_v1"
    assert not [r for r in caplog.records if "fallback in use" in (r.message or "")]


# ---------------------------------------------------------------------------
# A job that says it succeeded, did
# ---------------------------------------------------------------------------


def test_a_provider_rejection_moves_the_job_off_succeeded() -> None:
    """WAO-14F8282BF6AC reads `succeeded` while carrying
    "code=131047 … Message failed to send", and its message row reads `failed`.
    Anything counting job status over-reported delivery."""
    import inspect
    import db_whatsapp

    src = inspect.getsource(db_whatsapp._apply_whatsapp_status)
    assert "status = CASE WHEN status = 'succeeded' THEN 'failed' ELSE status END" in src
