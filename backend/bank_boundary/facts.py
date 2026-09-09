"""Project accepted bank manifests into the W6 point-in-time fact substrate."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import text

from agent_core.treatment import schema_ready
from bank_boundary import identifiers

SHARD_VERSION = 1
SHARD_COUNT = 128


def shard_key(
    tenant_id: str,
    account_id: str,
    *,
    version: int = SHARD_VERSION,
    shard_count: int = SHARD_COUNT,
) -> int:
    """Stable cross-process shard assignment; never use PostgreSQL hashtext."""
    if version != SHARD_VERSION:
        raise ValueError(f"unsupported_shard_version:{version}")
    if shard_count <= 0 or shard_count > 32767:
        raise ValueError("invalid_shard_count")
    payload = f"{version}\0{tenant_id}\0{account_id}".encode()
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(digest, "big") % shard_count


def project_manifest(
    conn: Any,
    *,
    tenant_id: str,
    portfolio_id: str,
    contract_code: str,
    manifest_id: str,
    rows: Sequence[Mapping[str, Any]],
    event_time: datetime,
    known_from: datetime,
) -> int:
    """Write all Layer 0 facts in the caller's accepted-manifest transaction."""
    if not schema_ready.w6_ready(conn):
        return 0
    writers = {
        "C1": _loan,
        "C2": _installment,
        "C3": _mandate,
        "C4": _presentation,
        "C5": _return,
        "C6": _payment,
        "C7": _contact,
        "C8": _consent,
        "C10": _protection,
    }
    writer = writers.get(contract_code)
    if writer is None:
        return 0
    written = 0
    for index, row in enumerate(rows):
        source_row_id = str(
            row.get("source_row_id") or row.get("external_id") or index
        )
        written += int(
            writer(
                conn=conn,
                tenant_id=tenant_id,
                portfolio_id=portfolio_id,
                manifest_id=manifest_id,
                source_row_id=source_row_id,
                row=row,
                event_time=event_time,
                known_from=known_from,
            )
        )
    return written


def _utc(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return fallback


def _id(table: str, manifest_id: str, source_row_id: str) -> str:
    token = hashlib.sha256(
        f"{table}\0{manifest_id}\0{source_row_id}".encode()
    ).hexdigest()[:24]
    return f"W6-{token}"


def _range_end(conn: Any, table: str, tenant_id: str, fact_key: str, valid_from: datetime):
    return conn.execute(
        text(
            f"""
            SELECT min(lower(valid_at))
              FROM {table}
             WHERE tenant_id = :tid AND fact_key = :key
               AND known_to IS NULL AND lower(valid_at) > :vf
            """
        ),
        {"tid": tenant_id, "key": fact_key, "vf": valid_from},
    ).scalar()


def _prepare_range(
    conn: Any,
    *,
    table: str,
    tenant_id: str,
    fact_key: str,
    valid_from: datetime,
    known_from: datetime,
) -> datetime | None:
    conn.execute(
        text(
            f"""
            UPDATE {table}
               SET known_to = :kf
             WHERE tenant_id = :tid AND fact_key = :key
               AND known_to IS NULL AND lower(valid_at) = :vf
            """
        ),
        {"tid": tenant_id, "key": fact_key, "vf": valid_from, "kf": known_from},
    )
    conn.execute(
        text(
            f"""
            UPDATE {table}
               SET valid_at = tstzrange(lower(valid_at), :vf, '[)')
             WHERE tenant_id = :tid AND fact_key = :key
               AND known_to IS NULL
               AND lower(valid_at) < :vf
               AND valid_at @> :vf
            """
        ),
        {"tid": tenant_id, "key": fact_key, "vf": valid_from},
    )
    return _range_end(conn, table, tenant_id, fact_key, valid_from)


def _insert(
    conn: Any,
    *,
    table: str,
    tenant_id: str,
    portfolio_id: str,
    fact_key: str,
    manifest_id: str,
    source_row_id: str,
    valid_from: datetime,
    known_from: datetime,
    columns: Mapping[str, Any],
    event_fact: bool = False,
) -> bool:
    valid_to = (
        valid_from + timedelta(microseconds=1)
        if event_fact
        else _prepare_range(
            conn,
            table=table,
            tenant_id=tenant_id,
            fact_key=fact_key,
            valid_from=valid_from,
            known_from=known_from,
        )
    )
    names = list(columns)
    sql_names = ", ".join(names)
    sql_values = ", ".join(f":{name}" for name in names)
    result = conn.execute(
        text(
            f"""
            INSERT INTO {table} (
              id, tenant_id, portfolio_id, fact_key, valid_at, known_from,
              source_manifest_id, source_row_id, {sql_names}
            ) VALUES (
              :id, :tenant_id, :portfolio_id, :fact_key,
              tstzrange(:valid_from, :valid_to, '[)'), :known_from,
              :manifest_id, :source_row_id, {sql_values}
            )
            ON CONFLICT (tenant_id, source_manifest_id, source_row_id)
            DO NOTHING
            """
        ),
        {
            "id": _id(table, manifest_id, source_row_id),
            "tenant_id": tenant_id,
            "portfolio_id": portfolio_id,
            "fact_key": fact_key,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "known_from": known_from,
            "manifest_id": manifest_id,
            "source_row_id": source_row_id,
            # jsonb columns arrive here as Python containers -- ``_protection``
            # passes ``detail`` -- and psycopg cannot adapt a dict to a bound
            # parameter. Serialise here rather than at each call site, so the
            # next fact carrying a jsonb column does not rediscover this.
            **{
                name: (
                    json.dumps(value, sort_keys=True)
                    if isinstance(value, (Mapping, list))
                    else value
                )
                for name, value in columns.items()
            },
        },
    )
    return bool(result.rowcount)


def _account(conn: Any, tenant_id: str, external: str) -> str:
    account_id = identifiers.resolve(
        conn,
        tenant_id=tenant_id,
        namespace="account",
        external_id=external,
    ) or external
    owned = conn.execute(
        text(
            """
            SELECT a.id
              FROM accounts a JOIN customers c ON c.id = a.customer_id
             WHERE a.id = :aid AND c.tenant_id = :tid
            """
        ),
        {"aid": account_id, "tid": tenant_id},
    ).scalar()
    if not owned:
        raise ValueError("fact_account_ownership")
    return str(owned)


def _canonical(
    conn: Any, tenant_id: str, namespace: str, external: str
) -> str:
    value = identifiers.resolve(
        conn,
        tenant_id=tenant_id,
        namespace=namespace,
        external_id=external,
    )
    if not value:
        raise ValueError(f"fact_identifier_missing:{namespace}")
    return str(value)


def _base(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        key: kwargs[key]
        for key in (
            "conn",
            "tenant_id",
            "portfolio_id",
            "manifest_id",
            "source_row_id",
            "known_from",
        )
    }


def _loan(**kwargs: Any) -> bool:
    row = kwargs["row"]
    account_id = _account(kwargs["conn"], kwargs["tenant_id"], str(row["external_id"]))
    key = f"loan:{account_id}"
    written = _insert(
        **_base(kwargs),
        table="fct_loan_state",
        fact_key=key,
        valid_from=_utc(row.get("valid_from"), kwargs["event_time"]),
        columns={
            "account_id": account_id,
            "external_loan_id": str(row["external_id"]),
            "dpd": row.get("dpd"),
            "pos_paise": int(row.get("outstanding_paise") or 0),
            "bucket": row.get("bucket"),
            "status_raw": row.get("status"),
            "collectible": bool(row.get("contacting_permitted", True)),
        },
    )
    kwargs["conn"].execute(
        text(
            """
            UPDATE accounts
               SET shard_key = :shard, shard_version = :version
             WHERE id = :id
               AND (shard_key IS NULL OR shard_version IS DISTINCT FROM :version)
            """
        ),
        {
            "id": account_id,
            "shard": shard_key(kwargs["tenant_id"], account_id),
            "version": SHARD_VERSION,
        },
    )
    return written


def _installment(**kwargs: Any) -> bool:
    row = kwargs["row"]
    installment_id = _canonical(
        kwargs["conn"], kwargs["tenant_id"], "installment", str(row["external_id"])
    )
    account_id = _account(
        kwargs["conn"], kwargs["tenant_id"], str(row["account_external_id"])
    )
    return _insert(
        **_base(kwargs),
        table="fct_installment",
        fact_key=f"installment:{installment_id}",
        valid_from=_utc(row.get("valid_from"), kwargs["event_time"]),
        columns={
            "installment_id": installment_id,
            "account_id": account_id,
            "due_date": row.get("due_date"),
            "amount_paise": int(row.get("amount_paise") or 0),
            "paid_paise": int(row.get("paid_paise") or 0),
            "status": str(row.get("status") or "upcoming"),
        },
    )


def _mandate(**kwargs: Any) -> bool:
    row = kwargs["row"]
    mandate_id = _canonical(
        kwargs["conn"], kwargs["tenant_id"], "mandate", str(row["external_id"])
    )
    account_id = _account(
        kwargs["conn"], kwargs["tenant_id"], str(row["account_external_id"])
    )
    customer_id = str(row.get("_canonical_customer_id") or "")
    return _insert(
        **_base(kwargs),
        table="fct_mandate",
        fact_key=f"mandate:{mandate_id}",
        valid_from=_utc(row.get("valid_from"), kwargs["event_time"]),
        columns={
            "mandate_id": mandate_id,
            "account_id": account_id,
            "customer_id": customer_id,
            "rail": str(row.get("rail") or "nach"),
            "status": str(row.get("status") or "active"),
            "max_amount_paise": row.get("max_amount_paise"),
            "debit_day": row.get("debit_day"),
        },
    )


def _presentation(**kwargs: Any) -> bool:
    row = kwargs["row"]
    presentation_id = _canonical(
        kwargs["conn"], kwargs["tenant_id"], "presentation", str(row["external_id"])
    )
    data = kwargs["conn"].execute(
        text(
            """
            SELECT mandate_id, account_id
              FROM mandate_presentations
             WHERE id = :id AND tenant_id = :tid
            """
        ),
        {"id": presentation_id, "tid": kwargs["tenant_id"]},
    ).mappings().one()
    return _insert(
        **_base(kwargs),
        table="fct_presentation",
        fact_key=f"presentation:{presentation_id}",
        valid_from=_utc(row.get("event_time"), kwargs["event_time"]),
        columns={
            "presentation_id": presentation_id,
            "mandate_id": str(data["mandate_id"]),
            "account_id": str(data["account_id"]),
            "presented_for": row.get("presented_for") or row.get("cycle"),
            "amount_paise": int(row.get("amount_paise") or 0),
            "attempt_no": int(row.get("attempt_no") or 1),
            "status": str(row.get("status") or "submitted"),
        },
    )


def _return(**kwargs: Any) -> bool:
    row = kwargs["row"]
    presentation_id = _canonical(
        kwargs["conn"], kwargs["tenant_id"], "presentation", str(row["external_id"])
    )
    data = kwargs["conn"].execute(
        text(
            """
            SELECT mandate_id, account_id
              FROM mandate_presentations
             WHERE id = :id AND tenant_id = :tid
            """
        ),
        {"id": presentation_id, "tid": kwargs["tenant_id"]},
    ).mappings().one()
    return _insert(
        **_base(kwargs),
        table="fct_return",
        fact_key=f"return:{presentation_id}:{kwargs['source_row_id']}",
        valid_from=_utc(row.get("event_time"), kwargs["event_time"]),
        event_fact=True,
        columns={
            "return_id": str(row["external_id"]),
            "presentation_id": presentation_id,
            "mandate_id": str(data["mandate_id"]),
            "account_id": str(data["account_id"]),
            "returned_at": _utc(row.get("event_time"), kwargs["event_time"]),
            "amount_paise": int(row.get("amount_paise") or 0),
            "return_code_raw": str(row.get("return_code") or ""),
            "return_reason": row.get("normalised_return_code"),
            "retryable": row.get("normalised_return_code") in {
                "insufficient_funds",
                "technical",
            },
        },
    )


def _payment(**kwargs: Any) -> bool:
    row = kwargs["row"]
    payment_id = _canonical(
        kwargs["conn"], kwargs["tenant_id"], "ledger_entry", str(row["external_id"])
    )
    account_id = _account(
        kwargs["conn"], kwargs["tenant_id"], str(row["account_external_id"])
    )
    posted = _utc(row.get("posted_at"), kwargs["event_time"])
    return _insert(
        **_base(kwargs),
        table="fct_payment",
        fact_key=f"payment:{payment_id}",
        valid_from=posted,
        event_fact=True,
        columns={
            "payment_id": payment_id,
            "account_id": account_id,
            "posted_at": posted,
            "amount_paise": int(row.get("amount_paise") or 0),
            "channel": row.get("channel"),
        },
    )


def _contact(**kwargs: Any) -> bool:
    row = kwargs["row"]
    contact_id = kwargs["conn"].execute(
        text(
            """
            SELECT id FROM bank_external_contacts
             WHERE tenant_id = :tid AND external_key = :key
            """
        ),
        {"tid": kwargs["tenant_id"], "key": str(row["external_key"])},
    ).scalar_one()
    occurred = _utc(row.get("occurred_at"), kwargs["event_time"])
    return _insert(
        **_base(kwargs),
        table="fct_contact",
        fact_key=f"contact:{contact_id}",
        valid_from=occurred,
        event_fact=True,
        columns={
            "contact_id": str(contact_id),
            "customer_id": str(row["_canonical_customer_id"]),
            "account_id": row.get("_canonical_account_id"),
            "channel": str(row["channel"]),
            "occurred_at": occurred,
            "outcome": row.get("outcome"),
            "agency_id": row.get("agency_id"),
            "agent_id": row.get("agent_id"),
        },
    )


def _consent(**kwargs: Any) -> bool:
    row = kwargs["row"]
    customer_id = str(row["_canonical_customer_id"])
    event_at = _utc(row.get("event_time"), kwargs["event_time"])
    fact_key = ":".join(
        (
            "consent",
            customer_id,
            str(row["endpoint"]),
            str(row.get("purpose") or "servicing"),
            str(row.get("channel") or "all"),
        )
    )
    return _insert(
        **_base(kwargs),
        table="fct_consent",
        fact_key=fact_key,
        valid_from=event_at,
        columns={
            "consent_id": f"FC-{uuid.uuid4().hex[:16]}",
            "customer_id": customer_id,
            "endpoint": str(row["endpoint"]),
            "purpose": str(row.get("purpose") or "servicing"),
            "channel": str(row.get("channel") or "all"),
            "permitted": bool(row.get("permitted")),
            "event_time": event_at,
        },
    )


def _protection(**kwargs: Any) -> bool:
    row = kwargs["row"]
    customer_id = str(row["_canonical_customer_id"])
    account_id = row.get("_canonical_account_id")
    event_at = _utc(row.get("event_time"), kwargs["event_time"])
    key = f"protection:{customer_id}:{account_id or ''}:{row['kind']}"
    return _insert(
        **_base(kwargs),
        table="fct_protection",
        fact_key=key,
        valid_from=event_at,
        columns={
            "protection_id": f"FP-{uuid.uuid4().hex[:16]}",
            "customer_id": customer_id,
            "account_id": account_id,
            "kind": str(row["kind"]),
            "active": bool(row.get("active", True)),
            "detail": row.get("detail") or {},
            "event_time": event_at,
        },
    )
