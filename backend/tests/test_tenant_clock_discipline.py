"""Today is a tenant fact, not a process fact.

Every container here runs UTC. The customers are in Asia/Kolkata. Between
18:30 and 24:00 UTC those two calendars disagree by a day, so anything that
reckons "today" from the process zone is correct only for the other 18½ hours.

That is not hypothetical. ``tests/test_conversation_trace_regressions.py``
asserted ``_promise_date_is_past(date.today().isoformat()) is False`` while the
guard it tests reckons the day in the tenant's zone, so CI went red for 5½
hours a day, on code that was correct. Eight further sites built promise dates
from ``date.today()`` and were saved only by a two-day margin — a caller
changing ``days=2`` to ``days=0`` would have reopened it.

``agent_core.clock.today_local()`` is the single answer. It follows
``APP_TIMEZONE`` rather than hardcoding IST, which matters because the guard
does too: pinning the tests to ``ZoneInfo("Asia/Kolkata")`` would have
reintroduced exactly this bug the day that variable is set.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from agent_core import clock
from agent_core.tools import domain

TESTS = Path(__file__).resolve().parent

#: ``date.today()`` is legitimate here: it scans *source literals* for
#: approaching expiry on a 30-day window, which is a fact about the repository's
#: calendar rather than about a borrower's day. A one-day skew cannot flip it.
_PROCESS_CLOCK_ALLOWED = {"test_dated_constants.py", Path(__file__).name}


def test_the_promise_guard_reckons_today_on_the_tenant_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the disagreement itself, not the hour the suite happens to run at.

    01:00 IST on the 5th is 19:30 UTC on the 4th. A guard reading the process
    clock calls the 5th "tomorrow" and the 4th "today"; a guard reading the
    tenant clock calls the 5th "today" and the 4th "yesterday". Only the second
    matches what the borrower was told.
    """
    ist_early_hours = datetime(2026, 9, 5, 1, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert ist_early_hours.astimezone(ZoneInfo("UTC")).date() == date(2026, 9, 4)
    monkeypatch.setattr(clock, "now_local", lambda: ist_early_hours)

    assert domain._promise_date_is_past("2026-09-05") is False, "today is a real promise"
    assert domain._promise_date_is_past("2026-09-06") is False
    assert domain._promise_date_is_past("2026-09-04") is True, "yesterday, tenant-side"


def test_today_local_follows_app_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not hardcoded IST. The guard honours APP_TIMEZONE, so the tests must too."""
    monkeypatch.setenv("APP_TIMEZONE", "Pacific/Kiritimati")  # UTC+14, the far edge
    assert clock.today_local() == datetime.now(ZoneInfo("Pacific/Kiritimati")).date()

    monkeypatch.setenv("APP_TIMEZONE", "Pacific/Niue")  # UTC-11, the other one
    assert clock.today_local() == datetime.now(ZoneInfo("Pacific/Niue")).date()


def test_no_test_reckons_today_from_the_process_clock() -> None:
    """A source pin, deliberately: it is a claim about the suite, not behaviour.

    The failure this prevents is silent for 18½ hours a day, which is exactly
    the kind nobody catches by running the suite once.
    """
    offenders: list[str] = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name in _PROCESS_CLOCK_ALLOWED:
            continue
        if "date.today()" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)

    assert not offenders, (
        "these tests reckon 'today' in the process zone (UTC in every container) "
        "while the code they exercise reckons it in the tenant's: "
        + ", ".join(offenders)
        + " — use agent_core.clock.today_local()"
    )
