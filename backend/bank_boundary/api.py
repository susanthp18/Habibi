"""Operator-facing bank-boundary reads. No W5 console; W8 owns UI."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text

from bank_boundary import auditor, evaluation, freshness, ingest, registry, schema_ready


def contract_status(conn: Any, *, tenant_id: str, portfolio_id: str = "") -> dict[str, Any]:
    return {
        "bindings": registry.status(conn, tenant_id=tenant_id, portfolio_id=portfolio_id),
        "ready": schema_ready.w5_ready(conn),
    }


def manifests(conn: Any, *, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
    if not schema_ready.w5_ready(conn):
        return []
    return [
        dict(r)
        for r in conn.execute(
            text(
                """
                SELECT id, contract_code, source, business_date, state, reject_reason
                  FROM bank_inbound_manifests
                 WHERE tenant_id = :tid
                 ORDER BY created_at DESC
                 LIMIT :lim
                """
            ),
            {"tid": tenant_id, "lim": limit},
        ).mappings().all()
    ]


def ingest_manifest(conn: Any, *, tenant_id: str, body: Any) -> dict[str, Any]:
    event_time = datetime.fromisoformat(str(body.eventTime).replace("Z", "+00:00"))
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    return ingest.load(
        conn,
        tenant_id=tenant_id,
        portfolio_id=body.portfolioId or "",
        contract_code=body.contractCode,
        schema_version=body.schemaVersion,
        source=body.source,
        business_date=date.fromisoformat(body.businessDate),
        source_ref=body.sourceRef,
        control_count=body.controlCount,
        control_sum_paise=body.controlSumPaise,
        event_time=event_time,
        rows=list(body.rows or []),
    )


def reconciliation(conn: Any, *, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
    if not schema_ready.w5_ready(conn):
        return []
    return [
        dict(r)
        for r in conn.execute(
            text(
                """
                SELECT b.id, b.kind, b.detail, r.contract_code, r.business_date
                  FROM bank_reconciliation_breaks b
                  JOIN bank_reconciliation_runs r ON r.id = b.run_id
                 WHERE b.tenant_id = :tid
                 ORDER BY b.created_at DESC
                 LIMIT :lim
                """
            ),
            {"tid": tenant_id, "lim": limit},
        ).mappings().all()
    ]


def readiness(conn: Any, *, tenant_id: str, portfolio_id: str = "") -> dict[str, Any]:
    ready = freshness.resolve(conn, tenant_id=tenant_id, portfolio_id=portfolio_id)
    return {
        "shadowUnlocked": ready.shadow_unlocked,
        "waitOnly": ready.wait_only,
        "nonContacting": ready.non_contacting,
        "reasons": list(ready.reasons),
        "consecutiveOk": ready.consecutive_ok,
        "veto": ready.veto,
    }


def outbox_state(conn: Any, *, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
    if not schema_ready.w5_ready(conn):
        return []
    return [
        dict(r)
        for r in conn.execute(
            text(
                """
                SELECT id, contract_code, idempotency_key, state, park_reason
                  FROM bank_outbound_outbox
                 WHERE tenant_id = :tid
                 ORDER BY created_at DESC
                 LIMIT :lim
                """
            ),
            {"tid": tenant_id, "lim": limit},
        ).mappings().all()
    ]


def breach_coverage(conn: Any, *, tenant_id: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return auditor.audit(conn, tenant_id=tenant_id, window_start=start, window_end=now)


def fairness(conn: Any, *, tenant_id: str) -> dict[str, Any]:
    return evaluation.fairness_readiness(conn, tenant_id=tenant_id)


def file_complaint(
    conn: Any,
    *,
    tenant_id: str,
    customer_id: str,
    kind: str,
    actor_user_id: str | None,
) -> dict[str, Any]:
    from bank_boundary import adapters
    from datetime import date as _date

    now = datetime.now(timezone.utc)
    row = {
        "customer_external_id": customer_id,
        "external_id": f"F8-{customer_id}-{int(now.timestamp())}",
        "direction": "inbound",
        "kind": kind,
        "event_time": now.isoformat(),
        "amount_paise": 0,
        "source_row_id": f"f8:{customer_id}:{now.isoformat()}",
    }
    loaded = ingest.load(
        conn,
        tenant_id=tenant_id,
        contract_code="F8",
        schema_version="bank-boundary.v1",
        source="operator",
        business_date=_date.today(),
        source_ref=str(row["external_id"]),
        control_count=1,
        control_sum_paise=0,
        event_time=now,
        rows=[row],
    )
    filing = adapters.send_with_outbox(
        conn,
        tenant_id=tenant_id,
        contract_code="O5",
        action_contract={
            "version": "action-contract.v1",
            "decision_id": f"complaint:{loaded['id']}",
            "tenant_id": tenant_id,
            "action": "file_complaint",
            "digest": "ref",
            "portfolio_id": "",
        },
        idempotency_key=f"O5:{loaded['id']}",
    )
    inbound_id = conn.execute(
        text(
            """
            SELECT id FROM bank_complaint_events
             WHERE manifest_id = :manifest AND direction = 'inbound'
             ORDER BY created_at DESC LIMIT 1
            """
        ),
        {"manifest": loaded["id"]},
    ).scalar()
    conn.execute(
        text(
            """
            UPDATE bank_complaint_events
               SET outbox_id = :outbox
             WHERE id = :id
            """
        ),
        {"outbox": filing["id"], "id": inbound_id},
    )
    conn.execute(
        text(
            """
            INSERT INTO bank_complaint_events (
              id, tenant_id, customer_id, direction, kind, decision_id,
              outbox_id, evidence, event_time, known_from
            ) VALUES (
              :id, :tid, :cid, 'outbound', :kind, NULL,
              :outbox, CAST(:evidence AS jsonb), :at, :at
            )
            """
        ),
        {
            "id": f"F8O-{loaded['id']}",
            "tid": tenant_id,
            "cid": customer_id,
            "kind": kind,
            "outbox": filing["id"],
            "evidence": json.dumps(
                {"actorUserId": actor_user_id, "manifestId": loaded["id"]}
            ),
            "at": now,
        },
    )
    return {"id": loaded["id"], "state": loaded["state"]}


def list_complaints(conn: Any, *, tenant_id: str) -> list[dict[str, Any]]:
    if not schema_ready.w5_ready(conn):
        return []
    return [
        dict(r)
        for r in conn.execute(
            text(
                """
                SELECT id, customer_id, direction, kind, event_time
                  FROM bank_complaint_events
                 WHERE tenant_id = :tid
                 ORDER BY created_at DESC
                 LIMIT 100
                """
            ),
            {"tid": tenant_id},
        ).mappings().all()
    ]
