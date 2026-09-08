"""Durable contact-budget reservations.

Immediate consumption at plan time is how a killed worker spends a borrower's
daily cap without sending anything. A reservation holds the slot until a
provider reference exists, then commits; abandoned rows are reaped.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import text

from agent_core.treatment import schema_ready

logger = logging.getLogger(__name__)

STATE_HELD = "held"
STATE_COMMITTED = "committed"
STATE_RELEASED = "released"


def reserve(
    conn: Any,
    *,
    tenant_id: str,
    customer_id: str,
    decision_id: str,
    channel: str,
) -> str | None:
    if not schema_ready.has_table(conn, "contact_reservations"):
        return None
    rid = f"CR-{uuid.uuid4().hex[:12].upper()}"
    try:
        conn.execute(
            text(
                """
                INSERT INTO contact_reservations (
                  id, tenant_id, customer_id, decision_id, channel,
                  state, created_at, updated_at
                ) VALUES (
                  :id, :tenant_id, :customer_id, :decision_id, :channel,
                  :state, now(), now()
                )
                ON CONFLICT (decision_id, channel) DO NOTHING
                """
            ),
            {
                "id": rid,
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "decision_id": decision_id,
                "channel": channel,
                "state": STATE_HELD,
            },
        )
        row = conn.execute(
            text(
                """
                SELECT id FROM contact_reservations
                WHERE decision_id = :d AND channel = :c
                """
            ),
            {"d": decision_id, "c": channel},
        ).scalar()
        return str(row) if row else rid
    except Exception:
        logger.exception("contact reservation failed for %s", decision_id)
        return None


def commit(conn: Any, reservation_id: str | None, *, provider_ref: str | None = None) -> None:
    _set(conn, reservation_id, STATE_COMMITTED, provider_ref=provider_ref)


def release(conn: Any, reservation_id: str | None) -> None:
    _set(conn, reservation_id, STATE_RELEASED)


def reap_abandoned(conn: Any, *, older_than: str = "15 minutes") -> int:
    if not schema_ready.has_table(conn, "contact_reservations"):
        return 0
    # Interval interpolated from a closed allow-list, never from caller text.
    window = older_than if older_than in {"15 minutes", "1 hour", "24 hours"} else "15 minutes"
    result = conn.execute(
        text(
            f"""
            UPDATE contact_reservations
            SET state = :released, updated_at = now()
            WHERE state = :held
              AND created_at < now() - interval '{window}'
            """
        ),
        {"released": STATE_RELEASED, "held": STATE_HELD},
    )
    return result.rowcount or 0


def _set(
    conn: Any,
    reservation_id: str | None,
    state: str,
    *,
    provider_ref: str | None = None,
) -> None:
    if not reservation_id or not schema_ready.has_table(conn, "contact_reservations"):
        return
    try:
        conn.execute(
            text(
                """
                UPDATE contact_reservations
                SET state = :state,
                    provider_ref = COALESCE(:provider_ref, provider_ref),
                    updated_at = now()
                WHERE id = :id AND state = :held
                """
            ),
            {
                "id": reservation_id,
                "state": state,
                "provider_ref": provider_ref,
                "held": STATE_HELD,
            },
        )
    except Exception:
        logger.exception("contact reservation update failed for %s", reservation_id)
