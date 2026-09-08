"""Durable enactment attempts. The idempotency key never changes.

One row per (tenant, decision, channel). Claim writes intent; provider I/O
happens outside the transaction; finalize or park happens on a fresh one.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import text

from agent_core.treatment import schema_ready

logger = logging.getLogger(__name__)

STATE_CLAIMED = "claimed"
STATE_COMMITTED = "committed"
STATE_QUEUED = "queued"
STATE_SENT = "sent"
STATE_FAILED = "failed"
STATE_PARKED = "parked"
STATE_RECONCILED = "reconciled"

STATES = frozenset(
    {
        STATE_CLAIMED,
        STATE_COMMITTED,
        STATE_QUEUED,
        STATE_SENT,
        STATE_FAILED,
        STATE_PARKED,
        STATE_RECONCILED,
    }
)


def idempotency_key(tenant_id: str, decision_id: str, channel: str) -> str:
    return f"{tenant_id}:{decision_id}:{channel}"


def write_intent(
    conn: Any,
    *,
    tenant_id: str,
    decision_id: str,
    channel: str,
    action: str,
) -> str | None:
    """Insert or return the existing attempt. Never mutates the key."""
    if not schema_ready.has_table(conn, "enactment_attempts"):
        return None
    key = idempotency_key(tenant_id, decision_id, channel)
    attempt_id = f"EA-{uuid.uuid4().hex[:12].upper()}"
    try:
        conn.execute(
            text(
                """
                INSERT INTO enactment_attempts (
                  id, tenant_id, decision_id, channel, action,
                  idempotency_key, state, created_at, updated_at
                ) VALUES (
                  :id, :tenant_id, :decision_id, :channel, :action,
                  :key, :state, now(), now()
                )
                ON CONFLICT (idempotency_key) DO NOTHING
                """
            ),
            {
                "id": attempt_id,
                "tenant_id": tenant_id,
                "decision_id": decision_id,
                "channel": channel,
                "action": action,
                "key": key,
                "state": STATE_CLAIMED,
            },
        )
        row = conn.execute(
            text(
                "SELECT id FROM enactment_attempts WHERE idempotency_key = :key"
            ),
            {"key": key},
        ).scalar()
        return str(row) if row else attempt_id
    except Exception:
        logger.exception("enactment intent failed for %s", decision_id)
        return None


def set_state(
    conn: Any,
    attempt_id: str | None,
    state: str,
    *,
    provider_ref: str | None = None,
    error: str | None = None,
) -> None:
    if not attempt_id or state not in STATES:
        return
    if not schema_ready.has_table(conn, "enactment_attempts"):
        return
    try:
        conn.execute(
            text(
                """
                UPDATE enactment_attempts
                SET state = :state,
                    provider_ref = COALESCE(:provider_ref, provider_ref),
                    error = COALESCE(:error, error),
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": attempt_id,
                "state": state,
                "provider_ref": provider_ref,
                "error": (error or "")[:2000] or None,
            },
        )
    except Exception:
        logger.exception("enactment state update failed for %s", attempt_id)


def for_decision(conn: Any, decision_id: str) -> dict[str, Any] | None:
    if not schema_ready.has_table(conn, "enactment_attempts"):
        return None
    row = conn.execute(
        text(
            """
            SELECT * FROM enactment_attempts
            WHERE decision_id = :id
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"id": decision_id},
    ).mappings().first()
    return dict(row) if row else None
