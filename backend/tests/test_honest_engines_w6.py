"""W6 decision-substrate contracts: temporal facts, snapshots, and attribution."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from agent_core.treatment import actions as A
from agent_core.treatment import config, policy, schema_ready
from agent_core.treatment.features import AccountFeatures, SqlFeatureProvider, Trigger
from agent_core.treatment.substrate import (
    SnapshotFeatureProvider,
    snapshot_vector,
)
from bank_boundary import bootstrap, ingest
from bank_boundary.facts import SHARD_COUNT, SHARD_VERSION, shard_key
from bank_boundary.ingest import IngestRejected

BACKEND = Path(__file__).resolve().parents[1]
SQL_25 = BACKEND / "sql" / "25_decision_substrate.sql"


@pytest.fixture(autouse=True)
def _reset_schema_cache():
    schema_ready.reset_cache()
    yield
    schema_ready.reset_cache()


def _w6(conn) -> None:
    bootstrap.ensure(conn)
    if not schema_ready.w6_ready(conn):
        conn.exec_driver_sql(SQL_25.read_text(encoding="utf-8"))
        schema_ready.reset_cache()


def _identity(conn) -> tuple[str, dict[str, str]]:
    row = conn.execute(
        text(
            """
            SELECT c.tenant_id, c.id AS customer_id, a.id AS account_id
              FROM customers c JOIN accounts a ON a.customer_id = c.id
             WHERE a.status = 'active'
             ORDER BY a.id
             LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("no seeded account")
    return str(row["tenant_id"]), {
        "customer_id": str(row["customer_id"]),
        "account_id": str(row["account_id"]),
    }


def _load_c1(
    conn,
    *,
    tenant: str,
    account_id: str,
    source_ref: str,
    valid_from: datetime,
    known_from: datetime,
    outstanding_paise: int,
) -> dict:
    return ingest.load(
        conn,
        tenant_id=tenant,
        contract_code="C1",
        schema_version="bank-boundary.v1",
        source="w6-test",
        business_date=valid_from.date(),
        source_ref=source_ref,
        control_count=1,
        control_sum_paise=outstanding_paise,
        event_time=valid_from,
        known_from=known_from,
        rows=[
            {
                "external_id": account_id,
                "source_row_id": source_ref,
                "outstanding_paise": outstanding_paise,
                "status": "active",
                "valid_from": valid_from,
            }
        ],
    )


def test_pg16_schema_uses_tenant_leading_gist_and_single_head() -> None:
    sql = SQL_25.read_text(encoding="utf-8")
    assert "EXCLUDE USING gist" in sql
    assert "tenant_id WITH =, fact_key WITH =, valid_at WITH &&" in sql
    assert all(
        "WITHOUT OVERLAPS" not in line
        for line in sql.splitlines()
        if not line.lstrip().startswith("--")
    )
    migration = (
        BACKEND / "alembic" / "versions" / "20260908_0113_decision_substrate.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision: Union[str, None] = "20260906_0112"' in migration
    assert "sql/25_decision_substrate.sql" in migration


def test_stable_shard_key_is_tenant_scoped_and_versioned() -> None:
    one = shard_key("tenant-a", "loan-1")
    assert one == shard_key("tenant-a", "loan-1")
    assert one != shard_key("tenant-b", "loan-1")
    assert 0 <= one < SHARD_COUNT
    with pytest.raises(ValueError, match="unsupported_shard_version"):
        shard_key("tenant-a", "loan-1", version=SHARD_VERSION + 1)


def test_manifest_projection_is_atomic_and_preserves_late_knowledge(db_tx) -> None:
    _w6(db_tx)
    tenant, ids = _identity(db_tx)
    now = datetime.now(timezone.utc)
    first_valid = now - timedelta(days=2)
    second_valid = now - timedelta(days=1)
    first = _load_c1(
        db_tx,
        tenant=tenant,
        account_id=ids["account_id"],
        source_ref="w6-first",
        valid_from=first_valid,
        known_from=now,
        outstanding_paise=10000,
    )
    second = _load_c1(
        db_tx,
        tenant=tenant,
        account_id=ids["account_id"],
        source_ref="w6-late",
        valid_from=second_valid,
        known_from=now + timedelta(microseconds=1),
        outstanding_paise=9000,
    )
    rows = db_tx.execute(
        text(
            """
            SELECT source_manifest_id, lower(valid_at) AS valid_from,
                   upper(valid_at) AS valid_to, known_from
              FROM fct_loan_state
             WHERE tenant_id = :tid AND account_id = :aid
               AND source_manifest_id IN (:first, :second)
             ORDER BY lower(valid_at)
            """
        ),
        {
            "tid": tenant,
            "aid": ids["account_id"],
            "first": first["id"],
            "second": second["id"],
        },
    ).mappings().all()
    assert len(rows) == 2
    assert rows[0]["valid_to"] == second_valid
    assert rows[0]["known_from"] == now
    assert rows[1]["known_from"] == now + timedelta(microseconds=1)


def test_temporal_overlap_is_refused(db_tx) -> None:
    _w6(db_tx)
    tenant, ids = _identity(db_tx)
    now = datetime.now(timezone.utc)
    manifest = _load_c1(
        db_tx,
        tenant=tenant,
        account_id=ids["account_id"],
        source_ref="w6-overlap-source",
        valid_from=now - timedelta(days=2),
        known_from=now,
        outstanding_paise=10000,
    )
    savepoint = db_tx.begin_nested()
    with pytest.raises(IntegrityError):
        db_tx.execute(
            text(
                """
                INSERT INTO fct_loan_state (
                  id, tenant_id, portfolio_id, fact_key, account_id,
                  external_loan_id, valid_at, known_from,
                  source_manifest_id, source_row_id
                ) VALUES (
                  'W6-overlap', :tid, '', :key, :aid, :aid,
                  tstzrange(:start, NULL, '[)'), :known,
                  :manifest, 'overlap-direct'
                )
                """
            ),
            {
                "tid": tenant,
                "key": f"loan:{ids['account_id']}",
                "aid": ids["account_id"],
                "start": now - timedelta(days=1),
                "known": now,
                "manifest": manifest["id"],
            },
        )
    savepoint.rollback()


def test_snapshot_plus_payment_delta_matches_integer_paise(db_tx) -> None:
    _w6(db_tx)
    tenant, ids = _identity(db_tx)
    now = datetime.now(timezone.utc)
    legacy = SqlFeatureProvider().build(
        ids["customer_id"],
        account_id=ids["account_id"],
        trigger=Trigger(kind="manual"),
        now=now,
        conn=db_tx,
    )
    build_id = "FSB-W6-DELTA"
    db_tx.execute(
        text(
            """
            INSERT INTO feature_snapshot_builds (
              id, tenant_id, portfolio_id, as_of_date, feature_schema_version,
              source_kind, state, started_at, finished_at
            ) VALUES (
              :id, :tid, '', :day, :version, 'scratch', 'loaded', :now, :now
            )
            """
        ),
        {
            "id": build_id,
            "tid": tenant,
            "day": now.date(),
            "version": legacy.schema_version,
            "now": now,
        },
    )
    db_tx.execute(
        text(
            """
            INSERT INTO feature_snapshot_daily (
              tenant_id, portfolio_id, as_of_date, account_id, customer_id,
              feature_schema_version, vector, snapshot_as_of, known_from, build_id
            ) VALUES (
              :tid, '', :day, :aid, :cid, :version,
              CAST(:vector AS jsonb), :now, :now, :build
            )
            """
        ),
        {
            "tid": tenant,
            "day": now.date(),
            "aid": ids["account_id"],
            "cid": ids["customer_id"],
            "version": legacy.schema_version,
            "vector": json.dumps(snapshot_vector(legacy), default=str),
            "now": now,
            "build": build_id,
        },
    )
    payment_known = now + timedelta(seconds=1)
    ingest.load(
        db_tx,
        tenant_id=tenant,
        contract_code="C6",
        schema_version="bank-boundary.v1",
        source="w6-test",
        business_date=now.date(),
        source_ref="w6-delta-payment",
        control_count=1,
        control_sum_paise=123,
        event_time=now,
        known_from=payment_known,
        rows=[
            {
                "external_id": "W6-PAYMENT-DELTA",
                "source_row_id": "payment-delta",
                "account_external_id": ids["account_id"],
                "amount_paise": 123,
                "posted_at": now,
            }
        ],
    )
    served = SnapshotFeatureProvider().build(
        ids["customer_id"],
        account_id=ids["account_id"],
        trigger=Trigger(kind="manual"),
        now=payment_known + timedelta(seconds=1),
        conn=db_tx,
    )
    if legacy.outstanding is not None:
        assert round((legacy.outstanding - served.outstanding) * 100) == 123
    assert served.snapshot_build_id == build_id
    assert served.features_known_ts == now


def test_stale_snapshot_suppresses_contacting_only() -> None:
    features = AccountFeatures(
        customer_id="c",
        tenant_id="t",
        account_id="a",
        outstanding=1000,
        dpd=30,
        has_phone=True,
        stale_inputs=("stale_snapshot",),
    )
    reason = policy.veto(
        None,
        action=A.SMS,
        features=features,
        trigger=Trigger(kind="manual"),
        at=datetime.now(timezone.utc),
        policy=config.policy(),
        last_rung=0,
    )
    assert reason == "stale_snapshot"
    assert (
        policy.veto(
            None,
            action=A.WAIT,
            features=features,
            trigger=Trigger(kind="manual"),
            at=datetime.now(timezone.utc),
            policy=config.policy(),
            last_rung=0,
        )
        is None
    )


def test_paid_since_decision_reads_bitemporal_payment(db_tx) -> None:
    from agent_core.treatment.enact import _paid_since_decision

    _w6(db_tx)
    tenant, ids = _identity(db_tx)
    decided_at = datetime.now(timezone.utc) - timedelta(seconds=2)
    paid_at = decided_at + timedelta(seconds=1)
    ingest.load(
        db_tx,
        tenant_id=tenant,
        contract_code="C6",
        schema_version="bank-boundary.v1",
        source="w6-test",
        business_date=paid_at.date(),
        source_ref="paid-since-decision",
        control_count=1,
        control_sum_paise=100,
        event_time=paid_at,
        known_from=paid_at,
        rows=[
            {
                "external_id": "W6-PAID-SINCE",
                "source_row_id": "paid-since",
                "account_external_id": ids["account_id"],
                "amount_paise": 100,
                "posted_at": paid_at,
            }
        ],
    )
    assert _paid_since_decision(
        db_tx,
        {"account_id": ids["account_id"], "created_at": decided_at},
    )


def test_sweep_and_usage_schema_carry_typed_decision_links(db_tx) -> None:
    _w6(db_tx)
    constraints = {
        row["conname"]
        for row in db_tx.execute(
            text(
                """
                SELECT conname FROM pg_constraint
                 WHERE conrelid IN (
                   'treatment_sweep_claims'::regclass,
                   'usage_events'::regclass
                 ) AND contype = 'f'
                """
            )
        ).mappings()
    }
    assert any("decision" in name for name in constraints)
    assert db_tx.execute(
        text(
            """
            SELECT count(*) FROM pg_constraint
             WHERE conname = 'uq_treatment_sweep_account_day'
            """
        )
    ).scalar() == 1


def test_failed_fact_projection_rejects_manifest_and_rolls_back_canonical(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bank_boundary import facts

    _w6(db_tx)
    tenant, ids = _identity(db_tx)
    before = db_tx.execute(
        text("SELECT outstanding FROM accounts WHERE id = :id"),
        {"id": ids["account_id"]},
    ).scalar()
    monkeypatch.setattr(
        facts,
        "project_manifest",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fact-failed")),
    )
    now = datetime.now(timezone.utc)
    with pytest.raises(IngestRejected, match="validation"):
        _load_c1(
            db_tx,
            tenant=tenant,
            account_id=ids["account_id"],
            source_ref="w6-fact-failure",
            valid_from=now,
            known_from=now,
            outstanding_paise=7654,
        )
    after = db_tx.execute(
        text("SELECT outstanding FROM accounts WHERE id = :id"),
        {"id": ids["account_id"]},
    ).scalar()
    rejected = db_tx.execute(
        text(
            """
            SELECT state FROM bank_inbound_manifests
             WHERE tenant_id = :tid AND source_ref = 'w6-fact-failure'
            """
        ),
        {"tid": tenant},
    ).scalar()
    assert after == before
    assert rejected == "rejected"


def _second_tenant_account(conn, first_tenant: str, first_account: str) -> tuple[str, str]:
    tenants = [
        str(item)
        for item in conn.execute(text("SELECT id FROM tenants ORDER BY id")).scalars().all()
    ]
    other = next((item for item in tenants if item != first_tenant), None)
    product = conn.execute(text("SELECT id FROM products LIMIT 1")).scalar()
    if product is None:
        pytest.skip("no product")
    if other is None:
        other = "w6-isolation-tenant"
        conn.execute(
            text("INSERT INTO tenants (id, name) VALUES (:id, 'W6 isolation')"),
            {"id": other},
        )
    row = conn.execute(
        text(
            """
            SELECT a.id
              FROM accounts a JOIN customers c ON c.id = a.customer_id
             WHERE c.tenant_id = :tid AND a.id <> :aid AND a.status = 'active'
             ORDER BY a.id LIMIT 1
            """
        ),
        {"tid": other, "aid": first_account},
    ).scalar()
    if row:
        return other, str(row)
    cid = f"W6C-{other}"[:40]
    aid = f"W6A-{other}"[:40]
    from tests.conftest import acting_as

    with acting_as(conn, other):
        conn.execute(
            text(
                """
                INSERT INTO customers_pii (id, tenant_id, name, risk, phone_primary_enc, phone_primary_hmac)
                VALUES (:id, :tid, 'W6 borrower', 'medium', pii_encrypt('9999999998'), pii_phone_hmac('9999999998'))
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": cid, "tid": other},
        )
        conn.execute(
            text(
                """
                INSERT INTO accounts (id, customer_id, product_id, outstanding, dpd, status)
                VALUES (:id, :cid, :pid, 1000, 15, 'active')
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": aid, "cid": cid, "pid": product},
        )
    return other, aid


def test_colliding_external_loan_id_is_tenant_scoped(db_tx) -> None:
    _w6(db_tx)
    tenant, ids = _identity(db_tx)
    other_tenant, other_account = _second_tenant_account(db_tx, tenant, ids["account_id"])
    now = datetime.now(timezone.utc)
    loan_id = "LOAN-SHARED"
    from tests.conftest import acting_as

    for tenant_id, account_id, fact_id in (
        (tenant, ids["account_id"], "W6-loan-a"),
        (other_tenant, other_account, "W6-loan-b"),
    ):
          with acting_as(db_tx, tenant_id):
            manifest = db_tx.execute(
                text(
                    """
                    INSERT INTO bank_inbound_manifests (
                      id, tenant_id, portfolio_id, contract_code, schema_version,
                      source, business_date, source_ref, control_count, control_sum_paise,
                      payload_hash, event_time, known_from, state
                    ) VALUES (
                      :id, :tid, '', 'C1', 'bank-boundary.v1', 'w6-test', :day,
                      :ref, 1, 1, :hash, :now, :now, 'accepted'
                    )
                    RETURNING id
                    """
                ),
                {
                    "id": f"BM-{fact_id}",
                    "tid": tenant_id,
                    "day": now.date(),
                    "ref": fact_id,
                    "hash": f"sha256:{fact_id}",
                    "now": now,
                },
            ).scalar_one()
            db_tx.execute(
                text(
                    """
                    INSERT INTO fct_loan_state (
                      id, tenant_id, portfolio_id, fact_key, account_id,
                      external_loan_id, valid_at, known_from,
                      source_manifest_id, source_row_id
                    ) VALUES (
                      :id, :tid, '', :key, :aid, :loan,
                      tstzrange(:now, NULL, '[)'), :now, :manifest, 'shared'
                    )
                    """
                ),
                {
                    "id": fact_id,
                    "tid": tenant_id,
                    "key": f"loan:{account_id}",
                    "aid": account_id,
                    "loan": loan_id,
                    "now": now,
                    "manifest": manifest,
                },
            )
    # One row per tenant, and each tenant sees only its own.
    for tenant_id in (tenant, other_tenant):
        with acting_as(db_tx, tenant_id):
            n = db_tx.execute(
                text("SELECT count(*) FROM fct_loan_state WHERE external_loan_id = :loan"),
                {"loan": loan_id},
            ).scalar()
        assert n == 1
    # As ourselves, the policy hides the other tenant's row outright.
    count = db_tx.execute(
        text("SELECT count(*) FROM fct_loan_state WHERE external_loan_id = :loan"),
        {"loan": loan_id},
    ).scalar()
    assert count == 1


def test_usage_events_decision_id_is_typed_and_nullable(db_tx) -> None:
    _w6(db_tx)
    tenant, ids = _identity(db_tx)
    service = db_tx.execute(text("SELECT id FROM billing_services LIMIT 1")).scalar()
    if service is None:
        pytest.skip("no billing service")
    decision_id = "TD-W6-USAGE"
    db_tx.execute(
        text(
            """
            INSERT INTO treatment_decisions (
              id, tenant_id, customer_id, account_id, trigger_kind, mode,
              recommender, recommender_version, feature_schema_version,
              chosen_action, expected_value, propensity
            ) VALUES (
              :id, :tid, :cid, :aid, 'manual', 'shadow',
              'w6', 'test', 'v4', 'wait', 0, 1
            )
            """
        ),
        {
            "id": decision_id,
            "tid": tenant,
            "cid": ids["customer_id"],
            "aid": ids["account_id"],
        },
    )
    db_tx.execute(
        text(
            """
            INSERT INTO usage_events (
              id, tenant_id, environment, service_id, units, cost_inr, decision_id
            ) VALUES (
              'UE-W6-1', :tid, 'sandbox', :svc, 1, 0, :decision
            )
            """
        ),
        {"tid": tenant, "svc": service, "decision": decision_id},
    )
    savepoint = db_tx.begin_nested()
    with pytest.raises(IntegrityError):
        db_tx.execute(
            text(
                """
                INSERT INTO usage_events (
                  id, tenant_id, environment, service_id, units, cost_inr, decision_id
                ) VALUES (
                  'UE-W6-2', :tid, 'sandbox', :svc, 1, 0, 'missing-decision'
                )
                """
            ),
            {"tid": tenant, "svc": service},
        )
    savepoint.rollback()


def test_w6_soak_defaults_to_not_yet_measured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import soak_w6

    monkeypatch.delenv("W6_SOAK_DAYS", raising=False)
    monkeypatch.delenv("W6_DECLARED_BOOK_SCALE", raising=False)
    assert soak_w6.main() == 2
    assert "not yet measured" in capsys.readouterr().out


def test_an_unreadable_consent_store_is_a_stale_input_not_an_empty_consent(db_tx, monkeypatch) -> None:
    """The consent read used to swallow its exception and hand the engine `{}`
    -- "no consent on any channel", a fact the snapshot never had. It is a
    stale input now, and every channelled action is vetoed for that reason
    while WAIT stays legal."""
    import capture
    from agent_core.treatment.features import CONSENT_UNAVAILABLE, SqlFeatureProvider

    row = db_tx.execute(
        text("SELECT c.id AS customer_id, a.id AS account_id FROM customers c JOIN accounts a ON a.customer_id = c.id LIMIT 1")
    ).mappings().first()
    assert row

    def _boom(*_a, **_k):
        raise RuntimeError("consent store unreachable")

    monkeypatch.setattr(capture, "latest_consent_by_channel", _boom)
    served = SqlFeatureProvider().build(
        row["customer_id"], account_id=row["account_id"], trigger=Trigger(kind="manual"), now=datetime.now(timezone.utc), conn=db_tx
    )
    assert CONSENT_UNAVAILABLE in served.stale_inputs
    kwargs = dict(features=served, trigger=Trigger(kind="manual"), at=datetime.now(timezone.utc), policy=config.policy(), last_rung=0)
    assert policy.veto(None, action=A.SMS, **kwargs) == CONSENT_UNAVAILABLE
    assert policy.veto(None, action=A.WAIT, **kwargs) is None
