"""Typed inbound loaders. Validate the whole batch, then one idempotent write."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Protocol, Sequence

from sqlalchemy import text

from bank_boundary import ALL_CODES, INBOUND, facts, identifiers, mappings, schema_ready


class IngestRejected(ValueError):
    """The batch was refused and canonical state is unchanged."""

    def __init__(self, reason: str, breaks: list[dict[str, Any]] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.breaks = breaks or []


class ContractAdapter(Protocol):
    code: str

    def validate(self, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        ...

    def apply(
        self,
        conn: Any,
        *,
        tenant_id: str,
        portfolio_id: str,
        rows: Sequence[Mapping[str, Any]],
        manifest_id: str,
        known_from: datetime,
    ) -> tuple[int, int]:
        """Return (observed_count, observed_sum_paise)."""
        ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _hash_rows(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = json.dumps(list(rows), sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _paise(row: Mapping[str, Any]) -> int:
    if "amount_paise" in row:
        return int(row["amount_paise"] or 0)
    if "outstanding_paise" in row:
        return int(row["outstanding_paise"] or 0)
    return 0


def load(
    conn: Any,
    *,
    tenant_id: str,
    portfolio_id: str = "",
    contract_code: str,
    schema_version: str,
    source: str,
    business_date: date,
    source_ref: str,
    control_count: int,
    control_sum_paise: int,
    event_time: datetime,
    rows: Sequence[Mapping[str, Any]],
    known_from: datetime | None = None,
    mapping_namespace: str = "reference",
) -> dict[str, Any]:
    """Atomic ingest. A mismatch rejects the whole batch."""
    if not schema_ready.w5_ready(conn):
        raise IngestRejected("w5_schema_missing")
    if contract_code not in ALL_CODES:
        raise IngestRejected(f"unknown_contract:{contract_code}")
    if contract_code == "F9":
        raise IngestRejected("f9_requires_evaluation_adapter")
    if contract_code not in INBOUND:
        raise IngestRejected(f"outbound_contract_requires_outbox:{contract_code}")

    arrival = known_from or _now()
    if arrival.tzinfo is None:
        arrival = arrival.replace(tzinfo=timezone.utc)
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    if arrival < event_time:
        raise IngestRejected("backdated_known_from")
    if arrival < _now() - timedelta(seconds=5) and known_from is not None:
        raise IngestRejected("backdated_known_from")
    if event_time > _now() + timedelta(minutes=5):
        raise IngestRejected("future_event_time")

    version_exists = conn.execute(
        text(
            """
            SELECT 1 FROM bank_contract_versions
             WHERE contract_code = :code AND schema_version = :version
               AND active IS TRUE
            """
        ),
        {"code": contract_code, "version": schema_version},
    ).first()
    if version_exists is None:
        _record_break(
            conn,
            tenant_id=tenant_id,
            portfolio_id=portfolio_id,
            contract_code=contract_code,
            business_date=business_date,
            kind="contract_version",
            detail={"schema_version": schema_version},
        )
        raise IngestRejected("contract_version")
    binding = conn.execute(
        text(
            """
            SELECT schema_version, state FROM bank_contract_bindings
             WHERE tenant_id = :tid AND portfolio_id = :pid
               AND contract_code = :code
            """
        ),
        {"tid": tenant_id, "pid": portfolio_id, "code": contract_code},
    ).mappings().first()
    if (
        binding is None
        or binding["schema_version"] != schema_version
        or binding["state"] == "blocked"
    ):
        _record_break(
            conn,
            tenant_id=tenant_id,
            portfolio_id=portfolio_id,
            contract_code=contract_code,
            business_date=business_date,
            kind="binding",
            detail={"schema_version": schema_version},
        )
        raise IngestRejected("binding")

    payload_hash = _hash_rows(rows)
    existing = conn.execute(
        text(
            """
            SELECT id, payload_hash, state, reject_reason
              FROM bank_inbound_manifests
             WHERE tenant_id = :tid AND source = :src
               AND business_date = :bd AND schema_version = :ver
               AND source_ref = :ref AND payload_hash = :hash
            """
        ),
        {
            "tid": tenant_id,
            "src": source,
            "bd": business_date,
            "ver": schema_version,
            "ref": source_ref,
            "hash": payload_hash,
        },
    ).mappings().first()
    if existing:
        if existing["state"] == "accepted":
            return {"id": existing["id"], "state": "accepted", "replayed": True}
        raise IngestRejected(existing["reject_reason"] or "rejected")
    prior = conn.execute(
        text(
            """
            SELECT id, payload_hash
              FROM bank_inbound_manifests
             WHERE tenant_id = :tid AND source = :src
               AND business_date = :bd AND schema_version = :ver
               AND source_ref = :ref
             ORDER BY created_at
             LIMIT 1
            """
        ),
        {
            "tid": tenant_id,
            "src": source,
            "bd": business_date,
            "ver": schema_version,
            "ref": source_ref,
        },
    ).mappings().first()
    if prior:
        rejected_source_ref = (
            f"{source_ref}#rejected:{payload_hash.removeprefix('sha256:')[:12]}"
        )
        already_rejected = conn.execute(
            text(
                """
                SELECT 1 FROM bank_inbound_manifests
                 WHERE tenant_id = :tid AND source = :src
                   AND business_date = :bd AND schema_version = :ver
                   AND source_ref = :ref AND payload_hash = :hash
                   AND state = 'rejected'
                """
            ),
            {
                "tid": tenant_id,
                "src": source,
                "bd": business_date,
                "ver": schema_version,
                "ref": rejected_source_ref,
                "hash": payload_hash,
            },
        ).first()
        if already_rejected:
            raise IngestRejected("hash_mismatch")
        _reject(
            conn,
            tenant_id=tenant_id,
            portfolio_id=portfolio_id,
            contract_code=contract_code,
            schema_version=schema_version,
            source=source,
            business_date=business_date,
            source_ref=rejected_source_ref,
            control_count=control_count,
            control_sum_paise=control_sum_paise,
            payload_hash=payload_hash,
            event_time=event_time,
            known_from=arrival,
            reason="hash_mismatch",
            breaks=[
                {
                    "kind": "hash_mismatch",
                    "source_ref": source_ref,
                    "prior_manifest_id": prior["id"],
                }
            ],
        )
        raise IngestRejected("hash_mismatch")

    breaks: list[dict[str, Any]] = []
    if len(rows) != control_count:
        breaks.append({"kind": "count", "observed": len(rows), "control": control_count})
    observed_sum = sum(_paise(r) for r in rows)
    if observed_sum != control_sum_paise:
        breaks.append(
            {
                "kind": "sum",
                "observed": observed_sum,
                "control": control_sum_paise,
            }
        )
    keys = [str(r.get("source_row_id") or r.get("external_id") or i) for i, r in enumerate(rows)]
    if len(keys) != len(set(keys)):
        breaks.append({"kind": "duplicate", "keys": keys})

    adapter = _ADAPTERS.get(contract_code)
    if adapter is None:
        breaks.append({"kind": "unknown_map", "contract": contract_code})

    if breaks:
        manifest_id = _reject(
            conn,
            tenant_id=tenant_id,
            portfolio_id=portfolio_id,
            contract_code=contract_code,
            schema_version=schema_version,
            source=source,
            business_date=business_date,
            source_ref=source_ref,
            control_count=control_count,
            control_sum_paise=control_sum_paise,
            payload_hash=payload_hash,
            event_time=event_time,
            known_from=arrival,
            reason=breaks[0]["kind"],
            breaks=breaks,
        )
        raise IngestRejected(breaks[0]["kind"], breaks)

    try:
        validated = adapter.validate(rows) if adapter else list(rows)
        _preflight(
            conn,
            tenant_id=tenant_id,
            contract_code=contract_code,
            rows=validated,
            arrival=arrival,
        )
        _check_maps(conn, contract_code, validated, namespace=mapping_namespace)
    except IngestRejected as exc:
        _reject(
            conn,
            tenant_id=tenant_id,
            portfolio_id=portfolio_id,
            contract_code=contract_code,
            schema_version=schema_version,
            source=source,
            business_date=business_date,
            source_ref=source_ref,
            control_count=control_count,
            control_sum_paise=control_sum_paise,
            payload_hash=payload_hash,
            event_time=event_time,
            known_from=arrival,
            reason=exc.reason if exc.reason in {"ownership", "temporal"} else "validation",
            breaks=[{"kind": exc.reason}],
        )
        raise
    except mappings.UnknownMapping as exc:
        mappings.open_review(
            conn,
            tenant_id=tenant_id,
            catalogue=exc.catalogue,
            raw_value=exc.raw,
            contract_code=contract_code,
        )
        _reject(
            conn,
            tenant_id=tenant_id,
            portfolio_id=portfolio_id,
            contract_code=contract_code,
            schema_version=schema_version,
            source=source,
            business_date=business_date,
            source_ref=source_ref,
            control_count=control_count,
            control_sum_paise=control_sum_paise,
            payload_hash=payload_hash,
            event_time=event_time,
            known_from=arrival,
            reason="unknown_map",
            breaks=[{"kind": "unknown_map", "raw": exc.raw}],
        )
        raise IngestRejected("unknown_map") from exc

    apply_tx = conn.begin_nested()
    manifest_id = _id("BM")
    conn.execute(
        text(
            """
            INSERT INTO bank_inbound_manifests (
              id, tenant_id, portfolio_id, contract_code, schema_version,
              source, business_date, source_ref, control_count, control_sum_paise,
              payload_hash, event_time, known_from, state
            ) VALUES (
              :id, :tid, :pid, :code, :ver, :src, :bd, :ref, :cnt, :sum,
              :hash, :et, :kf, 'accepted'
            )
            """
        ),
        {
            "id": manifest_id,
            "tid": tenant_id,
            "pid": portfolio_id,
            "code": contract_code,
            "ver": schema_version,
            "src": source,
            "bd": business_date,
            "ref": source_ref,
            "cnt": control_count,
            "sum": control_sum_paise,
            "hash": payload_hash,
            "et": event_time,
            "kf": arrival,
        },
    )
    try:
        observed_count, observed_sum = adapter.apply(
            conn,
            tenant_id=tenant_id,
            portfolio_id=portfolio_id,
            rows=validated,
            manifest_id=manifest_id,
            known_from=arrival,
        )
        facts.project_manifest(
            conn,
            tenant_id=tenant_id,
            portfolio_id=portfolio_id,
            contract_code=contract_code,
            manifest_id=manifest_id,
            rows=validated,
            event_time=event_time,
            known_from=arrival,
        )
        _finish_run(
            conn,
            tenant_id=tenant_id,
            portfolio_id=portfolio_id,
            contract_code=contract_code,
            business_date=business_date,
            manifest_id=manifest_id,
            status="matched",
            observed_count=observed_count,
            observed_sum_paise=observed_sum,
            control_count=control_count,
            control_sum_paise=control_sum_paise,
        )
        _touch_freshness(
            conn,
            tenant_id=tenant_id,
            portfolio_id=portfolio_id,
            contract_code=contract_code,
            known_from=arrival,
            business_date=business_date,
            matched=True,
        )
        apply_tx.commit()
    except Exception as exc:
        apply_tx.rollback()
        _reject(
            conn,
            tenant_id=tenant_id,
            portfolio_id=portfolio_id,
            contract_code=contract_code,
            schema_version=schema_version,
            source=source,
            business_date=business_date,
            source_ref=source_ref,
            control_count=control_count,
            control_sum_paise=control_sum_paise,
            payload_hash=payload_hash,
            event_time=event_time,
            known_from=arrival,
            reason="validation",
            breaks=[{"kind": "validation", "error": type(exc).__name__}],
        )
        if isinstance(exc, IngestRejected):
            raise
        raise IngestRejected("validation") from exc
    return {"id": manifest_id, "state": "accepted", "replayed": False}


def _preflight(
    conn: Any,
    *,
    tenant_id: str,
    contract_code: str,
    rows: Sequence[Mapping[str, Any]],
    arrival: datetime,
) -> None:
    """Validate the entire batch before any canonical row is written."""
    required: dict[str, tuple[str, ...]] = {
        "C1": ("external_id", "outstanding_paise", "status"),
        "C2": ("external_id", "account_external_id", "due_date", "amount_paise"),
        "C3": (
            "external_id",
            "account_external_id",
            "customer_external_id",
            "status",
        ),
        "C4": (
            "external_id",
            "mandate_external_id",
            "presented_for",
            "amount_paise",
        ),
        "C5": (
            "external_id",
            "mandate_external_id",
            "presented_for",
            "amount_paise",
            "return_code",
        ),
        "C6": (
            "external_id",
            "account_external_id",
            "amount_paise",
            "posted_at",
        ),
        "C7": (
            "customer_external_id",
            "external_key",
            "channel",
            "occurred_at",
        ),
        "C8": (
            "customer_external_id",
            "endpoint",
            "purpose",
            "channel",
            "permitted",
            "event_time",
        ),
        "C10": ("customer_external_id", "kind", "active", "event_time"),
        "F8": ("customer_external_id", "kind", "event_time"),
    }
    allowed_channels = {"voice", "whatsapp", "sms", "email", "chat", "field"}
    for row in rows:
        missing = [
            key
            for key in required.get(contract_code, ())
            if key not in row or row[key] is None or row[key] == ""
        ]
        if missing:
            raise IngestRejected(f"validation:{','.join(missing)}")
        if contract_code == "C9":
            kind = str(row.get("kind") or "")
            needed = (
                ("agency_id", "agent_id", "certification", "expires_at")
                if kind == "roster"
                else ("plan_date", "resource", "capacity_units")
            )
            if kind not in {"roster", "capacity"} or any(
                key not in row or row[key] is None for key in needed
            ):
                raise IngestRejected("validation:C9")
        for key in ("event_time", "occurred_at", "posted_at"):
            value = row.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if not isinstance(value, datetime):
                raise IngestRejected(f"temporal:{key}")
            aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            if aware > arrival + timedelta(minutes=5):
                raise IngestRejected(f"temporal:{key}")
        if contract_code in {"C7", "C8"} and row.get("channel") not in allowed_channels:
            raise IngestRejected("validation:channel")

        if contract_code in {"C1"}:
            if not _account_id(conn, tenant_id, str(row["external_id"])):
                raise IngestRejected("ownership")
        if contract_code in {"C2", "C3", "C6"}:
            if not _account_id(conn, tenant_id, str(row["account_external_id"])):
                raise IngestRejected("ownership")
        if contract_code in {"C3", "C7", "C8", "C10", "F8"}:
            customer_id = _customer_id(
                conn, tenant_id, str(row["customer_external_id"])
            )
            if not customer_id:
                raise IngestRejected("ownership")
            if isinstance(row, dict):
                row["_canonical_customer_id"] = customer_id
        if contract_code in {"C4", "C5"}:
            mandate_id = identifiers.resolve(
                conn,
                tenant_id=tenant_id,
                namespace="mandate",
                external_id=str(row["mandate_external_id"]),
            )
            if not mandate_id:
                raise IngestRejected("ownership")
        if contract_code == "C10" and row.get("account_external_id"):
            account_id = _account_id(
                conn, tenant_id, str(row["account_external_id"])
            )
            if not account_id:
                raise IngestRejected("ownership")
            if isinstance(row, dict):
                row["_canonical_account_id"] = account_id


def _check_maps(
    conn: Any,
    contract_code: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    namespace: str,
) -> None:
    if contract_code in {"C1", "C10"}:
        for row in rows:
            status = row.get("lms_status") or row.get("status")
            if status:
                mapped = mappings.lookup_lms_status(
                    conn, namespace=namespace, code=str(status)
                )
                if isinstance(row, dict):
                    row["canonical_status"] = mapped["normalised"]
                    row["contacting_permitted"] = mapped["contacting_permitted"]
    if contract_code == "C5":
        for row in rows:
            code = row.get("return_code")
            if code:
                normalised = mappings.lookup_rail(
                    conn, namespace=namespace, code=str(code)
                )
                if isinstance(row, dict):
                    row["normalised_return_code"] = normalised


def _reject(
    conn: Any,
    **kwargs: Any,
) -> str:
    manifest_id = _id("BM")
    breaks = kwargs.pop("breaks")
    reason = kwargs.pop("reason")
    conn.execute(
        text(
            """
            INSERT INTO bank_inbound_manifests (
              id, tenant_id, portfolio_id, contract_code, schema_version,
              source, business_date, source_ref, control_count, control_sum_paise,
              payload_hash, event_time, known_from, state, reject_reason
            ) VALUES (
              :id, :tid, :pid, :code, :ver, :src, :bd, :ref, :cnt, :sum,
              :hash, :et, :kf, 'rejected', :reason
            )
            """
        ),
        {
            "id": manifest_id,
            "tid": kwargs["tenant_id"],
            "pid": kwargs["portfolio_id"],
            "code": kwargs["contract_code"],
            "ver": kwargs["schema_version"],
            "src": kwargs["source"],
            "bd": kwargs["business_date"],
            "ref": kwargs["source_ref"],
            "cnt": kwargs["control_count"],
            "sum": kwargs["control_sum_paise"],
            "hash": kwargs["payload_hash"],
            "et": kwargs["event_time"],
            "kf": kwargs["known_from"],
            "reason": reason,
        },
    )
    _record_break(
        conn,
        tenant_id=kwargs["tenant_id"],
        portfolio_id=kwargs["portfolio_id"],
        contract_code=kwargs["contract_code"],
        business_date=kwargs["business_date"],
        kind=reason,
        detail=breaks[0] if breaks else {},
        manifest_id=manifest_id,
    )
    _touch_freshness(
        conn,
        tenant_id=kwargs["tenant_id"],
        portfolio_id=kwargs["portfolio_id"],
        contract_code=kwargs["contract_code"],
        known_from=kwargs["known_from"],
        business_date=kwargs["business_date"],
        matched=False,
    )
    return manifest_id


def _record_break(
    conn: Any,
    *,
    tenant_id: str,
    portfolio_id: str,
    contract_code: str,
    business_date: date,
    kind: str,
    detail: dict[str, Any],
    manifest_id: str | None = None,
) -> None:
    run_id = _id("BR")
    conn.execute(
        text(
            """
            INSERT INTO bank_reconciliation_runs (
              id, tenant_id, portfolio_id, contract_code, business_date,
              manifest_id, status, started_at, finished_at
            ) VALUES (
              :id, :tid, :pid, :code, :bd, :mid, 'break', now(), now()
            )
            """
        ),
        {
            "id": run_id,
            "tid": tenant_id,
            "pid": portfolio_id,
            "code": contract_code,
            "bd": business_date,
            "mid": manifest_id,
        },
    )
    conn.execute(
        text(
            """
            INSERT INTO bank_reconciliation_breaks (
              id, run_id, tenant_id, kind, detail
            ) VALUES (
              :id, :run, :tid, :kind, CAST(:detail AS jsonb)
            )
            """
        ),
        {
            "id": _id("BB"),
            "run": run_id,
            "tid": tenant_id,
            "kind": kind,
            "detail": json.dumps(detail, default=str),
        },
    )


def _finish_run(
    conn: Any,
    **kwargs: Any,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO bank_reconciliation_runs (
              id, tenant_id, portfolio_id, contract_code, business_date,
              manifest_id, status, observed_count, observed_sum_paise,
              control_count, control_sum_paise, started_at, finished_at
            ) VALUES (
              :id, :tid, :pid, :code, :bd, :mid, :status,
              :oc, :os, :cc, :cs, now(), now()
            )
            """
        ),
        {
            "id": _id("BR"),
            "tid": kwargs["tenant_id"],
            "pid": kwargs["portfolio_id"],
            "code": kwargs["contract_code"],
            "bd": kwargs["business_date"],
            "mid": kwargs["manifest_id"],
            "status": kwargs["status"],
            "oc": kwargs["observed_count"],
            "os": kwargs["observed_sum_paise"],
            "cc": kwargs["control_count"],
            "cs": kwargs["control_sum_paise"],
        },
    )


def _touch_freshness(
    conn: Any,
    *,
    tenant_id: str,
    portfolio_id: str,
    contract_code: str,
    known_from: datetime,
    business_date: date,
    matched: bool,
) -> None:
    prev = conn.execute(
        text(
            """
            SELECT consecutive_ok_days, last_business_date, last_accepted_at
              FROM bank_freshness
             WHERE tenant_id = :tid AND portfolio_id = :pid
               AND contract_code = :code
            """
        ),
        {"tid": tenant_id, "pid": portfolio_id, "code": contract_code},
    ).mappings().first()
    streak = 0
    if matched:
        streak = 1
        if prev and prev["last_business_date"]:
            if _next_business_date(prev["last_business_date"]) == business_date:
                streak = int(prev["consecutive_ok_days"] or 0) + 1
            elif business_date == prev["last_business_date"]:
                streak = int(prev["consecutive_ok_days"] or 1)
    conn.execute(
        text(
            """
            INSERT INTO bank_freshness (
              tenant_id, portfolio_id, contract_code,
              last_accepted_at, last_business_date, consecutive_ok_days, lag_hours
            ) VALUES (
              :tid, :pid, :code, :kf, :bd, :streak, 0
            )
            ON CONFLICT (tenant_id, portfolio_id, contract_code) DO UPDATE SET
              last_accepted_at = EXCLUDED.last_accepted_at,
              last_business_date = EXCLUDED.last_business_date,
              consecutive_ok_days = EXCLUDED.consecutive_ok_days,
              lag_hours = EXTRACT(EPOCH FROM (now() - EXCLUDED.last_accepted_at)) / 3600.0,
              updated_at = now()
            """
        ),
        {
            "tid": tenant_id,
            "pid": portfolio_id,
            "code": contract_code,
            "kf": known_from if matched else (prev["last_accepted_at"] if prev else None) or known_from,
            "bd": business_date,
            "streak": streak,
        },
    )
    if not matched:
        conn.execute(
            text(
                """
                UPDATE bank_freshness
                   SET consecutive_ok_days = 0, updated_at = now()
                 WHERE tenant_id = :tid AND portfolio_id = :pid
                   AND contract_code = :code
                """
            ),
            {"tid": tenant_id, "pid": portfolio_id, "code": contract_code},
        )


def _next_business_date(value: date) -> date:
    candidate = value + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


class _IdentityAdapter:
    def __init__(self, code: str) -> None:
        self.code = code

    def validate(self, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [dict(r) for r in rows]

    def apply(
        self,
        conn: Any,
        *,
        tenant_id: str,
        portfolio_id: str,
        rows: Sequence[Mapping[str, Any]],
        manifest_id: str,
        known_from: datetime,
    ) -> tuple[int, int]:
        total = sum(_paise(r) for r in rows)
        if self.code == "C1":
            _apply_c1(conn, tenant_id=tenant_id, rows=rows)
        elif self.code == "C2":
            _apply_c2(conn, tenant_id=tenant_id, rows=rows)
        elif self.code == "C3":
            _apply_c3(conn, tenant_id=tenant_id, rows=rows)
        elif self.code in {"C4", "C5"}:
            _apply_c4c5(conn, tenant_id=tenant_id, rows=rows, code=self.code)
        elif self.code == "C6":
            _apply_c6(conn, tenant_id=tenant_id, rows=rows)
        elif self.code == "C7":
            _apply_c7(
                conn,
                tenant_id=tenant_id,
                rows=rows,
                manifest_id=manifest_id,
                known_from=known_from,
            )
        elif self.code == "C8":
            _apply_c8(
                conn,
                tenant_id=tenant_id,
                rows=rows,
                manifest_id=manifest_id,
                known_from=known_from,
            )
        elif self.code == "C9":
            _apply_c9(
                conn,
                tenant_id=tenant_id,
                rows=rows,
                manifest_id=manifest_id,
                known_from=known_from,
            )
        elif self.code == "C10":
            _apply_c10(
                conn,
                tenant_id=tenant_id,
                rows=rows,
                manifest_id=manifest_id,
                known_from=known_from,
            )
        elif self.code == "F8":
            _apply_f8(
                conn,
                tenant_id=tenant_id,
                rows=rows,
                manifest_id=manifest_id,
                known_from=known_from,
            )
        return len(rows), total


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
    token = hashlib.sha256(
        f"{tenant_id}\0{namespace}\0{external_id}".encode("utf-8")
    ).hexdigest()[:20].upper()
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


_ADAPTERS: dict[str, ContractAdapter] = {
    code: _IdentityAdapter(code)
    for code in ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "F8")
}
