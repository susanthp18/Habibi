"""W6 daily snapshots, delta-overlay serving, PIT audits, and cost rollups."""

from __future__ import annotations

import json
import tempfile
import uuid
from dataclasses import asdict, fields, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import text

from agent_core.clock import as_utc
from agent_core.treatment.features import (
    AccountFeatures,
    SCHEMA_VERSION,
    SqlFeatureProvider,
    Trigger,
)
from agent_core.treatment.policy import STALE_SNAPSHOT as _STALE_SNAPSHOT
from env_utils import NON_PROD_ENVS, env_int, env_name

#: Re-exported, not restated. ``policy.py`` is the one place that decides what a
#: stale input *does*, so the string it vetoes on and the string this module
#: raises must be the same object rather than two spellings that can drift.
STALE_SNAPSHOT = _STALE_SNAPSHOT
SNAPSHOT_MAX_AGE = timedelta(hours=4)
DEFAULT_LAG_BYTES = 16 * 1024 * 1024


class SnapshotUnavailable(RuntimeError):
    """Layer 0 is active but no safe snapshot can serve this decision."""


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def snapshot_vector(features: AccountFeatures) -> dict[str, Any]:
    return _jsonable(asdict(features))


_DATE_FIELDS = {"mandate_cycle"}
_DATETIME_FIELDS = {
    "next_credit_at",
    "mandate_last_presented_at",
    "last_touch_at",
    "last_connect_at",
    "last_inbound_at",
    "legal_notice_at",
}
_TUPLE_FIELDS = {
    "responsive_hours",
    "allowed_days",
    "holds",
    "holds_of_record",
    "speech_flags",
    "stale_inputs",
}


def features_from_snapshot(vector: dict[str, Any]) -> AccountFeatures:
    allowed = {item.name for item in fields(AccountFeatures)}
    values = {key: value for key, value in vector.items() if key in allowed}
    for key in _DATE_FIELDS:
        value = values.get(key)
        if isinstance(value, str) and value:
            values[key] = date.fromisoformat(value)
    for key in _DATETIME_FIELDS:
        value = values.get(key)
        if isinstance(value, str) and value:
            values[key] = as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    for key in _TUPLE_FIELDS:
        value = values.get(key)
        if isinstance(value, list):
            values[key] = tuple(value)
    return AccountFeatures(**values)


class SnapshotFeatureProvider:
    """Serve one daily vector plus payment, consent, and protection deltas."""

    def build(
        self,
        customer_id: str,
        *,
        account_id: str | None,
        trigger: Trigger,
        now: datetime,
        conn: Any | None = None,
    ) -> AccountFeatures:
        if conn is None:
            raise SnapshotUnavailable("snapshot_provider_requires_connection")
        row = conn.execute(
            text(
                """
                WITH snapshot AS (
                  SELECT s.*
                    FROM feature_snapshot_daily s
                   WHERE s.customer_id = :cid
                     AND (CAST(:aid AS TEXT) IS NULL OR s.account_id = :aid)
                     AND s.feature_schema_version = :version
                     AND s.as_of_date <= (:now AT TIME ZONE 'Asia/Kolkata')::date
                   ORDER BY s.as_of_date DESC, s.known_from DESC
                   LIMIT 1
                )
                SELECT s.vector, s.known_from, s.snapshot_as_of, s.build_id,
                       s.as_of_date,
                       COALESCE((
                         SELECT sum(p.amount_paise)
                           FROM fct_payment p
                          WHERE p.tenant_id = s.tenant_id
                            AND p.account_id = s.account_id
                            AND p.known_from > s.known_from
                            AND p.known_from <= :now
                       ), 0)::bigint AS payment_delta_paise,
                       COALESCE((
                         SELECT jsonb_object_agg(latest.channel, latest.permitted)
                           FROM (
                             SELECT DISTINCT ON (c.channel)
                                    c.channel, c.permitted
                               FROM fct_consent c
                              WHERE c.tenant_id = s.tenant_id
                                AND c.customer_id = s.customer_id
                                AND c.known_from > s.known_from
                                AND c.known_from <= :now
                              ORDER BY c.channel, c.known_from DESC
                           ) latest
                       ), '{}'::jsonb) AS consent_delta,
                       COALESCE((
                         SELECT array_agg(p.kind ORDER BY p.kind)
                           FROM fct_protection p
                          WHERE p.tenant_id = s.tenant_id
                            AND p.customer_id = s.customer_id
                            AND (p.account_id IS NULL OR p.account_id = s.account_id)
                            AND p.active IS TRUE
                            AND p.known_from > s.known_from
                            AND p.known_from <= :now
                       ), ARRAY[]::text[]) AS protection_delta
                  FROM snapshot s
                """
            ),
            {
                "cid": customer_id,
                "aid": account_id,
                "version": SCHEMA_VERSION,
                "now": now,
            },
        ).mappings().first()
        if row is None:
            # §7.8: freshness is a policy state, not an exception. A missing
            # snapshot is the maximally-stale case, not a different case, and an
            # exception here reaches ``engine._recommend`` as a generic failure
            # -- silence, on every account with no snapshot row, which is the
            # whole book the day 0113 lands. Serve from SQL and declare the
            # staleness instead; ``policy.py:154`` already vetoes every
            # contacting action on ``stale_snapshot`` and leaves the
            # non-contacting ones (``represent_mandate``) admissible, which is
            # exactly the row §7.8 specifies.
            served = SqlFeatureProvider().build(
                customer_id, account_id=account_id, trigger=trigger, now=now, conn=conn
            )
            return replace(
                served,
                stale_inputs=tuple(sorted(set(served.stale_inputs) | {STALE_SNAPSHOT})),
            )
        vector = dict(row["vector"] or {})
        features = features_from_snapshot(vector)
        payment_rupees = int(row["payment_delta_paise"] or 0) / 100.0
        consent = dict(features.consent_by_channel)
        for channel, permitted in dict(row["consent_delta"] or {}).items():
            consent[str(channel)] = "active" if permitted else "withdrawn"
        holds = tuple(
            sorted(set(features.holds) | {str(v) for v in row["protection_delta"] or []})
        )
        stale = set(features.stale_inputs)
        known = as_utc(row["known_from"])
        if known is None or now - known > SNAPSHOT_MAX_AGE:
            stale.add(STALE_SNAPSHOT)
        return AccountFeatures(
            **{
                **asdict(features),
                "outstanding": (
                    None
                    if features.outstanding is None
                    else max(0.0, features.outstanding - payment_rupees)
                ),
                "minimum_due": (
                    None
                    if features.minimum_due is None
                    else max(0.0, features.minimum_due - payment_rupees)
                ),
                "instalment_amount": (
                    None
                    if features.instalment_amount is None
                    else max(0.0, features.instalment_amount - payment_rupees)
                ),
                "consent_by_channel": consent,
                "holds": holds,
                "stale_inputs": tuple(sorted(stale)),
                "snapshot_build_id": str(row["build_id"]),
                "snapshot_date": row["as_of_date"],
                "features_known_ts": known,
            }
        )


def _lsn(conn: Any, expression: str) -> str | None:
    value = conn.execute(text(f"SELECT {expression}")).scalar()
    return str(value) if value is not None else None


def _chunks(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for offset in range(0, len(rows), size):
        yield rows[offset : offset + size]


def build_daily_snapshot(
    source_conn: Any,
    sink_conn: Any,
    *,
    tenant_id: str,
    portfolio_id: str = "",
    as_of_date: date,
    source_kind: str,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Build on a reporting source, persist Parquet, then load the primary."""
    if source_kind not in {"reporting", "scratch"}:
        raise ValueError("invalid_snapshot_source")
    if source_kind != "reporting" and env_name() not in NON_PROD_ENVS:
        raise RuntimeError("production_snapshot_requires_reporting_source")
    primary_lsn = _lsn(sink_conn, "pg_current_wal_flush_lsn()")
    source_lsn = (
        _lsn(source_conn, "pg_last_wal_replay_lsn()")
        if source_kind == "reporting"
        else primary_lsn
    )
    if source_kind == "reporting" and source_lsn is None:
        raise RuntimeError("reporting_source_is_not_standby")
    lag_bytes = int(
        sink_conn.execute(
            text("SELECT pg_wal_lsn_diff(CAST(:primary AS pg_lsn), CAST(:source AS pg_lsn))"),
            {"primary": primary_lsn, "source": source_lsn},
        ).scalar()
        or 0
    )
    max_lag = max(0, env_int("W6_MAX_REPLICA_LAG_BYTES", DEFAULT_LAG_BYTES))
    if lag_bytes > max_lag:
        raise RuntimeError(f"reporting_replica_lag:{lag_bytes}")

    build_id = f"FSB-{uuid.uuid4().hex[:16].upper()}"
    started = datetime.now(timezone.utc)
    sink_conn.execute(
        text(
            """
            INSERT INTO feature_snapshot_builds (
              id, tenant_id, portfolio_id, as_of_date, feature_schema_version,
              source_kind, source_lsn, primary_flush_lsn, replica_lag_bytes,
              state, started_at
            ) VALUES (
              :id, :tid, :pid, :day, :version, :kind,
              CAST(:source_lsn AS pg_lsn), CAST(:primary_lsn AS pg_lsn),
              :lag, 'started', :started
            )
            ON CONFLICT (
              tenant_id, portfolio_id, as_of_date, feature_schema_version
            ) DO UPDATE SET
              source_kind = EXCLUDED.source_kind,
              source_lsn = EXCLUDED.source_lsn,
              primary_flush_lsn = EXCLUDED.primary_flush_lsn,
              replica_lag_bytes = EXCLUDED.replica_lag_bytes,
              state = 'started',
              started_at = EXCLUDED.started_at,
              finished_at = NULL,
              error = NULL
            RETURNING id
            """
        ),
        {
            "id": build_id,
            "tid": tenant_id,
            "pid": portfolio_id,
            "day": as_of_date,
            "version": SCHEMA_VERSION,
            "kind": source_kind,
            "source_lsn": source_lsn,
            "primary_lsn": primary_lsn,
            "lag": lag_bytes,
            "started": started,
        },
    )
    stored_build_id = sink_conn.execute(
        text(
            """
            SELECT id FROM feature_snapshot_builds
             WHERE tenant_id = :tid AND portfolio_id = :pid
               AND as_of_date = :day AND feature_schema_version = :version
            """
        ),
        {
            "tid": tenant_id,
            "pid": portfolio_id,
            "day": as_of_date,
            "version": SCHEMA_VERSION,
        },
    ).scalar_one()
    now = datetime.combine(as_of_date, datetime.min.time(), tzinfo=timezone.utc)
    accounts = source_conn.execute(
        text(
            """
            SELECT a.id, a.customer_id
              FROM accounts a JOIN customers c ON c.id = a.customer_id
             WHERE c.tenant_id = :tid AND a.status = 'active'
             ORDER BY a.id
            """
        ),
        {"tid": tenant_id},
    ).mappings().all()
    provider = SqlFeatureProvider()
    rows: list[dict[str, Any]] = []
    for account in accounts:
        features = provider.build(
            str(account["customer_id"]),
            account_id=str(account["id"]),
            trigger=Trigger(kind="dpd_tick", at=now, ref=as_of_date.isoformat()),
            now=now,
            conn=source_conn,
        )
        rows.append(
            {
                "tenant_id": tenant_id,
                "portfolio_id": portfolio_id,
                "as_of_date": as_of_date.isoformat(),
                "account_id": str(account["id"]),
                "customer_id": str(account["customer_id"]),
                "feature_schema_version": SCHEMA_VERSION,
                "vector": snapshot_vector(features),
                "snapshot_as_of": now.isoformat(),
                "known_from": started.isoformat(),
                "build_id": str(stored_build_id),
                "built_from_lsn": source_lsn,
                "primary_flush_lsn": primary_lsn,
                "replica_lag_bytes": lag_bytes,
                "stale_inputs": [],
            }
        )

    target_dir = output_dir or Path(tempfile.mkdtemp(prefix="w6-snapshot-"))
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / f"{stored_build_id}.jsonl"
    parquet_path = target_dir / f"{stored_build_id}.parquet"
    with json_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, default=str, sort_keys=True) + "\n")
    import duckdb

    with duckdb.connect() as local:
        local.execute(
            "COPY (SELECT * FROM read_json_auto(?)) TO ? (FORMAT PARQUET)",
            [str(json_path), str(parquet_path)],
        )
        parquet_count = int(
            local.execute("SELECT count(*) FROM read_parquet(?)", [str(parquet_path)]).fetchone()[0]
        )
    if parquet_count != len(rows):
        raise RuntimeError("parquet_row_count_mismatch")

    insert_rows = [
        {
            **row,
            "vector": json.dumps(row["vector"], default=str, sort_keys=True),
            "stale_inputs": row["stale_inputs"],
        }
        for row in rows
    ]
    for chunk in _chunks(insert_rows, 500):
        sink_conn.execute(
            text(
                """
                INSERT INTO feature_snapshot_daily (
                  tenant_id, portfolio_id, as_of_date, account_id, customer_id,
                  feature_schema_version, vector, snapshot_as_of, known_from,
                  build_id, built_from_lsn, primary_flush_lsn,
                  replica_lag_bytes, stale_inputs
                ) VALUES (
                  :tenant_id, :portfolio_id, :as_of_date, :account_id, :customer_id,
                  :feature_schema_version, CAST(:vector AS jsonb), :snapshot_as_of,
                  :known_from, :build_id, CAST(:built_from_lsn AS pg_lsn),
                  CAST(:primary_flush_lsn AS pg_lsn), :replica_lag_bytes, :stale_inputs
                )
                ON CONFLICT (
                  tenant_id, portfolio_id, as_of_date, account_id,
                  feature_schema_version
                ) DO UPDATE SET
                  vector = EXCLUDED.vector,
                  snapshot_as_of = EXCLUDED.snapshot_as_of,
                  known_from = EXCLUDED.known_from,
                  build_id = EXCLUDED.build_id,
                  built_from_lsn = EXCLUDED.built_from_lsn,
                  primary_flush_lsn = EXCLUDED.primary_flush_lsn,
                  replica_lag_bytes = EXCLUDED.replica_lag_bytes,
                  stale_inputs = EXCLUDED.stale_inputs
                """
            ),
            chunk,
        )
    size = parquet_path.stat().st_size
    sink_conn.execute(
        text(
            """
            UPDATE feature_snapshot_builds
               SET row_count = :rows, parquet_bytes = :bytes,
                   state = 'loaded', finished_at = now()
             WHERE id = :id
            """
        ),
        {"id": stored_build_id, "rows": len(rows), "bytes": size},
    )
    return {
        "id": str(stored_build_id),
        "rows": len(rows),
        "parquet": str(parquet_path),
        "parquet_bytes": size,
        "source_lsn": source_lsn,
        "primary_flush_lsn": primary_lsn,
        "replica_lag_bytes": lag_bytes,
    }


def rollup_decision_costs(source_conn: Any, sink_conn: Any, *, usage_date: date) -> int:
    """Read metering from reporting and replace one day's primary rollup."""
    rows = source_conn.execute(
        text(
            """
            SELECT tenant_id, decision_id, sum(units) AS units,
                   sum(cost_inr) AS cost_inr, count(*)::bigint AS event_count
              FROM usage_events
             WHERE decision_id IS NOT NULL
               AND occurred_at >= :start
               AND occurred_at < :finish
             GROUP BY tenant_id, decision_id
            """
        ),
        {
            "start": datetime.combine(usage_date, datetime.min.time(), tzinfo=timezone.utc),
            "finish": datetime.combine(
                usage_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
            ),
        },
    ).mappings().all()
    lsn = _lsn(source_conn, "pg_last_wal_replay_lsn()")
    for chunk in _chunks([dict(row) for row in rows], 500):
        sink_conn.execute(
            text(
                """
                INSERT INTO decision_cost_rollup_daily (
                  tenant_id, usage_date, decision_id, units, cost_inr,
                  event_count, built_from_lsn
                ) VALUES (
                  :tenant_id, :usage_date, :decision_id, :units, :cost_inr,
                  :event_count, CAST(:lsn AS pg_lsn)
                )
                ON CONFLICT (tenant_id, usage_date, decision_id) DO UPDATE SET
                  units = EXCLUDED.units,
                  cost_inr = EXCLUDED.cost_inr,
                  event_count = EXCLUDED.event_count,
                  built_from_lsn = EXCLUDED.built_from_lsn
                """
            ),
            [{**row, "usage_date": usage_date, "lsn": lsn} for row in chunk],
        )
    return len(rows)


_MONEY_KEYS = {"outstanding", "minimumDue", "instalmentAmount", "exposure"}


def _comparable(vector: dict[str, Any]) -> dict[str, Any]:
    compared: dict[str, Any] = {}
    for key, value in vector.items():
        if key in _MONEY_KEYS and value is not None:
            compared[key] = int(round(float(value) * 100))
        elif isinstance(value, float):
            compared[key] = round(value, 9)
        else:
            compared[key] = value
    return compared


def run_pit_skew(
    source_conn: Any,
    sink_conn: Any,
    *,
    tenant_id: str,
    sampled_from: datetime,
    sampled_to: datetime,
    source_kind: str,
    sample_percent: int = 1,
) -> dict[str, Any]:
    """Recompute a deterministic decision sample and record, never repair, skew."""
    if source_kind != "reporting" and env_name() not in NON_PROD_ENVS:
        raise RuntimeError("production_pit_requires_reporting_source")
    rate = max(1, min(100, int(sample_percent)))
    run_id = f"PIT-{uuid.uuid4().hex[:16].upper()}"
    sink_conn.execute(
        text(
            """
            INSERT INTO feature_pit_skew_runs (
              id, tenant_id, sampled_from, sampled_to, state, source_kind
            ) VALUES (:id, :tid, :start, :finish, 'started', :kind)
            """
        ),
        {
            "id": run_id,
            "tid": tenant_id,
            "start": sampled_from,
            "finish": sampled_to,
            "kind": source_kind,
        },
    )
    rows = source_conn.execute(
        text(
            """
            SELECT id, customer_id, account_id, trigger_kind, trigger_ref,
                   event_at, created_at, features
              FROM treatment_decisions
             WHERE tenant_id = :tid
               AND feature_snapshot_build_id IS NOT NULL
               AND created_at >= :start AND created_at < :finish
               AND mode <> 'simulated'
               AND mod(
                 abs(('x' || substr(md5(id), 1, 8))::bit(32)::bigint),
                 100
               ) < :rate
             ORDER BY id
            """
        ),
        {
            "tid": tenant_id,
            "start": sampled_from,
            "finish": sampled_to,
            "rate": rate,
        },
    ).mappings().all()
    mismatches = 0
    provider = SnapshotFeatureProvider()
    for row in rows:
        decision_at = as_utc(row["created_at"]) or sampled_to
        trigger = Trigger(
            kind=str(row["trigger_kind"]),
            at=as_utc(row["event_at"]),
            ref=row["trigger_ref"],
        )
        observed = provider.build(
            str(row["customer_id"]),
            account_id=str(row["account_id"]) if row["account_id"] else None,
            trigger=trigger,
            now=decision_at,
            conn=source_conn,
        ).to_log()
        expected_full = dict(row["features"] or {})
        expected = {key: expected_full.get(key) for key in observed}
        left = _comparable(expected)
        right = _comparable(observed)
        differing = sorted(
            key for key in set(left) | set(right) if left.get(key) != right.get(key)
        )
        if not differing:
            continue
        mismatches += 1
        sink_conn.execute(
            text(
                """
                INSERT INTO feature_pit_skew_mismatches (
                  id, tenant_id, run_id, decision_id, expected_vector,
                  observed_vector, differing_keys
                ) VALUES (
                  :id, :tid, :run, :decision, CAST(:expected AS jsonb),
                  CAST(:observed AS jsonb), :keys
                )
                ON CONFLICT (run_id, decision_id) DO NOTHING
                """
            ),
            {
                "id": f"PIM-{uuid.uuid4().hex[:16].upper()}",
                "tid": tenant_id,
                "run": run_id,
                "decision": row["id"],
                "expected": json.dumps(left, default=str, sort_keys=True),
                "observed": json.dumps(right, default=str, sort_keys=True),
                "keys": differing,
            },
        )
    state = "green" if mismatches == 0 else "red"
    sink_conn.execute(
        text(
            """
            UPDATE feature_pit_skew_runs
               SET sample_count = :sample, mismatch_count = :mismatch,
                   state = :state, finished_at = now()
             WHERE id = :id
            """
        ),
        {
            "id": run_id,
            "sample": len(rows),
            "mismatch": mismatches,
            "state": state,
        },
    )
    return {
        "id": run_id,
        "sample_count": len(rows),
        "mismatch_count": mismatches,
        "state": state,
    }


def build_training_asof(
    *,
    decisions_parquet: Path,
    facts_parquet: Path,
    output_parquet: Path,
) -> int:
    """Build a DuckDB ASOF LEFT JOIN training set from air-gapped Parquet."""
    import duckdb

    with duckdb.connect() as local:
        local.execute(
            """
            COPY (
              SELECT d.*, f.* EXCLUDE (tenant_id, account_id, known_from)
                FROM read_parquet(?) d
                ASOF LEFT JOIN read_parquet(?) f
                  ON d.tenant_id = f.tenant_id
                 AND d.account_id = f.account_id
                 AND d.created_at >= f.known_from
            ) TO ? (FORMAT PARQUET)
            """,
            [str(decisions_parquet), str(facts_parquet), str(output_parquet)],
        )
        return int(
            local.execute(
                "SELECT count(*) FROM read_parquet(?)", [str(output_parquet)]
            ).fetchone()[0]
        )
