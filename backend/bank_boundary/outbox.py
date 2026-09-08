"""Typed outbound outbox. Retries reuse one idempotency key."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text

from bank_boundary import schema_ready

PENDING = "pending"
SENT = "sent"
ACKED = "acked"
RECONCILED = "reconciled"
AWAITING_SETTLEMENT = "awaiting_settlement"
PARKED = "parked"
REJECTED = "rejected"

AMBIGUOUS = frozenset({"unknown", "timeout", "ambiguous"})


def enqueue(
    conn: Any,
    *,
    tenant_id: str,
    contract_code: str,
    idempotency_key: str,
    payload: dict[str, Any],
    action_contract_id: str | None = None,
    decision_id: str | None = None,
) -> str:
    if not schema_ready.w5_ready(conn):
        return idempotency_key
    oid = f"BO-{uuid.uuid4().hex[:12].upper()}"
    conn.execute(
        text(
            """
            INSERT INTO bank_outbound_outbox (
              id, tenant_id, contract_code, action_contract_id, decision_id,
              idempotency_key, state, payload
            ) VALUES (
              :id, :tid, :code, :ac, :did, :key, :state, CAST(:payload AS jsonb)
            )
            ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
            """
        ),
        {
            "id": oid,
            "tid": tenant_id,
            "code": contract_code,
            "ac": action_contract_id,
            "did": decision_id,
            "key": idempotency_key,
            "state": PENDING,
            "payload": json.dumps(payload, default=str),
        },
    )
    row = conn.execute(
        text(
            """
            SELECT id FROM bank_outbound_outbox
             WHERE tenant_id = :tid AND idempotency_key = :key
            """
        ),
        {"tid": tenant_id, "key": idempotency_key},
    ).scalar()
    return str(row or oid)


def park(conn: Any, outbox_id: str, reason: str) -> None:
    conn.execute(
        text(
            """
            UPDATE bank_outbound_outbox
               SET state = :st, park_reason = :reason, updated_at = now()
             WHERE id = :id AND state IN ('pending','sent')
            """
        ),
        {"id": outbox_id, "st": PARKED, "reason": reason[:500]},
    )


def mark(
    conn: Any,
    outbox_id: str,
    state: str,
    *,
    provider_ref: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        text(
            """
            UPDATE bank_outbound_outbox
               SET state = :st, updated_at = now()
             WHERE id = :id
            """
        ),
        {"id": outbox_id, "st": state},
    )
    if provider_ref:
        conn.execute(
            text(
                """
                INSERT INTO bank_outbound_acks (
                  id, outbox_id, tenant_id, provider_ref, status, payload
                )
                SELECT :aid, o.id, o.tenant_id, :pref, :st, CAST(:payload AS jsonb)
                  FROM bank_outbound_outbox o WHERE o.id = :id
                ON CONFLICT (outbox_id, provider_ref, status) DO NOTHING
                """
            ),
            {
                "aid": f"BA-{uuid.uuid4().hex[:12].upper()}",
                "id": outbox_id,
                "pref": provider_ref,
                "st": state,
                "payload": json.dumps(payload or {}, default=str),
            },
        )


def get(
    conn: Any, *, tenant_id: str, idempotency_key: str
) -> dict[str, Any] | None:
    if not schema_ready.w5_ready(conn):
        return None
    row = conn.execute(
        text(
            """
            SELECT * FROM bank_outbound_outbox
             WHERE tenant_id = :tid AND idempotency_key = :key
            """
        ),
        {"tid": tenant_id, "key": idempotency_key},
    ).mappings().first()
    return dict(row) if row else None
