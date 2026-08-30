"""Tenant-local time. One definition of "now", shared by every channel.

The containers run UTC. Nothing told the model that, and nothing told it what
time it was for the person on the phone, so on a live call it scheduled a
callback for ``2026-08-01T12:30:00+00:00`` and said "12:30 PM" out loud. Both
are internally consistent and they disagree by five and a half hours: the
customer expects 12:30 IST, the agent's screen shows 18:00 IST, and the callback
row is correct in neither sense.

A datetime is only meaningful next to the zone it was meant in. This module
supplies that zone, the current local time to put in front of the model, and the
normalisation that turns whatever the model emits into an unambiguous instant.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

#: Where the customers are. This is an India-facing retail collections product;
#: the deployment timezone (UTC in every container) is an infrastructure detail
#: and has never been the right answer for "what time did the caller mean".
DEFAULT_TIMEZONE = "Asia/Kolkata"


def timezone_name() -> str:
    return (os.getenv("APP_TIMEZONE") or "").strip() or DEFAULT_TIMEZONE


def tenant_tz() -> ZoneInfo:
    """The tenant's zone, falling back to the default rather than raising.

    A typo in APP_TIMEZONE must not take down callback scheduling on a live
    call; it should be loud in the log and behave as if unset.
    """
    name = timezone_name()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("APP_TIMEZONE %r is not a known zone — using %s", name, DEFAULT_TIMEZONE)
        return ZoneInfo(DEFAULT_TIMEZONE)


def now_local() -> datetime:
    return datetime.now(tenant_tz())


#: Inclusive start hours for the spoken parts of a day, in the tenant's own
#: zone, ascending. Indian retail collections greets on these four: morning from
#: 05:00, afternoon from noon, evening from 17:00, night from 21:00. Anything
#: before the first entry is night too — a call at 02:00 must not be greeted as
#: morning, which is the whole reason this is not just ``"day"``.
_PARTS_OF_DAY = ((5, "morning"), (12, "afternoon"), (17, "evening"), (21, "night"))


def part_of_day(at: datetime | None = None) -> str:
    """The word a person would use for the current time of day, tenant-local.

    Backs the ``{time_of_day}`` prompt variable. That token used to substitute
    the hardcoded string ``"day"`` from ``default_context`` — nothing anywhere
    computed it — so a prompt reading "Greet the caller, it is {time_of_day}"
    said "it is day" at 2 AM and at 6 PM alike. The clock this module already
    owns is the answer; there was never a second source to reconcile with.
    """
    now = at or now_local()
    hour = now.hour
    label = "night"
    for start, name in _PARTS_OF_DAY:
        if hour >= start:
            label = name
    return label


def describe_now() -> str:
    """One line for a prompt: what time it is where the customer is.

    Includes the zone name and the offset because the model has to be able to
    emit a correct offset, and includes the weekday because "tomorrow morning"
    and "Monday" are the units callers actually speak in.
    """
    now = now_local()
    return (
        f"Current local time for the customer: "
        f"{now.strftime('%A %d %B %Y, %I:%M %p')} "
        f"({timezone_name()}, UTC{now.strftime('%z')[:3]}:{now.strftime('%z')[3:]})"
    )


def to_instant(raw: str) -> datetime | None:
    """Parse a model-supplied datetime into an unambiguous instant.

    A value with an explicit offset is trusted as-is. A *naive* value is read as
    tenant-local, which is what the model means when it says "2:30 PM" — reading
    it as UTC is how a 2:30 PM callback became an 8:00 PM one.
    """
    s = (raw or "").strip()
    if not s:
        return None
    try:
        parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tenant_tz())
    return parsed


def to_local(value: datetime) -> datetime:
    """Render an instant in tenant-local time, for anything spoken or displayed."""
    if value.tzinfo is None:
        return value.replace(tzinfo=tenant_tz())
    return value.astimezone(tenant_tz())


def utc_isoformat(value: datetime) -> str:
    """Canonical storage form: an explicit UTC instant, never a naive string."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=tenant_tz())
    return value.astimezone(timezone.utc).isoformat()
