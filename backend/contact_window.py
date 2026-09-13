"""The preferred-contact-window parser. One implementation, imported from both sides.

This module is a DB-free preference parser. It has no regulatory authority:
statutory hours live in policy_rules rows and are evaluated by contact_policy.
The 09:00–20:00 default here is the borrower-preference fallback and must never
be merged with the RBI 08:00–19:00 statutory bound.

A leaf module on purpose, for the same reason as ``money_inr``: it imports
nothing from this repo, so ``db.py`` and ``agent_core`` can both take it at
module level without closing a cycle. Code-mode (``agent_core/skills/scripts``)
must stay free of a DB import.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

#: Contact windows are expressed in IST, not in the customer's tz column.
IST = timezone(timedelta(hours=5, minutes=30))

#: What a customer with no ``preferred_window`` on file is assumed to allow.
DEFAULT_START_HOUR = 9
DEFAULT_END_HOUR = 20

#: The same bounds as a window string, for echoing back to a caller that asked
#: which window a verdict was reached under.
DEFAULT_WINDOW = "09:00-20:00 IST"

#: ``09:00-20:00 IST``, ``9:00 – 8:00 pm``, ``10:00–19:00`` — any two HH:MM
#: pairs, whichever dash was typed between them.
_WINDOW_RE = re.compile(r"(\d{1,2}):(\d{2}).*?(\d{1,2}):(\d{2})")


def parse_hours(raw: str | None) -> tuple[int, int] | None:
    """The two hours in a window string, or ``None`` when nothing parses.

    The raw read: "nothing on file" and "unreadable" both come back ``None``
    so the gate can intersect a stated window with the statutory one and
    treat an absent one as absent. Screens that need a default use
    :func:`window_hours`.
    """
    if not raw or not str(raw).strip():
        return None
    match = _WINDOW_RE.search(str(raw))
    if not match:
        return None
    return int(match.group(1)), int(match.group(3))


def window_hours(preferred_window: str | None) -> tuple[int, int]:
    """Start/end hour of ``preferred_window``, falling back to the defaults.

    An unparseable window is not a licence to call at 03:00: it falls back to
    the default bounds rather than to "no restriction".
    """
    return parse_hours(preferred_window) or (DEFAULT_START_HOUR, DEFAULT_END_HOUR)


def outside_preferred_window(scheduled_at: str, preferred_window: str | None) -> bool:
    """True when the scheduled IST hour falls outside the HH:MM–HH:MM window.

    A timestamp that does not parse is not treated as a violation — the caller
    has a malformed input problem, not a contact-policy one.
    """
    try:
        at = datetime.fromisoformat(scheduled_at)
    except ValueError:
        return False
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    hour = at.astimezone(IST).hour
    start_h, end_h = window_hours(preferred_window)
    return hour < start_h or hour >= end_h


# --- allowed days ------------------------------------------------------------
#
# The hours rule was consolidated here; the days rule was not, and it drifted the
# same way for the same reason. ``contact_policy._parse_days`` normalised the
# dash and ``db._parse_allowed_days`` did not, so a borrower whose consent reads
# "Mon–Sat" was six days to the Gate and **Monday alone** to everything reading
# through db.py — the range branch missed, the token split matched the leading
# "mon", and a six-day consent silently became one. It fails closed, so nobody is
# contacted illegally; they are simply never contacted, which is the kind of
# wrong that does not raise.

#: 0=Sun … 6=Sat, matching ``isoweekday() % 7`` at the call sites.
DAY_NAME_TO_NUM = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def allowed_days(raw: str | None) -> list[int] | None:
    """Parse a consent day string. ``None`` means nothing was recorded.

    ``None`` is deliberately distinct from ``[]``: absent consent days and a
    string that named no recognisable day are different facts, and only the
    caller knows which default its screen or its gate should apply. Callers that
    need one substitute it themselves, visibly.

    Ranges arrive with whichever dash the operator's keyboard produced. The
    sibling ``allowed_hours`` column already holds both ``10:00-19:00 IST`` and
    ``10:00–19:00 IST``; ``window_hours`` tolerates that only because its regex
    skips the separator entirely. Here the dash is load-bearing, so it is
    normalised first.
    """
    if not raw or not str(raw).strip():
        return None
    text_val = str(raw).strip().lower().replace("–", "-").replace("—", "-")
    if "-" in text_val and "," not in text_val:
        parts = [p.strip() for p in text_val.split("-", 1)]
        if len(parts) == 2 and parts[0][:3] in DAY_NAME_TO_NUM and parts[1][:3] in DAY_NAME_TO_NUM:
            start, end = DAY_NAME_TO_NUM[parts[0][:3]], DAY_NAME_TO_NUM[parts[1][:3]]
            if start <= end:
                return list(range(start, end + 1))
            return list(range(start, 7)) + list(range(0, end + 1))
    days: list[int] = []
    for token in re.split(r"[,\s]+", text_val):
        key = token[:3]
        if key in DAY_NAME_TO_NUM:
            days.append(DAY_NAME_TO_NUM[key])
    return days or None
