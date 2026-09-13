"""The per-contract writers: what each inbound contract's rows become in the
canonical tables. ``ingest`` admits, replays and applies a load; this is the
apply half, one function per contract code.
"""

from __future__ import annotations

import uuid
import json
import hashlib
from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import text

from bank_boundary import identifiers


class IngestRejected(ValueError):
    """The batch was refused and canonical state is unchanged."""

    def __init__(self, reason: str, breaks: list[dict[str, Any]] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.breaks = breaks or []


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _account_id(conn: Any, tenant_id: str, external_id: str) -> str | None:
    bound = identifiers.resolve(
        conn, tenant_id=tenant_id, namespace="account", external_id=external_id
    )
    if bound:
        return bound
    row = conn.execute(
        text(
            """
            SELECT a.id FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE a.id = :id AND c.tenant_id = :tid
            """
        ),
        {"id": external_id, "tid": tenant_id},
    ).scalar()
    return str(row) if row else None


def _customer_id(conn: Any, tenant_id: str, external_id: str) -> str | None:
    bound = identifiers.resolve(
        conn, tenant_id=tenant_id, namespace="customer", external_id=external_id
    )
    if bound:
        return bound
    row = conn.execute(
        text("SELECT id FROM customers WHERE id = :id AND tenant_id = :tid"),
        {"id": external_id, "tid": tenant_id},
    ).scalar()
    return str(row) if row else None


def _canonical_external_id(
    conn: Any,
    *,
    tenant_id: str,
    namespace: str,
    external_id: str,
    canonical_table: str,
    prefix: str,
) -> str:
    existing = identifiers.resolve(
        conn,
        tenant_id=tenant_id,
        namespace=namespace,
        external_id=external_id,
    )
    if existing:
        return existing
    token = (
        hashlib.sha256(f"{tenant_id}\0{namespace}\0{external_id}".encode("utf-8"))
        .hexdigest()[:20]
        .upper()
    )
    canonical_id = f"{prefix}-{token}"
    identifiers.bind(
        conn,
        tenant_id=tenant_id,
        namespace=namespace,
        external_id=external_id,
        canonical_id=canonical_id,
        canonical_table=canonical_table,
    )
    return canonical_id


def _apply_c1(conn: Any, *, tenant_id: str, rows: Sequence[Mapping[str, Any]]) -> None:
    for row in rows:
        ext = str(row["external_id"])
        account_id = _account_id(conn, tenant_id, ext)
        if not account_id:
            raise IngestRejected("ownership")
        identifiers.bind(
            conn,
            tenant_id=tenant_id,
            namespace="account",
            external_id=ext,
            canonical_id=account_id,
            canonical_table="accounts",
        )
        outstanding = (int(row.get("outstanding_paise") or 0)) / 100.0
        conn.execute(
            text(
                """
                UPDATE accounts
                   SET outstanding = :out,
                       dpd = COALESCE(:dpd, dpd),
                       status = COALESCE(:status, status),
                       updated_at = now()
                 WHERE id = :id
                """
            ),
            {
                "id": account_id,
                "out": outstanding,
                "dpd": row.get("dpd"),
                "status": row.get("canonical_status") or row.get("status"),
            },
        )


def _apply_c2(conn: Any, *, tenant_id: str, rows: Sequence[Mapping[str, Any]]) -> None:
    for row in rows:
        account_id = _account_id(conn, tenant_id, str(row["account_external_id"]))
        if not account_id:
            raise IngestRejected("ownership")
        inst_id = _canonical_external_id(
            conn,
            tenant_id=tenant_id,
            namespace="installment",
            external_id=str(row["external_id"]),
            canonical_table="emi_installments",
            prefix="W5EMI",
        )
        conn.execute(
            text(
                """
                INSERT INTO emi_installments (
                  id, account_id, installment_index, due_date, amount, status
                ) VALUES (
                  :id, :aid, :idx, :due, :amt, :status
                )
                ON CONFLICT (id) DO UPDATE SET
                  amount = EXCLUDED.amount,
                  status = EXCLUDED.status,
                  updated_at = now()
                """
            ),
            {
                "id": inst_id,
                "aid": account_id,
                "idx": int(row.get("installment_index") or 1),
                "due": row["due_date"],
                "amt": int(row.get("amount_paise") or 0) / 100.0,
                "status": row.get("status") or "upcoming",
            },
        )


def _apply_c3(conn: Any, *, tenant_id: str, rows: Sequence[Mapping[str, Any]]) -> None:
    for row in rows:
        account_id = _account_id(conn, tenant_id, str(row["account_external_id"]))
        customer_id = _customer_id(conn, tenant_id, str(row["customer_external_id"]))
        if not account_id or not customer_id:
            raise IngestRejected("ownership")
        mandate_id = _canonical_external_id(
            conn,
            tenant_id=tenant_id,
            namespace="mandate",
            external_id=str(row["external_id"]),
            canonical_table="mandates",
            prefix="W5MAN",
        )
        conn.execute(
            text(
                """
                INSERT INTO mandates (
                  id, tenant_id, customer_id, account_id, rail, umrn, status,
                  max_amount, debit_day
                ) VALUES (
                  :id, :tid, :cid, :aid, :rail, :umrn, :status, :max, :day
                )
                ON CONFLICT (id) DO UPDATE SET
                  status = EXCLUDED.status,
                  umrn = COALESCE(EXCLUDED.umrn, mandates.umrn),
                  updated_at = now()
                """
            ),
            {
                "id": mandate_id,
                "tid": tenant_id,
                "cid": customer_id,
                "aid": account_id,
                "rail": row.get("rail") or "nach",
                "umrn": row.get("umrn"),
                "status": row.get("status") or "active",
                "max": (int(row.get("max_amount_paise") or 0) / 100.0) or None,
                "day": row.get("debit_day"),
            },
        )


def _apply_c4c5(
    conn: Any, *, tenant_id: str, rows: Sequence[Mapping[str, Any]], code: str
) -> None:
    for row in rows:
        mandate_id = identifiers.resolve(
            conn,
            tenant_id=tenant_id,
            namespace="mandate",
            external_id=str(row["mandate_external_id"]),
        ) or str(row.get("mandate_id") or "")
        if not mandate_id:
            raise IngestRejected("ownership")
        account_id = conn.execute(
            text("SELECT account_id FROM mandates WHERE id = :id AND tenant_id = :tid"),
            {"id": mandate_id, "tid": tenant_id},
        ).scalar()
        if not account_id:
            raise IngestRejected("ownership")
        external_id = str(row["external_id"])
        recommendation_id = str(
            row.get("our_recommendation_id") or row.get("canonical_id") or ""
        )
        pid = conn.execute(
            text(
                """
                SELECT id FROM mandate_presentations
                 WHERE tenant_id = :tid AND mandate_id = :mid
                   AND presented_for = :cycle AND attempt_no = :attempt
                """
            ),
            {
                "tid": tenant_id,
                "mid": mandate_id,
                "cycle": row.get("presented_for") or row.get("cycle"),
                "attempt": int(row.get("attempt_no") or 1),
            },
        ).scalar()
        if recommendation_id:
            recommended = conn.execute(
                text(
                    """
                    SELECT id FROM mandate_presentations
                     WHERE id = :id AND tenant_id = :tid
                    """
                ),
                {"id": recommendation_id, "tid": tenant_id},
            ).scalar()
            if recommended:
                pid = recommended
        if pid:
            identifiers.bind(
                conn,
                tenant_id=tenant_id,
                namespace="presentation",
                external_id=external_id,
                canonical_id=str(pid),
                canonical_table="mandate_presentations",
            )
        else:
            pid = _canonical_external_id(
                conn,
                tenant_id=tenant_id,
                namespace="presentation",
                external_id=external_id,
                canonical_table="mandate_presentations",
                prefix="W5PRES",
            )
        status = "returned" if code == "C5" else (row.get("status") or "submitted")
        conn.execute(
            text(
                """
                INSERT INTO mandate_presentations (
                  id, tenant_id, mandate_id, account_id, amount, presented_for,
                  attempt_no, status, return_code, executor
                ) VALUES (
                  :id, :tid, :mid, :aid, :amt, :cycle, :attempt, :status,
                  :rc, 'lms'
                )
                ON CONFLICT (id) DO UPDATE SET
                  status = EXCLUDED.status,
                  return_code = COALESCE(EXCLUDED.return_code, mandate_presentations.return_code),
                  updated_at = now()
                """
            ),
            {
                "id": pid,
                "tid": tenant_id,
                "mid": mandate_id,
                "aid": account_id,
                "amt": int(row.get("amount_paise") or 0) / 100.0,
                "cycle": row.get("presented_for") or row.get("cycle"),
                "attempt": int(row.get("attempt_no") or 1),
                "status": status,
                "rc": row.get("normalised_return_code") or row.get("return_code"),
            },
        )


def _apply_c6(conn: Any, *, tenant_id: str, rows: Sequence[Mapping[str, Any]]) -> None:
    for row in rows:
        account_id = _account_id(conn, tenant_id, str(row["account_external_id"]))
        if not account_id:
            raise IngestRejected("ownership")
        entry_id = _canonical_external_id(
            conn,
            tenant_id=tenant_id,
            namespace="ledger_entry",
            external_id=str(row["external_id"]),
            canonical_table="ledger_entries",
            prefix="W5LED",
        )
        conn.execute(
            text(
                """
                INSERT INTO ledger_entries (
                  id, account_id, type, description, amount, posted_at
                ) VALUES (
                  :id, :aid, 'payment', :desc, :amt, :posted
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": entry_id,
                "aid": account_id,
                "desc": row.get("description") or "bank payment",
                "amt": int(row.get("amount_paise") or 0) / 100.0,
                "posted": row.get("posted_at") or row.get("event_time"),
            },
        )


def _apply_c7(
    conn: Any,
    *,
    tenant_id: str,
    rows: Sequence[Mapping[str, Any]],
    manifest_id: str,
    known_from: datetime,
) -> None:
    for row in rows:
        customer_id = row.get("_canonical_customer_id")
        if not customer_id:
            raise IngestRejected("ownership")
        conn.execute(
            text(
                """
                INSERT INTO bank_external_contacts (
                  id, tenant_id, customer_id, external_key, channel,
                  occurred_at, known_from, agency_id, agent_id, outcome,
                  source_ref, manifest_id
                ) VALUES (
                  :id, :tid, :cid, :key, :ch, :at, :kf, :ag, :agent, :out,
                  :src, :mid
                )
                ON CONFLICT (tenant_id, external_key) DO NOTHING
                """
            ),
            {
                "id": _id("BX"),
                "tid": tenant_id,
                "cid": customer_id,
                "key": str(row["external_key"]),
                "ch": row["channel"],
                "at": row["occurred_at"],
                "kf": known_from,
                "ag": row.get("agency_id"),
                "agent": row.get("agent_id"),
                "out": row.get("outcome"),
                "src": row.get("source_ref"),
                "mid": manifest_id,
            },
        )


def _apply_c8(
    conn: Any,
    *,
    tenant_id: str,
    rows: Sequence[Mapping[str, Any]],
    manifest_id: str,
    known_from: datetime,
) -> None:
    for row in rows:
        customer_id = row.get("_canonical_customer_id")
        if not customer_id:
            raise IngestRejected("ownership")
        conn.execute(
            text(
                """
                INSERT INTO bank_consent_snapshots (
                  id, tenant_id, customer_id, endpoint, purpose, channel,
                  permitted, source_ref, event_time, known_from, manifest_id
                ) VALUES (
                  :id, :tid, :cid, :ep, :purpose, :ch, :ok, :src, :et, :kf, :mid
                )
                ON CONFLICT (tenant_id, customer_id, endpoint, purpose, channel, event_time)
                DO NOTHING
                """
            ),
            {
                "id": _id("BC"),
                "tid": tenant_id,
                "cid": customer_id,
                "ep": row["endpoint"],
                "purpose": row.get("purpose") or "servicing",
                "ch": row.get("channel") or "all",
                "ok": bool(row.get("permitted", True)),
                "src": row.get("source_ref"),
                "et": row["event_time"],
                "kf": known_from,
                "mid": manifest_id,
            },
        )


def _apply_c9(
    conn: Any,
    *,
    tenant_id: str,
    rows: Sequence[Mapping[str, Any]],
    manifest_id: str,
    known_from: datetime,
) -> None:
    for row in rows:
        kind = row.get("kind") or "capacity"
        if kind == "roster":
            conn.execute(
                text(
                    """
                    INSERT INTO bank_agency_roster (
                      id, tenant_id, agency_id, agent_id, certification,
                      expires_at, known_from, manifest_id
                    ) VALUES (
                      :id, :tid, :ag, :agent, :cert, :exp, :kf, :mid
                    )
                    ON CONFLICT (tenant_id, agency_id, agent_id, certification)
                    DO UPDATE SET expires_at = EXCLUDED.expires_at,
                                  known_from = EXCLUDED.known_from
                    """
                ),
                {
                    "id": _id("BAR"),
                    "tid": tenant_id,
                    "ag": row["agency_id"],
                    "agent": row["agent_id"],
                    "cert": row["certification"],
                    "exp": row["expires_at"],
                    "kf": known_from,
                    "mid": manifest_id,
                },
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO bank_capacity (
                      id, tenant_id, plan_date, resource, capacity_units,
                      known_from, manifest_id
                    ) VALUES (
                      :id, :tid, :day, :res, :cap, :kf, :mid
                    )
                    ON CONFLICT (tenant_id, plan_date, resource) DO UPDATE SET
                      capacity_units = EXCLUDED.capacity_units,
                      known_from = EXCLUDED.known_from
                    """
                ),
                {
                    "id": _id("BCA"),
                    "tid": tenant_id,
                    "day": row["plan_date"],
                    "res": row["resource"],
                    "cap": row.get("capacity_units") or 0,
                    "kf": known_from,
                    "mid": manifest_id,
                },
            )


def _apply_c10(
    conn: Any,
    *,
    tenant_id: str,
    rows: Sequence[Mapping[str, Any]],
    manifest_id: str,
    known_from: datetime,
) -> None:
    for row in rows:
        customer_id = row.get("_canonical_customer_id")
        if not customer_id:
            raise IngestRejected("ownership")
        conn.execute(
            text(
                """
                INSERT INTO bank_protections (
                  id, tenant_id, customer_id, account_id, kind, active, detail,
                  event_time, known_from, manifest_id
                ) VALUES (
                  :id, :tid, :cid, :aid, :kind, :active, CAST(:detail AS jsonb),
                  :et, :kf, :mid
                )
                """
            ),
            {
                "id": _id("BP"),
                "tid": tenant_id,
                "cid": customer_id,
                "aid": row.get("_canonical_account_id"),
                "kind": row["kind"],
                "active": bool(row.get("active", True)),
                "detail": json.dumps(row.get("detail") or {}, default=str),
                "et": row.get("event_time") or known_from,
                "kf": known_from,
                "mid": manifest_id,
            },
        )


def _apply_f8(
    conn: Any,
    *,
    tenant_id: str,
    rows: Sequence[Mapping[str, Any]],
    manifest_id: str,
    known_from: datetime,
) -> None:
    for row in rows:
        customer_id = row.get("_canonical_customer_id")
        if not customer_id:
            raise IngestRejected("ownership")
        conn.execute(
            text(
                """
                INSERT INTO bank_complaint_events (
                  id, tenant_id, customer_id, direction, kind, clock_due_at,
                  decision_id, evidence, event_time, known_from, manifest_id
                ) VALUES (
                  :id, :tid, :cid, :dir, :kind, :due, :did,
                  CAST(:ev AS jsonb), :et, :kf, :mid
                )
                """
            ),
            {
                "id": _id("BF8"),
                "tid": tenant_id,
                "cid": customer_id,
                "dir": row.get("direction") or "inbound",
                "kind": row.get("kind") or "grievance",
                "due": row.get("clock_due_at"),
                "did": row.get("decision_id"),
                "ev": json.dumps(row.get("evidence") or {}, default=str),
                "et": row.get("event_time") or known_from,
                "kf": known_from,
                "mid": manifest_id,
            },
        )
