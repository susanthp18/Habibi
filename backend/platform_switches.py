"""Operator-flippable runtime switches, read by every process that can dial.

Why this exists next to :mod:`agent_core.platform_flags`
--------------------------------------------------------
Those are environment flags: read with ``os.getenv``, fixed for the life of the
process, changed only by editing ``.env`` and restarting the API, ``bot_worker``,
``voice.bot`` and the insurance worker. They are the right shape for "does this
deployment have the feature at all".

They are the wrong shape for "stop dialling, now". This module is that: one
boolean, in Postgres, that all four processes read and any operator can flip
from a screen.

The safety property
-------------------
**Absence is off.** A missing row, an empty table, a table that does not exist
yet and a database the reader cannot reach all resolve to ``False``. There is no
input — including a broken one — that turns dialling on by accident. The only
thing that enables a switch is a row that says so.

That is the opposite of the usual "degrade gracefully" instinct, and it is
deliberate: the failure this guards against is placing a call to a real person
who did not ask for one.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from sqlalchemy import text

logger = logging.getLogger("platform_switches")

#: Master gate on every outbound dial. Checked at the carrier boundary, so no
#: caller can route around it — see :func:`voice.twilio_ops.start_outbound_call`.
OUTBOUND_ENABLED = "outbound.enabled"

#: Lets the **demo button only** ignore *when* and *how often* it may dial.
#:
#: This is a compliance override, so it is worth being exact about its reach. It
#: applies to one endpoint, which dials one number: the configured demo contact,
#: a handset the operator running the demo owns. It cannot be reached for any
#: other customer, because the endpoint takes no phone number.
#:
#: Waives the timing and frequency vetoes — calling hours, the borrower's
#: preferred window, the cooling-off gap, and the daily and weekly caps. Those
#: exist to stop a borrower being rung repeatedly, and rehearsing on your own
#: handset is not that.
#:
#: Never waives consent, opt-out, DND, the registry or the DPDP promotional
#: basis. Those answer whether the person agreed to be contacted at all, and a
#: demo does not get to re-answer that question.
#:
#: The key still reads ``_window`` for a duller reason than the scope: renaming
#: it would orphan the row an operator has already enabled, silently making the
#: demo *more* restrictive at the moment they least expect it.
DEMO_IGNORES_WINDOW = "outbound.demo_ignores_window"

#: Keys an operator may flip from the product. Anything else is a 404 rather
#: than a silently-created row, so a typo in a URL cannot mint a new switch
#: that nothing reads.
KNOWN_KEYS: dict[str, str] = {
    OUTBOUND_ENABLED: (
        "Master switch for outbound calling. Off means nothing dials: not the "
        "treatment executor, not the campaign runner, not the bounce autodial, "
        "not the demo button."
    ),
    DEMO_IGNORES_WINDOW: (
        "Let the demo button dial regardless of when or how often — calling "
        "hours, preferred window, cooling-off and the daily/weekly caps. "
        "Affects the demo number only. Never overrides consent, opt-out, DND "
        "or the registry."
    ),
}

# A dial is rare, but the worker loops ask about the gate far more often than
# they dial. One short-lived cache keeps that from becoming a query per
# iteration in four processes.
#
# The cost is that turning a switch OFF can take up to this long to be
# observed. That is a real property of the control and worth stating plainly:
# it is a kill switch with a two-second tail, not an instant one. Writes clear
# the cache in their own process, so the operator who flips it sees it at once;
# the other three converge within the TTL.
_TTL_SECONDS = 2.0

_lock = threading.Lock()
_cache: dict[str, tuple[float, bool]] = {}


def _tenant() -> str:
    import db

    return db._tenant()


def is_enabled(key: str, *, engine: Any = None) -> bool:
    """Is this switch on? Anything other than a row saying so is ``False``."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]

    enabled = False
    try:
        import db

        eng = engine if engine is not None else db.engine
        with eng.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT enabled FROM platform_switches"
                    " WHERE tenant_id = :t AND key = :k"
                ),
                {"t": _tenant(), "k": key},
            ).first()
        enabled = bool(row[0]) if row else False
    except Exception:
        # Fail closed, and say so loudly. A switch we cannot read is not a
        # switch we may assume is on.
        logger.exception("platform switch %s unreadable — treating as OFF", key)
        enabled = False

    with _lock:
        _cache[key] = (time.monotonic() + _TTL_SECONDS, enabled)
    return enabled


def outbound_enabled(*, engine: Any = None) -> bool:
    """Master outbound gate. Off by default, in every deployment."""
    return is_enabled(OUTBOUND_ENABLED, engine=engine)


def demo_ignores_window(*, engine: Any = None) -> bool:
    """May the demo button dial outside permitted hours? Off by default."""
    return is_enabled(DEMO_IGNORES_WINDOW, engine=engine)


def invalidate(key: str | None = None) -> None:
    """Drop cached values so the next read hits the database."""
    with _lock:
        if key is None:
            _cache.clear()
        else:
            _cache.pop(key, None)


def get_all(conn: Any) -> list[dict[str, Any]]:
    """Every known switch with its current state, for the operator screen.

    Driven by :data:`KNOWN_KEYS`, not by what happens to be in the table, so a
    switch that has never been flipped still appears — off, which is the truth.
    """
    rows = {
        str(r["key"]): r
        for r in (
            conn.execute(
                text(
                    "SELECT key, enabled, updated_at, updated_by_user_id, note"
                    " FROM platform_switches WHERE tenant_id = :t"
                ),
                {"t": _tenant()},
            )
            .mappings()
            .all()
        )
    }
    out: list[dict[str, Any]] = []
    for key, description in KNOWN_KEYS.items():
        row = rows.get(key)
        out.append(
            {
                "key": key,
                "description": description,
                "enabled": bool(row["enabled"]) if row else False,
                "updatedAt": (
                    row["updated_at"].isoformat() if row and row["updated_at"] else None
                ),
                "updatedByUserId": row["updated_by_user_id"] if row else None,
                "note": row["note"] if row else None,
            }
        )
    return out


def set_enabled(conn: Any, key: str, enabled: bool, *, note: str | None = None) -> dict[str, Any]:
    """Flip a switch. Unknown keys raise ``KeyError`` rather than being created."""
    if key not in KNOWN_KEYS:
        raise KeyError("unknown_switch")

    import db

    conn.execute(
        text(
            """
            INSERT INTO platform_switches
              (tenant_id, key, enabled, updated_by_user_id, note, created_at, updated_at)
            VALUES (:t, :k, :e, :u, :n, now(), now())
            ON CONFLICT (tenant_id, key) DO UPDATE
               SET enabled = EXCLUDED.enabled,
                   updated_by_user_id = EXCLUDED.updated_by_user_id,
                   note = EXCLUDED.note,
                   updated_at = now()
            """
        ),
        {
            "t": _tenant(),
            "k": key,
            "e": bool(enabled),
            "u": db._actor_user_id(),
            "n": note,
        },
    )
    # Flipping the master outbound gate is an operational event, and the audit
    # trail is the first thing anyone asks for after an unexpected dial.
    db.record_activity(
        conn,
        "platform",
        key,
        "platform_switch_changed",
        f"Outbound calling turned {'on' if enabled else 'off'}"
        if key == OUTBOUND_ENABLED
        else f"Switch {key} turned {'on' if enabled else 'off'}",
        note,
    )
    invalidate(key)
    return {"key": key, "enabled": bool(enabled)}
