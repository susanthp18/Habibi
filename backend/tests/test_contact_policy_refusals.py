"""The seven contact-policy refusals that were only members of a set.

Twelve reasons, five asserted as an outcome the engine produces. The other
seven — including ``customer_dnd``, the check that stops the platform calling
someone who told the regulator not to be called — appeared in tests only as
members of ``_DEMO_WAIVABLE_REASONS``. Deleting the branch left the suite green.

``_veto`` takes a plain dict, so four of the seven are unit tests of that
function. Cooling-off, the weekly cap and an unreadable consent table are
decided in ``evaluate`` after ``_veto`` returns, so those three drive
``evaluate`` with the database helpers stubbed out — still no DB, still the
reason the engine emits.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import contact_policy

IST = ZoneInfo("Asia/Kolkata")


def _monday_local(hour: int = 12) -> datetime:
    """A Monday inside the seeded Mon–Sat window. Relative, so it cannot age out."""
    today = datetime.now(IST).date()
    monday = today - timedelta(days=today.isoweekday() - 1)
    return datetime(monday.year, monday.month, monday.day, hour, 0)


def _saturday_local(hour: int = 12) -> datetime:
    monday = _monday_local(hour)
    return monday + timedelta(days=5)


def _inside_the_window() -> datetime:
    """A UTC instant that lands at noon IST — inside RBI's 08:00–19:00.

    ``datetime.now()`` is not a fixture. The two ``evaluate`` tests below took
    the wall clock, so they asserted cooling-off and the weekly cap only
    between 08:00 and 19:00 IST and reported ``outside_calling_hours`` for the
    other thirteen hours of the day. That is the same defect ``_monday_local``
    already exists to avoid for the window tests above — a refusal test has to
    pin the instant it is refusing at, or it is testing the clock.
    """
    return _monday_local(12).replace(tzinfo=IST).astimezone(timezone.utc)


def _borrower(**overrides) -> dict:
    row = {
        "id": "cust-refusals",
        "tenant_id": "t1",
        "dnd": False,
        "timezone": "Asia/Kolkata",
        "preferred_window": None,
        "allowed_days": None,
        "allowed_hours": None,
        "dnd_registry": False,
        "expires_at": None,
    }
    row.update(overrides)
    return row


def _reason(**overrides) -> str | None:
    kwargs = {
        "purpose": "outreach",
        "channel": "whatsapp",
        "customer": _borrower(),
        "status": None,
        "now_local": _monday_local(),
    }
    kwargs.update(overrides)
    return contact_policy._veto(**kwargs)


def _evaluate_outreach(monkeypatch: pytest.MonkeyPatch, **stubs):
    """Drive ``evaluate`` without a connection. Every helper that touches SQL is stubbed."""
    customer = stubs.pop("customer", _borrower())
    status = stubs.pop("status", None)
    last = stubs.pop("last", None)
    today = stubs.pop("today", 0)
    week_n = stubs.pop("week_n", 0)
    weekly = stubs.pop("weekly", 8)
    now = stubs.pop("now", _inside_the_window())
    assert not stubs, f"unexpected stubs: {sorted(stubs)}"

    monkeypatch.setattr(contact_policy, "_load_customer", lambda *_a, **_k: customer)
    monkeypatch.setattr(contact_policy, "_channel_status", lambda *_a, **_k: status)
    monkeypatch.setattr(contact_policy, "_rules_for", lambda *_a, **_k: None)
    monkeypatch.setattr(contact_policy, "_today_count", lambda *_a, **_k: today)
    monkeypatch.setattr(contact_policy, "_last_counted_at", lambda *_a, **_k: last)
    monkeypatch.setattr(contact_policy, "_week_counted", lambda *_a, **_k: week_n)
    monkeypatch.setattr(contact_policy, "_weekly_cap_for", lambda *_a, **_k: weekly)
    return contact_policy.evaluate(
        None,
        customer_id=customer["id"],
        channel="whatsapp",
        purpose="outreach",
        now=now,
    )


def test_a_dnd_borrower_is_refused_as_customer_dnd() -> None:
    assert _reason(customer=_borrower(dnd=True)) == contact_policy.REASON_CUSTOMER_DND


def test_a_registry_flag_is_the_same_refusal_as_customer_dnd() -> None:
    """The gate ORs ``customers.dnd`` with ``consent_records.dnd_registry``."""
    assert (
        _reason(customer=_borrower(dnd_registry=True)) == contact_policy.REASON_CUSTOMER_DND
    )


def test_a_channel_marked_dnd_is_refused_as_channel_dnd() -> None:
    assert _reason(status="dnd") == contact_policy.REASON_CHANNEL_DND


def test_expired_channel_consent_is_refused_as_channel_expired() -> None:
    assert _reason(status="expired") == contact_policy.REASON_EXPIRED


def test_outreach_outside_allowed_hours_is_refused_as_outside_allowed_window() -> None:
    assert (
        _reason(
            customer=_borrower(allowed_hours="11:00-18:00 IST"),
            now_local=_monday_local(hour=10),
        )
        == contact_policy.REASON_WINDOW
    )


def test_outreach_on_a_disallowed_day_is_refused_as_outside_allowed_window() -> None:
    assert (
        _reason(
            customer=_borrower(allowed_days="Mon-Fri"),
            now_local=_saturday_local(),
        )
        == contact_policy.REASON_WINDOW
    )


def test_evaluate_emits_cooling_off_inside_the_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTACT_COOLING_OFF_MINUTES", "120")
    now = _inside_the_window()
    decision = _evaluate_outreach(
        monkeypatch, last=now - timedelta(minutes=30), now=now
    )
    assert decision.allowed is False
    assert decision.reason == contact_policy.REASON_COOLING


def test_evaluate_emits_weekly_cap_before_the_daily_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Daily = 3, weekly already spent: the weekly branch must fire, not the daily."""
    monkeypatch.setenv("CONTACT_COOLING_OFF_MINUTES", "0")
    monkeypatch.setenv("CONTACT_DAILY_CAP", "3")
    decision = _evaluate_outreach(monkeypatch, today=0, week_n=2, weekly=2)
    assert decision.allowed is False
    assert decision.reason == contact_policy.REASON_WEEKLY


def test_evaluate_emits_consent_unreadable_when_the_load_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(_conn, _customer_id):
        raise RuntimeError("consent table is on fire")

    monkeypatch.setattr(contact_policy, "_load_customer", _boom)
    decision = contact_policy.evaluate(
        None,
        customer_id="CUST-UNREADABLE",
        channel="whatsapp",
        purpose="outreach",
    )
    assert decision.allowed is False
    assert decision.reason == contact_policy.REASON_UNREADABLE
