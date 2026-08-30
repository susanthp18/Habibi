"""A dispute's SLA is computed once, on the server, for every screen.

It used to be computed twice. ``db._sla_label`` rounded to whole hours and
carried no tone, and that was what the Customer 360 disputes tab rendered; the
disputes board ignored it and recomputed the countdown in the browser
(``disputes-seed.slaInfo``) to the minute, with a tone. So one dispute, 29
minutes from breach, read "0h 29m left" in amber on the board and "0h left" in
permanent grey-amber on the 360 tab — two screens of the same product
disagreeing about the same row.

These tests pin the single contract: ``sla`` (tone), ``slaLabel`` (display) and
``slaMinutes`` (signed value), identical on both serializers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

import db
import schemas


def _in(**kwargs: float) -> datetime:
    """A due date relative to now — positive is future, negative is overdue."""
    return datetime.now(timezone.utc) + timedelta(**kwargs)


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------


def test_far_future_is_ok() -> None:
    captured = _in(hours=-1)
    sla, label, minutes = db._dispute_sla(_in(hours=47, seconds=30), captured, "new")
    assert sla == "ok"
    assert label == "47h 0m left"
    assert minutes == 47 * 60


def test_last_quarter_of_the_window_is_a_warning() -> None:
    """Just inside the threshold warns; just outside it does not."""
    window = timedelta(hours=48)  # 25% of it is 12h

    due = _in(hours=11, minutes=59)
    inside, _label, _m = db._dispute_sla(due, due - window, "new")
    assert inside == "warn"

    due = _in(hours=12, minutes=1)
    outside, _label, _m = db._dispute_sla(due, due - window, "new")
    assert outside == "ok"


def test_exactly_past_due_is_a_breach() -> None:
    """The moment the due date passes — not an hour later, once rounding agrees."""
    sla, label, minutes = db._dispute_sla(_in(seconds=0), _in(hours=-48), "new")
    assert sla == "breach"
    assert label == "0h 0m over"
    assert minutes == 0


def test_overdue_is_reported_to_the_minute() -> None:
    """The old hour-rounded label called 40 minutes late "1h overdue"."""
    sla, label, minutes = db._dispute_sla(_in(minutes=-40, seconds=-30), _in(hours=-48), "new")
    assert (sla, label) == ("breach", "0h 40m over")
    assert minutes == -40


def test_the_last_half_hour_is_not_reported_as_zero() -> None:
    """The regression this contract exists for: "0h left" for 29 minutes."""
    _sla, label, minutes = db._dispute_sla(_in(minutes=29, seconds=30), _in(hours=-48), "new")
    assert label == "0h 29m left"
    assert minutes == 29


@pytest.mark.parametrize("status", ["resolved", "rejected"])
def test_a_closed_dispute_has_no_countdown(status: str) -> None:
    assert db._dispute_sla(_in(hours=-9), _in(hours=-48), status) == ("done", "Closed", 0)


def test_no_due_date_is_open_rather_than_instantly_breached() -> None:
    assert db._dispute_sla(None, _in(hours=-48), "new") == ("ok", "Open", 0)


# ---------------------------------------------------------------------------
# The serializers
# ---------------------------------------------------------------------------


# (suffix, created offset hours, due offset, expected tone, expected label)
_ROWS = [
    ("warn", -2, timedelta(minutes=29, seconds=30), "warn", "0h 29m left"),
    ("breach", -3, timedelta(minutes=-40, seconds=-30), "breach", "0h 40m over"),
    ("ok", -1, timedelta(hours=47, seconds=30), "ok", "47h 0m left"),
]


def _seed_disputes(db_tx) -> tuple[str, dict[str, tuple[str, str]]]:
    """Three disputes on one visible customer: at risk, breached, comfortable."""
    customers = db.list_customers(limit=50)
    if not customers:
        pytest.skip("no customers seeded")
    row = None
    for candidate in customers:
        row = db_tx.execute(
            text("SELECT id FROM accounts WHERE customer_id = :cid LIMIT 1"),
            {"cid": candidate["id"]},
        ).mappings().first()
        if row:
            customer_id, account_id = candidate["id"], row["id"]
            break
    else:
        pytest.skip("no customer with an account")

    now = datetime.now(timezone.utc)
    expected: dict[str, tuple[str, str]] = {}
    for suffix, created_hours, due_delta, tone, label in _ROWS:
        dispute_id = f"DSP-SLATEST-{suffix.upper()}"
        db_tx.execute(
            text(
                """
                INSERT INTO disputes
                  (id, customer_id, account_id, type, disputed_amount, source,
                   status, priority, transcript_snippet, sla_due_at, created_at)
                VALUES
                  (:id, :customer_id, :account_id, 'wrong_amount', 250, 'agent',
                   'new', 'normal', 'SLA fixture', :due, :created)
                """
            ),
            {
                "id": dispute_id,
                "customer_id": customer_id,
                "account_id": account_id,
                "due": now + due_delta,
                "created": now + timedelta(hours=created_hours),
            },
        )
        expected[dispute_id] = (tone, label)
    return customer_id, expected


def test_the_queue_feed_carries_the_structured_sla(db_tx) -> None:
    _customer_id, expected = _seed_disputes(db_tx)
    board = {d["id"]: d for d in db.list_disputes(limit=db.MAX_LIST_LIMIT)}
    for dispute_id, (tone, label) in expected.items():
        got = board[dispute_id]
        assert (got["sla"], got["slaLabel"]) == (tone, label), dispute_id
        assert isinstance(got["slaMinutes"], int)


def test_the_customer_360_tab_carries_the_same_structured_sla(db_tx) -> None:
    customer_id, expected = _seed_disputes(db_tx)
    tab = {d["id"]: d for d in db._dispute_contracts(db_tx, customer_id)}
    for dispute_id, (tone, label) in expected.items():
        got = tab[dispute_id]
        assert (got["sla"], got["slaLabel"]) == (tone, label), dispute_id
        assert isinstance(got["slaMinutes"], int)


def test_both_screens_say_the_same_words_about_the_same_dispute(db_tx) -> None:
    """The bug, stated as a test: board text == 360 text, per dispute."""
    customer_id, expected = _seed_disputes(db_tx)
    board = {d["id"]: d for d in db.list_disputes(limit=db.MAX_LIST_LIMIT)}
    tab = {d["id"]: d for d in db._dispute_contracts(db_tx, customer_id)}
    for dispute_id in expected:
        assert dispute_id in board and dispute_id in tab
        for field in ("sla", "slaLabel", "slaMinutes"):
            assert board[dispute_id][field] == tab[dispute_id][field], f"{dispute_id}.{field}"


def test_the_response_models_accept_the_new_fields(db_tx) -> None:
    """DisputeListResponse forbids extras — the payload must be declared."""
    customer_id, expected = _seed_disputes(db_tx)
    for item in db.list_disputes(limit=db.MAX_LIST_LIMIT):
        if item["id"] in expected:
            schemas.DisputeListResponse.model_validate(item)
    for item in db._dispute_contracts(db_tx, customer_id):
        if item["id"] in expected:
            assert schemas.DisputeResponse.model_validate(item).sla in {
                "ok",
                "warn",
                "breach",
                "done",
            }
