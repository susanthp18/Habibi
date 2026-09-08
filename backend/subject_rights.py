"""DPDP subject requests: intake, 90-day SLO, correction and erasure."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from agent_core.treatment import schema_ready

logger = logging.getLogger(__name__)

KINDS = frozenset({"access", "correction", "erasure", "grievance"})
STATES = frozenset(
    {"received", "verified", "in_progress", "fulfilled", "refused", "escalated"}
)
SLO_DAYS = 90


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def create_request(
    conn: Any,
    *,
    tenant_id: str,
    customer_id: str,
    kind: str,
    actor_user_id: str | None,
    note: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"invalid_kind:{kind}")
    if not schema_ready.has_table(conn, "subject_requests"):
        raise RuntimeError("schema_not_ready")
    instant = now or datetime.now(timezone.utc)
    due = instant + timedelta(days=SLO_DAYS)
    request_id = _id("SRQ")
    conn.execute(
        text(
            """
            INSERT INTO subject_requests (
              id, tenant_id, customer_id, kind, state, received_at, due_at,
              actor_user_id, note
            ) VALUES (
              :id, :tid, :cid, :kind, 'received', :at, :due, :actor, :note
            )
            """
        ),
        {
            "id": request_id,
            "tid": tenant_id,
            "cid": customer_id,
            "kind": kind,
            "at": instant,
            "due": due,
            "actor": actor_user_id,
            "note": note,
        },
    )
    _event(conn, request_id, "received", actor_user_id, note)
    return get_request(conn, request_id)


def transition(
    conn: Any,
    request_id: str,
    *,
    state: str,
    actor_user_id: str | None,
    note: str | None = None,
    evidence_ref: str | None = None,
) -> dict[str, Any]:
    if state not in STATES:
        raise ValueError(f"invalid_state:{state}")
    row = get_request(conn, request_id)
    if state == "fulfilled" and row["kind"] == "erasure" and not (evidence_ref or row.get("evidenceRef")):
        raise ValueError("erasure_evidence_required")
    extra = ""
    params: dict[str, Any] = {
        "id": request_id,
        "state": state,
        "actor": actor_user_id,
        "note": note,
        "evidence": evidence_ref,
    }
    if state == "verified":
        extra = ", verified_at = now()"
    if state == "fulfilled":
        extra += ", fulfilled_at = now(), evidence_ref = COALESCE(:evidence, evidence_ref)"
    conn.execute(
        text(
            f"""
            UPDATE subject_requests
            SET state = :state, actor_user_id = :actor, note = COALESCE(:note, note),
                updated_at = now()
                {extra}
            WHERE id = :id
            """
        ),
        params,
    )
    _event(conn, request_id, state, actor_user_id, note)
    return get_request(conn, request_id)


def fulfil_erasure(conn: Any, request_id: str, *, actor_user_id: str | None) -> dict[str, Any]:
    """Cancel unenacted plans and record an erasure event. Does not shred keys."""
    row = get_request(conn, request_id)
    if row["kind"] != "erasure":
        raise ValueError("not_an_erasure")
    cancelled = conn.execute(
        text(
            """
            UPDATE treatment_decisions
            SET outcome = 'cancelled',
                cancel_reason = 'policy_effective_change',
                outcome_at = now()
            WHERE customer_id = :cid
              AND enacted IS FALSE
              AND outcome IS NULL
            RETURNING id
            """
        ),
        {"cid": row["customerId"]},
    ).scalars().all()
    evidence_id = _id("ERS")
    conn.execute(
        text(
            """
            INSERT INTO erasure_events (
              id, tenant_id, customer_id, request_id, cancelled_plans
            ) VALUES (:id, :tid, :cid, :rid, :n)
            """
        ),
        {
            "id": evidence_id,
            "tid": row["tenantId"],
            "cid": row["customerId"],
            "rid": request_id,
            "n": len(cancelled),
        },
    )
    return transition(
        conn,
        request_id,
        state="fulfilled",
        actor_user_id=actor_user_id,
        evidence_ref=evidence_id,
        note=f"cancelled_plans={len(cancelled)}",
    )


def get_request(conn: Any, request_id: str) -> dict[str, Any]:
    row = conn.execute(
        text("SELECT * FROM subject_requests WHERE id = :id"),
        {"id": request_id},
    ).mappings().first()
    if row is None:
        raise KeyError("subject_request_not_found")
    return {
        "id": row["id"],
        "tenantId": row["tenant_id"],
        "customerId": row["customer_id"],
        "kind": row["kind"],
        "state": row["state"],
        "receivedAt": row["received_at"],
        "verifiedAt": row["verified_at"],
        "dueAt": row["due_at"],
        "fulfilledAt": row["fulfilled_at"],
        "evidenceRef": row["evidence_ref"],
        "ownerUserId": row["owner_user_id"],
        "escalatedToUserId": row["escalated_to_user_id"],
        "note": row["note"],
    }


def list_requests(conn: Any, *, tenant_id: str, overdue_only: bool = False) -> list[dict[str, Any]]:
    where = "tenant_id = :tid"
    if overdue_only:
        where += " AND due_at < now() AND state NOT IN ('fulfilled','refused')"
    rows = conn.execute(
        text(f"SELECT id FROM subject_requests WHERE {where} ORDER BY due_at"),
        {"tid": tenant_id},
    ).scalars().all()
    return [get_request(conn, rid) for rid in rows]


def overdue_count(conn: Any, *, tenant_id: str) -> int:
    if not schema_ready.has_table(conn, "subject_requests"):
        return 0
    return int(
        conn.execute(
            text(
                """
                SELECT COUNT(*) FROM subject_requests
                WHERE tenant_id = :tid
                  AND due_at < now()
                  AND state NOT IN ('fulfilled','refused')
                """
            ),
            {"tid": tenant_id},
        ).scalar()
        or 0
    )


def _event(
    conn: Any, request_id: str, state: str, actor_user_id: str | None, note: str | None
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO subject_request_events (id, request_id, state, actor_user_id, note)
            VALUES (:id, :rid, :state, :actor, :note)
            """
        ),
        {
            "id": _id("SRE"),
            "rid": request_id,
            "state": state,
            "actor": actor_user_id,
            "note": note,
        },
    )
