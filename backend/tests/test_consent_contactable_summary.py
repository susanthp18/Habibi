"""The Consent screen's green/amber/red pill is computed on the wire.

It used to be a browser rule over the same row, evaluated on the operator's
clock; the borrower's own zone decides the allowed-hours reading now.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import db_consent


def _rec(**over):
    rec = {
        "timezone": "Asia/Kolkata",
        "consentExpiresAt": "2099-01-01T00:00:00+00:00",
        "onDndRegistry": False,
        "allowedWindow": {"days": [1, 2, 3, 4, 5], "startHour": 9, "endHour": 20},
        "channels": [
            {"channel": c, "status": "opted_in", "frequencyCapPerWeek": 3, "usedThisWeek": 0}
            for c in ("call", "whatsapp", "sms", "email")
        ],
    }
    rec.update(over)
    return rec


# A weekday next week at 05:30 UTC = 11:00 IST, inside a 9-20 window; the
# same day at 16:00 UTC = 21:30 IST, outside it. Relative, so the pin does
# not expire.
_DAY = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=7)
_DAY -= timedelta(days=max(0, _DAY.weekday() - 4))  # never a weekend
INSIDE = _DAY.replace(hour=5, minute=30)
OUTSIDE = _DAY.replace(hour=16, minute=0)


def test_all_channels_open_is_green() -> None:
    assert db_consent.contactable_summary(_rec(), INSIDE) == {
        "status": "green",
        "reasons": ["All channels available."],
    }


def test_the_window_is_read_in_the_borrowers_zone() -> None:
    summary = db_consent.contactable_summary(_rec(), OUTSIDE)
    assert summary["status"] == "red"
    assert all("Outside allowed hours (9:00–20:00)" in r for r in summary["reasons"])
    # the same instant is 11:00 in Colombo (UTC+5:30) too -- but 21:00 in Bangkok
    assert db_consent.contactable_summary(_rec(timezone="Asia/Bangkok"), INSIDE)["status"] == "green"
    assert db_consent.contactable_summary(_rec(timezone="America/New_York"), INSIDE)["status"] == "red"


def test_dnd_registry_blocks_calls_only() -> None:
    summary = db_consent.contactable_summary(_rec(onDndRegistry=True), INSIDE)
    assert summary["status"] == "amber"
    assert summary["reasons"] == ["call: Customer is on national DND registry (calls only)."]


def test_expired_consent_is_red_on_every_channel() -> None:
    summary = db_consent.contactable_summary(_rec(consentExpiresAt="2020-01-01T00:00:00+00:00"), INSIDE)
    assert summary["status"] == "red"
    assert len(summary["reasons"]) == 4


def test_weekly_cap_and_opt_out_name_the_channel() -> None:
    rec = _rec()
    rec["channels"][1]["usedThisWeek"] = 3
    rec["channels"][2]["status"] = "opted_out"
    summary = db_consent.contactable_summary(rec, INSIDE)
    assert summary["status"] == "amber"
    assert summary["reasons"] == [
        "whatsapp: Weekly cap reached (3/3).",
        "sms: Customer opted out of sms.",
    ]
