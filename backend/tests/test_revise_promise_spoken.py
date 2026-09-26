"""The revise tool names what moved, and what did not.

VS-8C1B760F1B: the caller asked for ten more days. The open promise was INR
4,000 from an earlier call; only its date moved. The tool said "confirm the
promise now stands at 4000.0 on 2026-10-04" and the agent told the caller
"I've updated your Promise-to-Pay to INR 4,000" -- a figure they had not just
agreed, presented as though they had.
"""

from __future__ import annotations

from agent_core.clock import spoken_date as sd
from agent_core.tools.domain import _revision_spoken


def test_a_date_only_move_says_the_amount_is_unchanged() -> None:
    line = _revision_spoken(
        {"amount": 4000.0, "promisedDate": "2026-09-29"},
        {"amount": 4000.0, "promisedDate": "2026-10-04"},
    )
    assert "existing promise of ₹4,000" in line
    assert f"{sd('2026-09-29')} to {sd('2026-10-04')}" in line
    assert "2026-" not in line, "an ISO date is read to the caller digit by digit"
    assert "amount is unchanged" in line
    assert "4000.0" not in line


def test_an_amount_only_move_names_both_figures() -> None:
    line = _revision_spoken(
        {"amount": 4000.0, "promisedDate": "2026-10-04"},
        {"amount": 4800.0, "promisedDate": "2026-10-04"},
    )
    assert "₹4,800 instead of ₹4,000" in line
    assert f"still due on {sd('2026-10-04')}" in line


def test_both_moving_names_before_and_after() -> None:
    line = _revision_spoken(
        {"amount": 4000.0, "promisedDate": "2026-09-29"},
        {"amount": 4800.0, "promisedDate": "2026-10-04"},
    )
    assert f"from ₹4,000 on {sd('2026-09-29')} to ₹4,800 on {sd('2026-10-04')}" in line


def test_an_unreadable_before_falls_back_to_the_plain_confirmation() -> None:
    line = _revision_spoken({}, {"amount": 4000.0, "promisedDate": "2026-10-04"})
    assert line == f"confirm the promise now stands at ₹4,000 on {sd('2026-10-04')}"


def test_an_unreadable_after_never_invents_a_figure() -> None:
    assert _revision_spoken({"amount": 1.0, "promisedDate": "x"}, {}) == "confirm the promise was moved"


def test_a_spoken_date_is_the_customers_day() -> None:
    """A promise for 4 October is stored as 00:00 IST = 18:30 on the 3rd UTC;
    the outbound briefing used the UTC day and told the agent the 3rd."""
    from datetime import datetime, timezone

    from agent_core.clock import local_day

    stored = datetime(2026, 10, 3, 18, 30, tzinfo=timezone.utc)
    assert local_day(stored).isoformat() == "2026-10-04"
    assert sd("2026-10-04").startswith("Sunday 4 October")
