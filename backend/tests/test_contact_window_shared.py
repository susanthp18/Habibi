"""One promise date must not get two verdicts.

``db._outside_preferred_window`` and the code-mode script
``promise_date_in_window`` answer the same question — is this moment inside the
customer's contact window — for the same borrower, sometimes within the same
call. The script held its own copy of the rule "so code-mode has no DB import",
and the copy's default drifted: 10:00–19:00 IST against ``db.py``'s 09:00–20:00.

A promise at 09:30 IST for a customer with no ``preferred_window`` on file was
therefore in-window to the callback/DND path and out-of-window to the agent's
own pre-offer check. Which verdict the borrower got depended on which entry
point ran. ``db.py``'s bounds are authoritative: they are what the callback DND
flag has always enforced, and no test pinned the script's.

Both now call :mod:`contact_window`.
"""

from __future__ import annotations

import pytest

import contact_window
import db
from agent_core.skills.scripts import run_script

#: The hour the two copies disagreed about, and the two that bound it.
NINE_THIRTY_IST = "2026-08-21T09:30:00+05:30"
EIGHT_THIRTY_IST = "2026-08-21T08:30:00+05:30"
SEVEN_THIRTY_PM_IST = "2026-08-21T19:30:00+05:30"
EIGHT_PM_IST = "2026-08-21T20:00:00+05:30"


def _script_says_outside(scheduled_at: str, preferred_window: str | None = None) -> bool:
    payload: dict[str, object] = {"promise_date": scheduled_at}
    if preferred_window is not None:
        payload["preferred_window"] = preferred_window
    result = run_script("promise_date_in_window", payload)
    assert result["ok"] is True
    # ``outside`` and ``in_window`` are two faces of the same verdict; a caller
    # reading either one must not be able to reach a different conclusion.
    assert result["outside"] is not result["in_window"]
    return bool(result["outside"])


# --- the boundary the two copies disagreed on -------------------------------


def test_half_past_nine_with_no_preferred_window_gets_one_verdict() -> None:
    """09:30 IST, no window on file. In-window per db.py — and now per the script."""
    assert db._outside_preferred_window(NINE_THIRTY_IST, None) is False
    assert _script_says_outside(NINE_THIRTY_IST) is False


def test_db_default_bounds_are_the_authoritative_ones() -> None:
    assert contact_window.DEFAULT_START_HOUR == 9
    assert contact_window.DEFAULT_END_HOUR == 20
    assert contact_window.DEFAULT_WINDOW == "09:00-20:00 IST"


@pytest.mark.parametrize(
    ("scheduled_at", "outside"),
    [
        (EIGHT_THIRTY_IST, True),  # before 09:00
        (NINE_THIRTY_IST, False),  # the disputed hour
        (SEVEN_THIRTY_PM_IST, False),  # 19:30 — inside per db.py, was outside per the script
        (EIGHT_PM_IST, True),  # 20:00 is the exclusive end
    ],
)
def test_both_entry_points_agree_across_the_default_window(scheduled_at: str, outside: bool) -> None:
    assert db._outside_preferred_window(scheduled_at, None) is outside
    assert _script_says_outside(scheduled_at) is outside


# --- an explicit window still binds, identically on both sides --------------


@pytest.mark.parametrize(
    ("window", "scheduled_at", "outside"),
    [
        ("10:00-19:00 IST", NINE_THIRTY_IST, True),
        ("10:00-19:00 IST", "2026-08-21T12:00:00+05:30", False),
        ("10:00-19:00 IST", "2026-08-21T21:00:00+05:30", True),
        ("10:00–19:00 IST", NINE_THIRTY_IST, True),  # en dash
        ("nonsense", NINE_THIRTY_IST, False),  # unparseable falls back to 09–20
    ],
)
def test_explicit_window_agrees_on_both_sides(window: str, scheduled_at: str, outside: bool) -> None:
    assert db._outside_preferred_window(scheduled_at, window) is outside
    assert _script_says_outside(scheduled_at, window) is outside


def test_a_naive_timestamp_is_read_as_utc_on_both_sides() -> None:
    """04:00Z is 09:30 IST. A window rule that read the UTC hour would flag it."""
    naive = "2026-08-21T04:00:00"
    assert db._outside_preferred_window(naive, None) is False
    assert _script_says_outside(naive) is False


def test_an_unparseable_timestamp_is_not_a_violation() -> None:
    assert db._outside_preferred_window("not-a-date", None) is False
    assert _script_says_outside("not-a-date") is False


# --- the script's public shape is unchanged ---------------------------------


def test_script_echoes_the_window_it_actually_used() -> None:
    result = run_script("promise_date_in_window", {"promise_date": NINE_THIRTY_IST})
    assert result["preferred_window"] == contact_window.DEFAULT_WINDOW
    assert result["promise_date"] == NINE_THIRTY_IST


def test_missing_promise_date_still_reports_the_same_error() -> None:
    assert run_script("promise_date_in_window", {}) == {
        "ok": False,
        "error": "promise_date_required",
    }


def test_contact_window_is_a_leaf_module() -> None:
    """It is importable without ``db``; that is the whole point of the split."""
    import subprocess
    import sys

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import contact_window; "
            "assert 'db' not in sys.modules; "
            "assert 'sqlalchemy' not in sys.modules; "
            "print(contact_window.DEFAULT_WINDOW)",
        ],
        capture_output=True,
        text=True,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == contact_window.DEFAULT_WINDOW
