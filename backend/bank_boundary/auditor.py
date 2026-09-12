"""Breach auditor over internal contact_events ∪ C7 external ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text

from bank_boundary import schema_ready
from agent_core import clock

CONTRACTED_FLOOR = 0.95
EXPECTED_SOURCES = ("internal", "c7")


def audit(
    conn: Any,
    *,
    tenant_id: str,
    window_start: datetime,
    window_end: datetime,
    daily_cap: int = 3,
    coverage_floor: float = CONTRACTED_FLOOR,
) -> dict[str, Any]:
    """Incomplete coverage cannot be green."""
    internal = _rows(
        conn,
        """
        SELECT customer_id, channel, occurred_at, 'internal' AS source,
               id::text AS external_key
          FROM contact_events
         WHERE tenant_id = :tid
           AND occurred_at >= :start AND occurred_at < :end
        """,
        tid=tenant_id,
        start=window_start,
        end=window_end,
    ) if _has(conn, "contact_events") else []

    external = []
    if schema_ready.w5_ready(conn):
        external = _rows(
            conn,
            """
            SELECT customer_id, channel, occurred_at, 'c7' AS source, external_key
              FROM bank_external_contacts
             WHERE tenant_id = :tid
               AND occurred_at >= :start AND occurred_at < :end
            """,
            tid=tenant_id,
            start=window_start,
            end=window_end,
        )

    seen: set[Any] = set()
    union: list[dict[str, Any]] = []
    for row in internal + external:
        key = (
            row.get("external_key")
            or (
                row.get("customer_id"),
                row.get("channel"),
                row.get("occurred_at"),
            )
        )
        if key in seen:
            continue
        seen.add(key)
        union.append(row)

    sources: list[str] = []
    if _has(conn, "contact_events"):
        sources.append("internal")
    if schema_ready.w5_ready(conn):
        c7 = conn.execute(
            text(
                """
                SELECT 1 FROM bank_freshness
                 WHERE tenant_id = :tid AND contract_code = 'C7'
                   AND last_accepted_at IS NOT NULL
                LIMIT 1
                """
            ),
            {"tid": tenant_id},
        ).first()
        if c7 is not None:
            sources.append("c7")
    sources.sort()
    expected = len(EXPECTED_SOURCES)
    represented = len([s for s in EXPECTED_SOURCES if s in sources])
    coverage = represented / expected if expected else 0.0

    details = _breaches(conn, tenant_id=tenant_id, events=union, daily_cap=daily_cap)
    breaches = len(details)
    green = coverage >= coverage_floor and "c7" in sources and "internal" in sources
    result = {
        "breaches": breaches,
        "breach_details": details,
        "ledger_coverage_share": round(coverage, 4),
        "sources_represented": sources,
        "green": green,
        "n_events": len(union),
    }
    if schema_ready.w5_ready(conn):
        import json
        import uuid

        conn.execute(
            text(
                """
                INSERT INTO bank_breach_audits (
                  id, tenant_id, window_start, window_end, breaches,
                  ledger_coverage_share, sources_represented, green
                ) VALUES (
                  :id, :tid, :start, :end, :breaches,
                  :coverage, CAST(:sources AS jsonb), :green
                )
                """
            ),
            {
                "id": f"BBA-{uuid.uuid4().hex[:12].upper()}",
                "tid": tenant_id,
                "start": window_start,
                "end": window_end,
                "breaches": breaches,
                "coverage": coverage,
                "sources": json.dumps(sources),
                "green": green,
            },
        )
    return result


def _breaches(
    conn: Any,
    *,
    tenant_id: str,
    events: list[dict[str, Any]],
    daily_cap: int,
) -> list[dict[str, Any]]:
    from collections import defaultdict
    from datetime import timezone

    counts: dict[tuple[str, str], int] = defaultdict(int)
    breaches: list[dict[str, Any]] = []
    for row in events:
        cid = str(row.get("customer_id") or "")
        at = row.get("occurred_at")
        if not cid or at is None:
            continue
        if getattr(at, "tzinfo", None) is None:
            at = at.replace(tzinfo=timezone.utc)
        key = (cid, at.date().isoformat())
        counts[key] += 1
        if counts[key] > daily_cap:
            breaches.append({"kind": "daily_cap", "customer_id": cid, "at": at})
        local = at.astimezone(clock.tenant_tz())
        if local.hour < 8 or local.hour >= 19:
            breaches.append({"kind": "calling_window", "customer_id": cid, "at": at})
        if _hold_active_at(conn, tenant_id=tenant_id, customer_id=cid, at=at):
            breaches.append({"kind": "suppression", "customer_id": cid, "at": at})
    return breaches


def _hold_active_at(
    conn: Any, *, tenant_id: str, customer_id: str, at: datetime
) -> bool:
    if not _has(conn, "treatment_holds"):
        return False
    found = conn.execute(
        text(
            """
            SELECT 1 FROM treatment_holds
             WHERE tenant_id = :tid AND customer_id = :cid
               AND starts_at <= :at
               AND (released_at IS NULL OR released_at > :at)
               AND (expires_at IS NULL OR expires_at > :at)
            LIMIT 1
            """
        ),
        {"tid": tenant_id, "cid": customer_id, "at": at},
    ).first()
    return found is not None


def _has(conn: Any, table: str) -> bool:
    from agent_core.treatment import schema_ready as base

    return base.has_table(conn, table)


def _rows(conn: Any, sql: str, **params: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]
