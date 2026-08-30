"""The preferred-contact-window rule. One implementation, imported from both sides.

A leaf module on purpose, for the same reason as ``money_inr``: it imports
nothing from this repo, so ``db.py`` and ``agent_core`` can both take it at
module level without closing a cycle. Code-mode (``agent_core/skills/scripts``)
must stay free of a DB import, and that constraint is what produced the bug this
module exists to close — the rule was copied there instead of shared, and the
copy drifted.

The two copies defaulted differently when a customer had no ``preferred_window``
on file: ``db._outside_preferred_window`` treated 09:00–20:00 IST as callable,
the skill script treated 10:00–19:00 IST as callable. A promise at 09:30 IST was
therefore in-window to the callback/DND path and out-of-window to the agent's
own ``promise_date_in_window`` check — the same date, two verdicts, decided by
which copy happened to run. ``db.py``'s bounds are the authoritative ones: they
are what the callback DND flag and the outbound paths have always enforced.

Windows in this product are written in IST. Comparing against the UTC hour of a
timestamptz would falsely flag every morning slot as DND, so the instant is
converted before the hour is read.
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


def window_hours(preferred_window: str | None) -> tuple[int, int]:
    """Start/end hour of ``preferred_window``, falling back to the defaults.

    An unparseable window is not a licence to call at 03:00: it falls back to
    the default bounds rather than to "no restriction".
    """
    if not preferred_window:
        return DEFAULT_START_HOUR, DEFAULT_END_HOUR
    match = _WINDOW_RE.search(preferred_window)
    if not match:
        return DEFAULT_START_HOUR, DEFAULT_END_HOUR
    return int(match.group(1)), int(match.group(3))


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
