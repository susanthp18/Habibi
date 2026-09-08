"""One parser, one default, one DND definition.

Four work packages, all the same shape: a rule the contact Gate enforces had a
second copy somewhere in ``db.py``, and the copy answered differently.

* ``WP-030`` — ``db._parse_allowed_days`` did not normalise the dash, so a
  borrower whose consent reads ``Mon–Sat`` was six days to the Gate and Monday
  alone to every screen and comparison reading through ``db.py``.
* ``WP-029`` — the fallback window was ``10:00-19:00 IST`` in ``db.py`` and
  ``schemas.py`` against ``09:00-20:00 IST`` in ``contact_window``. One of those
  fed a DND verdict.
* ``WP-027`` — ``_callback_dnd_active`` read ``customers.dnd`` only, while
  ``contact_policy.admit`` and the consent screen OR it with
  ``consent_records.dnd_registry``. A registry-flagged borrower was refused by
  the Gate and shown as callable on the callback board.
* ``WP-033`` — ``_preferred_hours`` returns ``None`` for "nothing recorded", and
  the outreach check read ``None`` as "skip". A borrower with neither column had
  no hour bound at all on WhatsApp, SMS and email.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

import contact_policy
import contact_window
import db
import schemas

IST = timezone(timedelta(hours=5, minutes=30))


# --- WP-030: one allowed-days parser ----------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Mon-Sat", [1, 2, 3, 4, 5, 6]),
        ("Mon–Sat", [1, 2, 3, 4, 5, 6]),  # en-dash: the one that used to break
        ("Mon—Sat", [1, 2, 3, 4, 5, 6]),  # em-dash
        ("Sat-Mon", [6, 0, 1]),  # wrap-around must survive the consolidation
        ("Mon, Wed, Fri", [1, 3, 5]),
    ],
)
def test_both_paths_read_a_consent_window_the_same_way(raw: str, expected: list[int]) -> None:
    """``Mon–Sat`` is six days to the Gate and to db.py, not six and one."""
    assert contact_window.allowed_days(raw) == expected
    assert contact_policy._parse_days(raw) == expected
    assert db._parse_allowed_days(raw) == expected


def test_the_two_empty_defaults_stay_different_on_purpose() -> None:
    """Consolidating the parser must not quietly merge two product decisions.

    The Gate treats absent days as "no day restriction to apply"; the CRM screen
    substitutes Mon-Fri because that is the claim it makes to an operator. Both
    are defensible and they are not the same claim, so the substitution lives at
    the call site where it can be seen.
    """
    for blank in ("", "   ", None):
        assert contact_window.allowed_days(blank) is None
        assert contact_policy._parse_days(blank) is None
        assert db._parse_allowed_days(blank) == [1, 2, 3, 4, 5]


def test_an_unrecognisable_day_string_is_not_silently_a_week() -> None:
    assert contact_window.allowed_days("whenever") is None
    assert db._parse_allowed_days("whenever") == [1, 2, 3, 4, 5]


# --- WP-029: one preferred-window default -----------------------------------


def test_one_fallback_window_everywhere() -> None:
    """The console showed one window while the veto enforced another."""
    assert contact_window.DEFAULT_WINDOW == "09:00-20:00 IST"
    assert schemas.ContactResponse().preferredWindow == contact_window.DEFAULT_WINDOW
    assert contact_window.window_hours(None) == (
        contact_window.DEFAULT_START_HOUR,
        contact_window.DEFAULT_END_HOUR,
    )


def test_the_statutory_window_is_not_the_preference_window() -> None:
    """The trap this band must not fall into.

    RBI 08:00-19:00 is statutory and applies to voice. 09:00-20:00 is what a
    borrower with nothing on file is assumed to allow. A 19:30 contact is
    in-preference and out-of-statute; collapsing them into one number would be
    the worst available outcome, so this pins that they are different.
    """
    assert (contact_policy.RBI_VOICE_START, contact_policy.RBI_VOICE_END) == (8, 19)
    assert (contact_window.DEFAULT_START_HOUR, contact_window.DEFAULT_END_HOUR) == (9, 20)
    assert (contact_policy.RBI_VOICE_START, contact_policy.RBI_VOICE_END) != (
        contact_window.DEFAULT_START_HOUR,
        contact_window.DEFAULT_END_HOUR,
    )


# --- WP-027: one DND definition ---------------------------------------------


def test_either_dnd_store_blocks_the_callback_slot() -> None:
    """The registry flag alone used to leave the board saying "callable"."""
    in_window = "2026-09-07T12:00:00+05:30"  # a Monday, inside 09:00-20:00
    assert db._callback_dnd_active(False, False, contact_window.DEFAULT_WINDOW, in_window) is False
    assert db._callback_dnd_active(True, False, contact_window.DEFAULT_WINDOW, in_window) is True
    assert db._callback_dnd_active(False, True, contact_window.DEFAULT_WINDOW, in_window) is True
    assert db._callback_dnd_active(True, True, contact_window.DEFAULT_WINDOW, in_window) is True


def test_the_registry_flag_reaches_the_callback_board(db_tx) -> None:
    """The acceptance criterion, end to end rather than on the helper.

    dnd_registry = true with customers.dnd = false must come back as
    ``dndActive`` from the same query the board renders. Before the join was
    added, the query could not see the registry column at all, so this was
    structurally impossible rather than merely wrong.
    """
    row = db_tx.execute(
        text(
            """
            SELECT cb.id, cb.customer_id
            FROM callbacks cb
            JOIN customers c ON c.id = cb.customer_id
            JOIN consent_records cr ON cr.customer_id = cb.customer_id
            ORDER BY cb.id
            LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("no seeded callback with a consent record")

    # Inside the window and with the operator flag down, so the registry is the
    # only thing that can block it.
    noon_ist = datetime.now(IST).replace(hour=12, minute=0, second=0, microsecond=0)
    if noon_ist.isoweekday() == 7:
        noon_ist -= timedelta(days=1)
    db_tx.execute(
        text("UPDATE customers SET dnd = false, preferred_window = NULL WHERE id = :cid"),
        {"cid": row["customer_id"]},
    )
    db_tx.execute(
        text("UPDATE callbacks SET scheduled_at = :at WHERE id = :id"),
        {"at": noon_ist, "id": row["id"]},
    )

    db_tx.execute(
        text("UPDATE consent_records SET dnd_registry = false WHERE customer_id = :cid"),
        {"cid": row["customer_id"]},
    )
    before = {c["id"]: c for c in db.list_callbacks(limit=500)}
    assert before[row["id"]]["dndActive"] is False, "control: nothing should block it yet"

    db_tx.execute(
        text("UPDATE consent_records SET dnd_registry = true WHERE customer_id = :cid"),
        {"cid": row["customer_id"]},
    )
    after = {c["id"]: c for c in db.list_callbacks(limit=500)}
    assert after[row["id"]]["dndActive"] is True, "registry flag must block the slot"


# --- WP-033: an absent window is a bound, not an absence --------------------


def _veto_at(customer: dict, at: datetime) -> str | None:
    """The outreach veto on a digital channel, with no published rule set.

    WhatsApp on purpose: voice is separately bounded by the statutory window, so
    it would mask the hole this covers.
    """
    return contact_policy._veto(
        purpose="outreach",
        channel="whatsapp",
        customer=customer,
        status=None,
        now_local=at,
        rules=None,
    )


def _customer(**over) -> dict:
    base = {
        "id": "CUST-TEST",
        "dnd": False,
        "dnd_registry": False,
        "allowed_hours": None,
        "preferred_window": None,
        "allowed_days": None,
    }
    base.update(over)
    return base


@pytest.mark.parametrize("hour", [3, 6, 21, 23])
def test_a_borrower_with_no_window_on_file_is_still_bounded(hour: int) -> None:
    """Outside the statutory 08:00–19:00 bound is hours, not a missing preference.

    Preference 09:00–20:00 is a tighter overlay inside that bound. Hours 08 and
    19 are the two edges where the two clocks disagree; they are covered below.
    """
    at = datetime(2026, 9, 7, hour, 0, tzinfo=IST)  # a Monday
    assert _veto_at(_customer(), at) == contact_policy.REASON_HOURS


def test_preference_tightens_inside_the_statutory_bound() -> None:
    """08:00 is lawful under RBI and outside the 09:00–20:00 preference."""
    at = datetime(2026, 9, 7, 8, 0, tzinfo=IST)
    assert _veto_at(_customer(), at) == contact_policy.REASON_WINDOW


@pytest.mark.parametrize("hour", [9, 12, 18])
def test_the_same_borrower_is_contactable_inside_those_bounds(hour: int) -> None:
    at = datetime(2026, 9, 7, hour, 0, tzinfo=IST)
    assert _veto_at(_customer(), at) is None


def test_a_recorded_window_cannot_widen_the_statutory_bound() -> None:
    """Preference may tighten 08:00–19:00. It may not extend it to 21:00."""
    at = datetime(2026, 9, 7, 21, 0, tzinfo=IST)
    stated = _customer(preferred_window="18:00-22:00 IST")
    assert _veto_at(stated, at) == contact_policy.REASON_HOURS
