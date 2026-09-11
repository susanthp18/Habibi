"""W5 bank boundary — contracts, ingest, action contract, isolation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from agent_core.treatment import contract as action_contract
from bank_boundary import (
    ACTION_CONTRACT_VERSION,
    adapters,
    auditor,
    bootstrap,
    clerk_allowlist,
    evaluation,
    freshness,
    identifiers,
    ingest,
    mappings,
    outbox,
    registry,
    snapshots,
)
from bank_boundary.ingest import IngestRejected


@pytest.fixture(autouse=True)
def _reset_schema_cache():
    from agent_core.treatment import schema_ready

    schema_ready.reset_cache()
    yield
    schema_ready.reset_cache()


@pytest.fixture(autouse=True)
def _as_the_owner(db_tx):
    """This module bootstraps the W5 schema (DDL) and seeds contract bindings
    for *every* tenant, then loads the same feed under two tenants to prove
    isolation -- platform operations, done from the outside. The application
    role, which row-level security constrains, cannot perform them. Run as
    the owner: ``docker compose exec -e DATABASE_URL=<owner dsn> voice pytest
    tests/test_honest_engines_w5.py``."""
    from tests.conftest import require_owner

    require_owner(db_tx, "W5 bootstrap and tenant-pair seeding are owner operations")


def _tenant_pair(conn):
    rows = [str(x) for x in conn.execute(text("SELECT id FROM tenants ORDER BY id")).scalars().all()]
    if not rows:
        pytest.skip("no tenant")
    t1 = rows[0]
    if len(rows) >= 2:
        return t1, rows[1]
    t2 = "w5-isolation-tenant"
    conn.execute(
        text("INSERT INTO tenants (id, name) VALUES (:id, 'W5 isolation')"),
        {"id": t2},
    )
    bootstrap.ensure(conn)
    return t1, t2


def _account(conn, tenant_id: str):
    row = conn.execute(
        text(
            """
            SELECT a.id, a.customer_id, c.phone_primary
              FROM accounts a
              JOIN customers c ON c.id = a.customer_id
             WHERE c.tenant_id = :tid AND a.status = 'active'
             ORDER BY a.id LIMIT 1
            """
        ),
        {"tid": tenant_id},
    ).mappings().first()
    if row is not None:
        return dict(row)
    product = conn.execute(text("SELECT id FROM products LIMIT 1")).scalar()
    if product is None:
        pytest.skip("no product")
    cid = f"W5C-{tenant_id}"[:40]
    aid = f"W5A-{tenant_id}"[:40]
    conn.execute(
        text(
            """
            INSERT INTO customers (id, tenant_id, name, risk, phone_primary)
            VALUES (:id, :tid, 'W5 borrower', 'medium', '9999999999')
            """
        ),
        {"id": cid, "tid": tenant_id},
    )
    conn.execute(
        text(
            """
            INSERT INTO accounts (id, customer_id, product_id, outstanding, dpd, status)
            VALUES (:id, :cid, :pid, 1000, 15, 'active')
            """
        ),
        {"id": aid, "cid": cid, "pid": product},
    )
    return {"id": aid, "customer_id": cid, "phone_primary": "9999999999"}


def _load(conn, *, tenant_id, code, rows, day, ref, sum_paise=None):
    total = sum(int(r.get("amount_paise") or r.get("outstanding_paise") or 0) for r in rows)
    return ingest.load(
        conn,
        tenant_id=tenant_id,
        contract_code=code,
        schema_version="bank-boundary.v1",
        source="reference",
        business_date=day,
        source_ref=ref,
        control_count=len(rows),
        control_sum_paise=total if sum_paise is None else sum_paise,
        event_time=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
        rows=rows,
        known_from=datetime.now(timezone.utc),
    )


def test_atomic_reject_leaves_canonical_unchanged(db_tx) -> None:
    bootstrap.ensure(db_tx)
    tenant, _ = _tenant_pair(db_tx)
    account = _account(db_tx, tenant)
    before = db_tx.execute(
        text("SELECT outstanding FROM accounts WHERE id = :id"),
        {"id": account["id"]},
    ).scalar()
    with pytest.raises(IngestRejected, match="sum"):
        ingest.load(
            db_tx,
            tenant_id=tenant,
            contract_code="C1",
            schema_version="bank-boundary.v1",
            source="reference",
            business_date=date(2026, 9, 1),
            source_ref="bad-sum",
            control_count=1,
            control_sum_paise=1,
            event_time=datetime(2026, 9, 1, tzinfo=timezone.utc),
            rows=[
                {
                    "external_id": account["id"],
                    "outstanding_paise": 50000,
                    "status": "active",
                    "source_row_id": "1",
                }
            ],
        )
    after = db_tx.execute(
        text("SELECT outstanding FROM accounts WHERE id = :id"),
        {"id": account["id"]},
    ).scalar()
    assert after == before


def test_idempotent_replay_and_tenant_isolation(db_tx) -> None:
    bootstrap.ensure(db_tx)
    t1, t2 = _tenant_pair(db_tx)
    a1 = _account(db_tx, t1)
    a2 = _account(db_tx, t2)
    day = date(2026, 9, 2)
    row = {
        "external_id": "ACC-COLLIDE",
        "outstanding_paise": 1000,
        "status": "active",
        "source_row_id": "x",
    }
    identifiers.bind(
        db_tx,
        tenant_id=t1,
        namespace="account",
        external_id="ACC-COLLIDE",
        canonical_id=a1["id"],
        canonical_table="accounts",
    )
    identifiers.bind(
        db_tx,
        tenant_id=t2,
        namespace="account",
        external_id="ACC-COLLIDE",
        canonical_id=a2["id"],
        canonical_table="accounts",
    )
    first = _load(db_tx, tenant_id=t1, code="C1", rows=[row], day=day, ref="iso-1")
    replay = _load(db_tx, tenant_id=t1, code="C1", rows=[row], day=day, ref="iso-1")
    assert replay["replayed"] is True
    assert replay["id"] == first["id"]
    _load(db_tx, tenant_id=t2, code="C1", rows=[row], day=day, ref="iso-1")
    mapped_1 = identifiers.resolve(
        db_tx, tenant_id=t1, namespace="account", external_id="ACC-COLLIDE"
    )
    mapped_2 = identifiers.resolve(
        db_tx, tenant_id=t2, namespace="account", external_id="ACC-COLLIDE"
    )
    assert mapped_1 == a1["id"]
    assert mapped_2 == a2["id"]
    assert mapped_1 != mapped_2


def test_w5_schema_constraints_indexes_and_evaluation_isolation(db_tx) -> None:
    bootstrap.ensure(db_tx)
    columns = {
        (row["table_schema"], row["table_name"], row["column_name"])
        for row in db_tx.execute(
            text(
                """
                SELECT table_schema, table_name, column_name
                  FROM information_schema.columns
                 WHERE table_name IN (
                   'bank_inbound_manifests','bank_outbound_outbox',
                   'protected_attributes'
                 )
                """
            )
        ).mappings()
    }
    assert ("public", "bank_inbound_manifests", "known_from") in columns
    assert ("public", "bank_outbound_outbox", "idempotency_key") in columns
    assert ("evaluation", "protected_attributes", "attribute_value_hash") in columns
    tenant_first = db_tx.execute(
        text(
            """
            SELECT bool_and(pg_get_indexdef(i.indexrelid) LIKE '%(tenant_id,%')
              FROM pg_index i
              JOIN pg_class t ON t.oid = i.indrelid
             WHERE t.relname IN (
               'bank_inbound_manifests','bank_outbound_outbox',
               'bank_external_contacts'
             )
               AND NOT i.indisprimary
            """
        )
    ).scalar()
    assert tenant_first is True
    public_can_read_f9 = db_tx.execute(
        text(
            """
            SELECT has_table_privilege(
              'public', 'evaluation.protected_attributes', 'SELECT'
            )
            """
        )
    ).scalar()
    assert public_can_read_f9 is False


def test_unknown_map_opens_review_and_rejects(db_tx) -> None:
    bootstrap.ensure(db_tx)
    tenant, _ = _tenant_pair(db_tx)
    account = _account(db_tx, tenant)
    with pytest.raises(IngestRejected, match="unknown_map"):
        ingest.load(
            db_tx,
            tenant_id=tenant,
            contract_code="C1",
            schema_version="bank-boundary.v1",
            source="reference",
            business_date=date(2026, 9, 3),
            source_ref="unk",
            control_count=1,
            control_sum_paise=0,
            event_time=datetime(2026, 9, 3, tzinfo=timezone.utc),
            rows=[
                {
                    "external_id": account["id"],
                    "outstanding_paise": 0,
                    "status": "mystery_status",
                    "source_row_id": "1",
                }
            ],
        )
    open_n = db_tx.execute(
        text("SELECT count(*) FROM bank_mapping_reviews WHERE state = 'open'")
    ).scalar()
    assert int(open_n or 0) >= 1


def test_late_ownership_failure_cannot_partially_apply(db_tx) -> None:
    bootstrap.ensure(db_tx)
    tenant, _ = _tenant_pair(db_tx)
    account = _account(db_tx, tenant)
    before = db_tx.execute(
        text("SELECT outstanding FROM accounts WHERE id = :id"),
        {"id": account["id"]},
    ).scalar()
    rows = [
        {
            "external_id": account["id"],
            "outstanding_paise": 12345,
            "status": "active",
            "source_row_id": "valid-first",
        },
        {
            "external_id": "belongs-nowhere",
            "outstanding_paise": 500,
            "status": "active",
            "source_row_id": "invalid-second",
        },
    ]
    with pytest.raises(IngestRejected, match="ownership"):
        _load(
            db_tx,
            tenant_id=tenant,
            code="C1",
            rows=rows,
            day=date(2026, 9, 3),
            ref="late-ownership",
        )
    after = db_tx.execute(
        text("SELECT outstanding FROM accounts WHERE id = :id"),
        {"id": account["id"]},
    ).scalar()
    assert after == before


def test_endpoint_consent_is_not_shared_between_numbers(db_tx) -> None:
    bootstrap.ensure(db_tx)
    tenant, _ = _tenant_pair(db_tx)
    account = _account(db_tx, tenant)
    now = datetime.now(timezone.utc)
    _load(
        db_tx,
        tenant_id=tenant,
        code="C8",
        rows=[
            {
                "customer_external_id": account["customer_id"],
                "endpoint": "9999999999",
                "purpose": "servicing",
                "channel": "voice",
                "permitted": True,
                "event_time": now,
                "amount_paise": 0,
                "source_row_id": "consent-primary",
            }
        ],
        day=now.date(),
        ref="endpoint-grain",
    )
    primary = freshness.resolve(
        db_tx,
        tenant_id=tenant,
        action="voice_bot",
        channel="voice",
        endpoint="9999999999",
        customer_id=account["customer_id"],
    )
    alternate = freshness.resolve(
        db_tx,
        tenant_id=tenant,
        action="voice_bot",
        channel="voice",
        endpoint="9888888888",
        customer_id=account["customer_id"],
    )
    assert "endpoint_consent_stale" not in primary.reasons
    assert "endpoint_consent_stale" in alternate.reasons
    assert alternate.contacting_blocked is True


def test_outbox_key_is_tenant_scoped_and_reference_only(db_tx) -> None:
    bootstrap.ensure(db_tx)
    tenant, other = _tenant_pair(db_tx)
    one = adapters.send_with_outbox(
        db_tx,
        tenant_id=tenant,
        contract_code="O6",
        action_contract={
            "tenant_id": tenant,
            "portfolio_id": "",
            "decision_id": "D1",
        },
        idempotency_key="same-key",
    )
    two = adapters.send_with_outbox(
        db_tx,
        tenant_id=other,
        contract_code="O6",
        action_contract={
            "tenant_id": other,
            "portfolio_id": "",
            "decision_id": "D2",
        },
        idempotency_key="same-key",
    )
    assert one["id"] != two["id"]
    assert one["submitted"] is False
    assert two["submitted"] is False


def test_ambiguous_committed_outbox_is_parked_not_resent(db_tx) -> None:
    bootstrap.ensure(db_tx)
    tenant, _ = _tenant_pair(db_tx)
    outbox.enqueue(
        db_tx,
        tenant_id=tenant,
        contract_code="O6",
        idempotency_key="ambiguous-after-crash",
        payload={"decision_id": "D-crash"},
        decision_id="D-crash",
    )
    before = len(
        adapters.dispatch("O6").receipts(
            datetime.min.replace(tzinfo=timezone.utc)
        )
    )
    reconciled = adapters.send_with_outbox(
        db_tx,
        tenant_id=tenant,
        contract_code="O6",
        action_contract={
            "tenant_id": tenant,
            "portfolio_id": "",
            "decision_id": "D-crash",
        },
        idempotency_key="ambiguous-after-crash",
    )
    after = len(
        adapters.dispatch("O6").receipts(
            datetime.min.replace(tzinfo=timezone.utc)
        )
    )
    assert reconciled["state"] == outbox.PARKED
    assert after == before


def test_o1_unknown_template_fails_closed_without_adapter_send(db_tx) -> None:
    bootstrap.ensure(db_tx)
    tenant, _ = _tenant_pair(db_tx)
    before = len(adapters.dispatch("O1").receipts(datetime.min.replace(tzinfo=timezone.utc)))
    with pytest.raises(mappings.UnknownMapping):
        adapters.send_with_outbox(
            db_tx,
            tenant_id=tenant,
            contract_code="O1",
            action_contract={
                "tenant_id": tenant,
                "portfolio_id": "",
                "decision_id": "D1",
                "channel": "sms",
                "template_id": "unknown-template",
                "required_assertions": ["identify_lender"],
            },
            idempotency_key="O1:D1",
        )
    after = len(adapters.dispatch("O1").receipts(datetime.min.replace(tzinfo=timezone.utc)))
    assert after == before


def test_five_day_streak_unlocks_only_that_portfolio(db_tx) -> None:
    bootstrap.ensure(db_tx)
    tenant, other = _tenant_pair(db_tx)
    account = _account(db_tx, tenant)
    start = date(2026, 8, 24)
    for code in ("C1", "C2", "C6", "C8", "C10"):
        for i in range(5):
            day = start + timedelta(days=i)
            if code == "C1":
                rows = [
                    {
                        "external_id": account["id"],
                        "outstanding_paise": 100,
                        "status": "active",
                        "source_row_id": f"{code}-{i}",
                    }
                ]
            elif code == "C2":
                rows = [
                    {
                        "external_id": f"EMI-{account['id']}-{i}",
                        "account_external_id": account["id"],
                        "installment_index": 1,
                        "due_date": datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
                        "amount_paise": 100,
                        "status": "overdue",
                        "source_row_id": f"{code}-{i}",
                    }
                ]
            elif code == "C6":
                rows = [
                    {
                        "external_id": f"PAY-{account['id']}-{i}",
                        "account_external_id": account["id"],
                        "amount_paise": 100,
                        "posted_at": datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
                        "source_row_id": f"{code}-{i}",
                    }
                ]
            elif code == "C8":
                rows = [
                    {
                        "customer_external_id": account["customer_id"],
                        "endpoint": account["phone_primary"] or "9999999999",
                        "purpose": "servicing",
                        "channel": "voice",
                        "permitted": True,
                        "event_time": datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
                        "source_row_id": f"{code}-{i}",
                        "amount_paise": 0,
                    }
                ]
            else:
                rows = [
                    {
                        "customer_external_id": account["customer_id"],
                        "kind": "mfi_protection",
                        "active": True,
                        "event_time": datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
                        "source_row_id": f"{code}-{i}",
                        "amount_paise": 0,
                    }
                ]
            _load(db_tx, tenant_id=tenant, code=code, rows=rows, day=day, ref=f"{code}-{i}")
    assert freshness.require_shadow_exit(db_tx, tenant_id=tenant) is True
    assert freshness.require_shadow_exit(db_tx, tenant_id=other) is False
    # A later failed contract clears the streak.
    with pytest.raises(IngestRejected):
        ingest.load(
            db_tx,
            tenant_id=tenant,
            contract_code="C1",
            schema_version="bank-boundary.v1",
            source="reference",
            business_date=start + timedelta(days=5),
            source_ref="stale-fail",
            control_count=1,
            control_sum_paise=1,
            event_time=datetime(2026, 8, 29, tzinfo=timezone.utc),
            rows=[
                {
                    "external_id": account["id"],
                    "outstanding_paise": 0,
                    "status": "active",
                    "source_row_id": "fail",
                }
            ],
        )
    assert freshness.require_shadow_exit(db_tx, tenant_id=tenant) is False


def test_action_contract_refuse_missing_stale_unsupported() -> None:
    fake = SimpleNamespace(
        decision_id="TD-1",
        action="whatsapp",
        channel="whatsapp",
        at=datetime.now(timezone.utc),
        expected_value=1.5,
        variant="control",
        arm_propensity=0.5,
        action_propensity=1.0,
        policy_binding_hash="h",
        engine_image_digest="sha256:x",
        config_version="env:x",
        tenant_id="t",
    )
    built = action_contract.build(fake, features=None, policy_version=1, propensity=0.5)
    assert built["version"] == ACTION_CONTRACT_VERSION
    assert built["decision_id"] == "TD-1"
    assert built["ev_lcb_paise"] == 150
    assert built["allowed_offers"] == []


def test_reference_adapter_does_not_submit_debit() -> None:
    adapter = adapters.dispatch("O2")
    ack = adapter.send({"decision_id": "TD-M", "idempotency_key": "O2:TD-M"})
    assert ack["submitted"] is False
    assert ack["status"] == "awaiting_settlement"


def test_clerk_unknown_workflow_parks() -> None:
    assert clerk_allowlist.allow("not_a_workflow") == "unknown_workflow"
    assert clerk_allowlist.allow("bounce_chase") is None
    assert (
        clerk_allowlist.allow("o6_lms_workitem")
        == "missing_contract_version"
    )
    assert (
        clerk_allowlist.allow(
            "o6_lms_workitem", contract_version=ACTION_CONTRACT_VERSION
        )
        is None
    )


def test_f9_requires_evaluation_role(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    bootstrap.ensure(db_tx)
    tenant, _ = _tenant_pair(db_tx)
    account = _account(db_tx, tenant)
    with pytest.raises(evaluation.EvaluationRoleRequired):
        evaluation.ingest(
            db_tx,
            tenant_id=tenant,
            customer_id=account["customer_id"],
            attribute_name="gender",
            attribute_value="secret",
        )
    monkeypatch.setattr(evaluation, "evaluation_role_active", lambda conn: True)
    evaluation.ingest(
        db_tx,
        tenant_id=tenant,
        customer_id=account["customer_id"],
        attribute_name="gender",
        attribute_value="secret",
    )
    ready = evaluation.fairness_readiness(db_tx, tenant_id=tenant)
    assert ready["ready"] is True
    assert "secret" not in str(ready)


def test_f9_not_queried_from_api_modules() -> None:
    from pathlib import Path

    for rel in ("main.py", "authz.py", "bank_boundary/api.py"):
        src = (Path(__file__).resolve().parents[1] / rel).read_text(encoding="utf-8")
        assert "protected_attributes" not in src


def test_breach_auditor_needs_c7_coverage(db_tx) -> None:
    bootstrap.ensure(db_tx)
    tenant, _ = _tenant_pair(db_tx)
    now = datetime.now(timezone.utc)
    result = auditor.audit(
        db_tx, tenant_id=tenant, window_start=now - timedelta(days=1), window_end=now
    )
    assert "ledger_coverage_share" in result
    assert result["green"] is False


def test_f8_round_trip_links_intake_and_filing(db_tx) -> None:
    from bank_boundary import api

    bootstrap.ensure(db_tx)
    tenant, _ = _tenant_pair(db_tx)
    account = _account(db_tx, tenant)
    filed = api.file_complaint(
        db_tx,
        tenant_id=tenant,
        customer_id=account["customer_id"],
        kind="conduct",
        actor_user_id=None,
    )
    assert filed["state"] == "accepted"
    rows = db_tx.execute(
        text(
            """
            SELECT direction, outbox_id FROM bank_complaint_events
             WHERE tenant_id = :tid AND customer_id = :cid
             ORDER BY direction
            """
        ),
        {"tid": tenant, "cid": account["customer_id"]},
    ).mappings().all()
    assert {row["direction"] for row in rows} == {"inbound", "outbound"}
    assert all(row["outbox_id"] for row in rows)


def test_mandate_candidate_without_debit(db_tx) -> None:
    bootstrap.ensure(db_tx)
    tenant, _ = _tenant_pair(db_tx)
    account = _account(db_tx, tenant)
    day = date(2026, 9, 4)
    _load(
        db_tx,
        tenant_id=tenant,
        code="C2",
        rows=[
            {
                "external_id": f"EMI-{account['id']}",
                "account_external_id": account["id"],
                "installment_index": 1,
                "due_date": day,
                "amount_paise": 1000,
                "status": "overdue",
                "source_row_id": "emi1",
            }
        ],
        day=day,
        ref="c2",
    )
    # C3 mandate
    _load(
        db_tx,
        tenant_id=tenant,
        code="C3",
        rows=[
            {
                "external_id": f"M-{account['id']}",
                "account_external_id": account["id"],
                "customer_external_id": account["customer_id"],
                "rail": "nach",
                "status": "active",
                "max_amount_paise": 500000,
                "debit_day": 5,
                "amount_paise": 0,
                "source_row_id": "m1",
            }
        ],
        day=day,
        ref="c3",
    )
    _load(
        db_tx,
        tenant_id=tenant,
        code="C4",
        rows=[],
        day=day,
        ref="c4",
    )
    _load(
        db_tx,
        tenant_id=tenant,
        code="C5",
        rows=[],
        day=day,
        ref="c5",
    )
    registry.bind(
        db_tx,
        tenant_id=tenant,
        contract_code="O6",
        state="ready",
    )
    from agent_core.treatment import Trigger, recommend_treatment

    result = recommend_treatment(
        customer_id=account["customer_id"],
        account_id=account["id"],
        trigger=Trigger(kind="manual"),
        conn=db_tx,
        persist="preview",
    )
    candidate_actions = {item.action for item in result.alternatives}
    candidate_actions.add(result.action)
    assert "represent_mandate" in candidate_actions, result.excluded
    assert "represent_mandate" not in (result.excluded or {})
    ack = adapters.dispatch("O2").send({"decision_id": "preview", "idempotency_key": "none"})
    assert ack["submitted"] is False


def test_executor_consumes_persisted_contract(db_tx) -> None:
    bootstrap.ensure(db_tx)
    tenant, _ = _tenant_pair(db_tx)
    # Need a treatment_decisions row for the FK.
    decision_id = db_tx.execute(
        text("SELECT id FROM treatment_decisions WHERE tenant_id = :tid LIMIT 1"),
        {"tid": tenant},
    ).scalar()
    if decision_id is None:
        pytest.skip("no decision")
    payload = {
        "version": ACTION_CONTRACT_VERSION,
        "decision_id": decision_id,
        "tenant_id": tenant,
        "portfolio_id": "",
        "policy_binding": [],
        "policy_binding_hash": "sha256:test-policy",
        "engine_image_digest": "sha256:test-image",
        "config_version": "sha256:test-config",
        "veto_stack_version": "treatment-veto-v4",
        "action": "sms",
        "channel": "sms",
        "arm_propensity": 1.0,
        "action_propensity": 1.0,
        "scheduled_at": datetime.now(timezone.utc).isoformat(),
        "expected_value_paise": 0,
        "ev_lcb_paise": 0,
        "objective": "payment_commitment",
        "strategy": "soft_reminder",
        "prohibitions": ["cross_sell"],
        "required_assertions": ["identify_lender"],
        "retention_class": "collections_operational",
        "allowed_offers": [],
    }
    stored = snapshots.persist(db_tx, payload)
    loaded = snapshots.load(db_tx, str(decision_id))
    assert loaded["decision_id"] == decision_id
    assert stored["digest"].startswith("sha256:")
    from agent_core.treatment.enact import _consume_contract, NoExecutor

    _consume_contract(loaded, {"id": decision_id})
    with pytest.raises(NoExecutor):
        _consume_contract({**loaded, "version": "nope", "digest": "x"}, {"id": decision_id})
    with pytest.raises(NoExecutor):
        _consume_contract({**loaded, "decision_id": "other", "digest": "x"}, {"id": decision_id})
    with pytest.raises(NoExecutor, match="tampered"):
        _consume_contract(
            {**loaded, "objective": "changed-after-signing"},
            {"id": decision_id},
        )
    replay = snapshots.persist(db_tx, {**payload, "objective": "different"})
    assert replay["objective"] == loaded["objective"]


def test_c7_union_and_agency_expiry(db_tx) -> None:
    bootstrap.ensure(db_tx)
    tenant, _ = _tenant_pair(db_tx)
    account = _account(db_tx, tenant)
    day = date(2026, 9, 5)
    _load(
        db_tx,
        tenant_id=tenant,
        code="C7",
        rows=[
            {
                "customer_external_id": account["customer_id"],
                "external_key": "cdr-1",
                "channel": "voice",
                "occurred_at": datetime.now(timezone.utc),
                "amount_paise": 0,
                "source_row_id": "cdr-1",
            }
        ],
        day=day,
        ref="c7",
    )
    _load(
        db_tx,
        tenant_id=tenant,
        code="C9",
        rows=[
            {
                "kind": "roster",
                "agency_id": "ag1",
                "agent_id": "agent1",
                "certification": "empanelled",
                "expires_at": datetime.now(timezone.utc) - timedelta(days=1),
                "amount_paise": 0,
                "source_row_id": "r1",
            }
        ],
        day=day,
        ref="c9",
    )
    ready = freshness.resolve(
        db_tx, tenant_id=tenant, action="field_visit", channel="field"
    )
    assert ready.field_blocked is True
    result = auditor.audit(
        db_tx,
        tenant_id=tenant,
        window_start=datetime.now(timezone.utc) - timedelta(hours=1),
        window_end=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert "c7" in result["sources_represented"]
    assert result["ledger_coverage_share"] is not None
