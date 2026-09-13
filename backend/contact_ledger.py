"""The contact ledger: the rows that make a contact count. One event per
admitted attempt, the per-day counter it is locked and reserved against, and
the week's running total on the consent row. ``contact_policy.admit`` is the
one writer; this is what it writes.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

#: Who can be on the hook for a contact. The ledger stores one of these or
#: "system"; the policy quotes the same set when it names an actor.
ACTORS = frozenset({"human", "bot", "system", "agency"})


def event_id() -> str:
    return f"CE-{uuid.uuid4().hex[:10].upper()}"


def insert_event(
    conn: Any,
    *,
    customer: dict[str, Any],
    channel: str,
    purpose: str,
    actor_kind: str,
    actor_user_id: str | None,
    outcome: str,
    reason: str | None,
    session_key: str | None,
    source: str | None,
    related_id: str | None,
    touch_counted: bool,
    account_id: str | None,
    occurred_at: datetime,
    policy_binding: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    policy_binding_hash: str | None = None,
) -> None:
    extra_cols = ""
    extra_vals = ""
    params: dict[str, Any] = {
        "id": event_id(),
        "tenant_id": customer["tenant_id"],
        "customer_id": customer["id"],
        "account_id": account_id,
        "channel": channel,
        "purpose": purpose,
        "actor_kind": actor_kind if actor_kind in ACTORS else "system",
        "actor_user_id": actor_user_id,
        "outcome": outcome,
        "reason": reason,
        "session_key": session_key,
        "source": source,
        "related_id": related_id,
        "touch_counted": touch_counted,
        "occurred_at": occurred_at,
    }
    from agent_core.treatment import schema_ready

    if schema_ready.has_column(conn, "contact_events", "policy_binding"):
        extra_cols = ", policy_binding, policy_binding_hash"
        extra_vals = ", CAST(:policy_binding AS jsonb), :policy_binding_hash"
        params["policy_binding"] = json.dumps(list(policy_binding))
        params["policy_binding_hash"] = policy_binding_hash
    conn.execute(
        text(
            f"""
            INSERT INTO contact_events (
              id, tenant_id, customer_id, account_id, channel, direction,
              purpose, actor_kind, actor_user_id, outcome, reason,
              session_key, source, related_id, touch_counted, occurred_at
              {extra_cols}
            ) VALUES (
              :id, :tenant_id, :customer_id, :account_id, :channel, 'outbound',
              :purpose, :actor_kind, :actor_user_id, :outcome, :reason,
              :session_key, :source, :related_id, :touch_counted, :occurred_at
              {extra_vals}
            )
            """
        ),
        params,
    )


def lock_day(conn: Any, customer_id: str, local_date: Any) -> int:
    """Take the borrower's day row lock; returns today's count so far."""
    conn.execute(
        text(
            """
            INSERT INTO contact_day_counters (customer_id, local_date, outreach_sessions)
            VALUES (:cid, :d, 0)
            ON CONFLICT (customer_id, local_date) DO NOTHING
            """
        ),
        {"cid": customer_id, "d": local_date},
    )
    row = (
        conn.execute(
            text(
                """
            SELECT outreach_sessions FROM contact_day_counters
            WHERE customer_id = :cid AND local_date = :d
            FOR UPDATE
            """
            ),
            {"cid": customer_id, "d": local_date},
        )
        .mappings()
        .first()
    )
    return int(row["outreach_sessions"] or 0) if row else 0


def increment_day(conn: Any, customer_id: str, local_date: Any) -> int:
    """Count one outreach session on a row `_lock_day` already holds."""
    row = (
        conn.execute(
            text(
                """
            UPDATE contact_day_counters
               SET outreach_sessions = outreach_sessions + 1
             WHERE customer_id = :cid AND local_date = :d
            RETURNING outreach_sessions
            """
            ),
            {"cid": customer_id, "d": local_date},
        )
        .mappings()
        .first()
    )
    return int(row["outreach_sessions"] or 0) if row else 0


def reserve_day(
    conn: Any, customer_id: str, local_date: Any, cap: int
) -> tuple[bool, int]:
    """Lock the day row and increment if under cap. Returns (ok, count_after)."""
    conn.execute(
        text(
            """
            INSERT INTO contact_day_counters (customer_id, local_date, outreach_sessions)
            VALUES (:cid, :d, 0)
            ON CONFLICT (customer_id, local_date) DO NOTHING
            """
        ),
        {"cid": customer_id, "d": local_date},
    )
    row = (
        conn.execute(
            text(
                """
            SELECT outreach_sessions
            FROM contact_day_counters
            WHERE customer_id = :cid AND local_date = :d
            FOR UPDATE
            """
            ),
            {"cid": customer_id, "d": local_date},
        )
        .mappings()
        .first()
    )
    current = int(row["outreach_sessions"] or 0) if row else 0
    if current >= cap:
        return False, current
    conn.execute(
        text(
            """
            UPDATE contact_day_counters
            SET outreach_sessions = outreach_sessions + 1
            WHERE customer_id = :cid AND local_date = :d
            """
        ),
        {"cid": customer_id, "d": local_date},
    )
    return True, current + 1


def refresh_used_this_week(
    conn: Any, customer_id: str, channel: str, tz: ZoneInfo
) -> None:
    local = datetime.now(tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
    n = conn.execute(
        text(
            """
            SELECT count(*)::int AS n
            FROM contact_events
            WHERE customer_id = :cid
              AND channel = :ch
              AND outcome = 'allowed'
              AND touch_counted
              AND occurred_at >= :start
            """
        ),
        {"cid": customer_id, "ch": channel, "start": start.astimezone(timezone.utc)},
    ).scalar()
    conn.execute(
        text(
            """
            UPDATE channel_consents cc
            SET used_this_week = :n
            FROM consent_records cr
            WHERE cc.consent_id = cr.id
              AND cr.customer_id = :cid
              AND cc.channel = :ch
            """
        ),
        {"cid": customer_id, "ch": channel, "n": int(n or 0)},
    )
