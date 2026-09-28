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

#: The hour the two copies disagreed about, and the two that bound it.
NINE_THIRTY_IST = "2026-08-21T09:30:00+05:30"
EIGHT_THIRTY_IST = "2026-08-21T08:30:00+05:30"
SEVEN_THIRTY_PM_IST = "2026-08-21T19:30:00+05:30"
EIGHT_PM_IST = "2026-08-21T20:00:00+05:30"


# --- the boundary the two copies disagreed on -------------------------------


def test_db_default_bounds_are_the_authoritative_ones() -> None:
    assert contact_window.DEFAULT_START_HOUR == 9
    assert contact_window.DEFAULT_END_HOUR == 20
    assert contact_window.DEFAULT_WINDOW == "09:00-20:00 IST"


# --- an explicit window still binds, identically on both sides --------------


# --- the script's public shape is unchanged ---------------------------------


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
