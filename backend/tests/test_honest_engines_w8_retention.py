"""W8b — retention: every record knows when it dies, and a citation says why.

The tests that earn the wave are the two that fail loudly if the design is
implemented backwards: an ``identified`` record is redacted in place and
reclassified, never deleted (deleting it would destroy the evidence
``policy_replay`` and every compensation case rest on), and an open recording
hold outranks the schedule.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from agent_core import retention
from agent_core.treatment import schema_ready

MAKER = "maker@example.test"
CHECKER = "checker@example.test"


@pytest.fixture(autouse=True)
def _reset():
    schema_ready.reset_cache()
    yield
    schema_ready.reset_cache()


def _require(db_tx) -> None:
    if not schema_ready.retention_ready(db_tx):
        if os.getenv("HONEST_ENGINES_REQUIRE_SCHEMA") == "1":
            pytest.fail("W8b schema not applied (migration 0117)")
        pytest.skip("W8b schema not applied")


def _subject(db_tx) -> tuple[str, str]:
    row = db_tx.execute(
        text("SELECT tenant_id, id FROM customers ORDER BY id LIMIT 1")
    ).mappings().first()
    if row is None:
        pytest.skip("no seeded customer")
    return str(row["tenant_id"]), str(row["id"])


def _expired_decision(db_tx, *, tenant, customer, age_days: int, cls=retention.IDENTIFIED):
    """One decision row already past its clock. Back-dated, not wall-clocked."""
    decision_id = f"TD-RET-{uuid.uuid4().hex[:10].upper()}"
    db_tx.execute(
        text(
            """
            INSERT INTO treatment_decisions (
              id, tenant_id, customer_id, trigger_kind, trigger_ref, mode,
              recommender, recommender_version, feature_schema_version,
              features, candidates, excluded, chosen_action, rationale,
              created_at, retention_class, retain_until
            ) VALUES (
              :id, :t, :c, 'dpd_tick', :ref, 'shadow',
              'ev', '1', '1',
              '{}'::jsonb, '[]'::jsonb, '{}'::jsonb, 'wait',
              'this borrower said his salary lands on the 3rd',
              now() - make_interval(days => :age),
              :cls,
              now() - make_interval(days => :age) + make_interval(days => 365)
            )
            """
        ),
        {
            "id": decision_id,
            "t": tenant,
            "c": customer,
            "ref": uuid.uuid4().hex[:8],
            "age": age_days,
            "cls": cls,
        },
    )
    return decision_id


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


def test_every_rule_names_its_instrument():
    # "Until purpose served" is a statutory standard, not a schedule. A rule
    # without a citation cannot answer why a record died on a Tuesday.
    assert retention.DEFAULTS
    for rule in retention.DEFAULTS.values():
        assert rule.citation.strip(), rule.record_kind
        assert rule.retention_class in retention.CLASSES


def test_the_statutory_floor_is_applied_as_a_maximum():
    rule = retention.DEFAULTS["interaction"]
    # The recovery-conduct six months is a FLOOR, not a ceiling, and DPDP Rule
    # 8(3)'s year is higher — so the year wins, not the tenant's 183 days.
    assert rule.retain_days == 183
    assert rule.floor_days == retention.DPDP_RULE_8_3_DAYS
    assert rule.effective_days == retention.DPDP_RULE_8_3_DAYS


def test_a_tenant_row_overrides_the_default_rule(db_tx):
    _require(db_tx)
    tenant, _ = _subject(db_tx)
    db_tx.execute(
        text(
            """
            INSERT INTO retention_rules (
              id, tenant_id, record_kind, retention_class, anchor,
              retain_days, floor_days, citation, changed_by, approved_by, reason
            ) VALUES (
              :id, :t, 'contact_event', 'processing_log', 'occurred_at',
              1500, 365, 'tenant contractual undertaking cl.9', :m, :c,
              'longer window agreed with the bank'
            )
            """
        ),
        {"id": f"RTR-{uuid.uuid4().hex[:8]}", "t": tenant, "m": MAKER, "c": CHECKER},
    )
    rule = retention.rule_for(db_tx, tenant_id=tenant, record_kind="contact_event")
    assert rule.effective_days == 1500
    assert "cl.9" in rule.citation


def test_a_self_approved_rule_is_refused_by_the_database(db_tx):
    _require(db_tx)
    tenant, _ = _subject(db_tx)
    with pytest.raises(Exception) as caught:
        db_tx.execute(
            text(
                """
                INSERT INTO retention_rules (
                  id, tenant_id, record_kind, retention_class, anchor,
                  retain_days, floor_days, citation, changed_by, approved_by, reason
                ) VALUES (
                  :id, :t, 'interaction', 'identified', 'started_at',
                  400, 365, 'cite', :m, :m, 'approving my own change'
                )
                """
            ),
            {"id": f"RTR-{uuid.uuid4().hex[:8]}", "t": tenant, "m": MAKER},
        )
    assert "maker_checker" in str(caught.value)


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


def test_an_identified_record_is_redacted_in_place_not_deleted(db_tx):
    _require(db_tx)
    tenant, customer = _subject(db_tx)
    decision_id = _expired_decision(db_tx, tenant=tenant, customer=customer, age_days=400)

    result = retention.sweep(db_tx, tenant_id=tenant, record_kind="treatment_decision")
    assert result[0]["redacted"] >= 1
    assert result[0]["deleted"] == 0

    row = db_tx.execute(
        text(
            "SELECT rationale, retention_class, retain_until, features"
            " FROM treatment_decisions WHERE id = :id"
        ),
        {"id": decision_id},
    ).mappings().first()
    # The row survives. Deleting it would destroy what policy_replay, the
    # compensation case and MRM traceability all rest on.
    assert row is not None
    assert row["rationale"] is None
    assert row["retention_class"] == retention.PSEUDONYMOUS
    # The exact feature vector stays: an EV cannot be replayed from banded
    # inputs, and a decision that cannot be replayed cannot be defended.
    assert row["features"] is not None
    # And the second, longer clock now runs from the redaction.
    assert row["retain_until"] > datetime.now(timezone.utc) + timedelta(days=3000)


def test_a_record_inside_its_window_is_not_touched(db_tx):
    _require(db_tx)
    tenant, customer = _subject(db_tx)
    decision_id = _expired_decision(db_tx, tenant=tenant, customer=customer, age_days=10)

    retention.sweep(db_tx, tenant_id=tenant, record_kind="treatment_decision")
    row = db_tx.execute(
        text("SELECT rationale, retention_class FROM treatment_decisions WHERE id = :id"),
        {"id": decision_id},
    ).mappings().first()
    assert row["rationale"] is not None
    assert row["retention_class"] == retention.IDENTIFIED


def test_a_sweep_that_destroyed_nothing_still_files_a_run(db_tx):
    # §7.8's discipline applied to retention. "Retention ran and destroyed
    # nothing" and "retention did not run" look identical in an empty table,
    # and only one of them is a finding.
    _require(db_tx)
    tenant, _ = _subject(db_tx)
    before = db_tx.execute(
        text("SELECT count(*) FROM retention_runs WHERE tenant_id = :t"), {"t": tenant}
    ).scalar()
    result = retention.sweep(db_tx, tenant_id=tenant)
    after = db_tx.execute(
        text("SELECT count(*) FROM retention_runs WHERE tenant_id = :t"), {"t": tenant}
    ).scalar()
    assert after - before == len(result) == len(retention.DEFAULTS)


def test_an_open_hold_outranks_the_schedule(db_tx):
    _require(db_tx)
    tenant, customer = _subject(db_tx)
    interaction_id = f"IN-RET-{uuid.uuid4().hex[:10].upper()}"
    bot_id = db_tx.execute(
        text("SELECT id FROM bots WHERE tenant_id = :t ORDER BY id LIMIT 1"),
        {"t": tenant},
    ).scalar()
    if not bot_id:
        pytest.skip("no seeded bot")
    db_tx.execute(
        text(
            """
            INSERT INTO interactions (
              id, tenant_id, customer_id, handler_kind, handler_bot_id,
              channel, direction, status, summary, started_at,
              retention_class, retain_until
            ) VALUES (
              :id, :t, :c, 'bot', :bot, 'voice', 'outbound', 'completed',
              'he disputed the amount and asked for the recording',
              now() - make_interval(days => 500), 'identified',
              now() - make_interval(days => 100)
            )
            """
        ),
        {"id": interaction_id, "t": tenant, "c": customer, "bot": bot_id},
    )
    hold = retention.open_hold(
        db_tx,
        tenant_id=tenant,
        interaction_id=interaction_id,
        reason="complaint under investigation",
        basis="RBI grievance redressal",
        opened_by=MAKER,
    )

    result = [r for r in retention.sweep(db_tx, tenant_id=tenant) if r["recordKind"] == "interaction"]
    assert result[0]["held"] >= 1
    row = db_tx.execute(
        text("SELECT summary, retention_class FROM interactions WHERE id = :id"),
        {"id": interaction_id},
    ).mappings().first()
    assert row["summary"] is not None
    assert row["retention_class"] == retention.IDENTIFIED

    # Released, the 90-day tail still holds it.
    assert retention.release_hold(db_tx, hold, released_by=CHECKER) is True
    result = [r for r in retention.sweep(db_tx, tenant_id=tenant) if r["recordKind"] == "interaction"]
    assert result[0]["held"] >= 1


def test_a_processing_log_is_deleted_when_its_clock_runs_out(db_tx):
    _require(db_tx)
    tenant, customer = _subject(db_tx)
    event_id = f"CE-RET-{uuid.uuid4().hex[:10].upper()}"
    db_tx.execute(
        text(
            """
            INSERT INTO contact_events (
              id, tenant_id, customer_id, channel, direction, purpose,
              actor_kind, outcome, occurred_at, retention_class, retain_until
            ) VALUES (
              :id, :t, :c, 'sms', 'outbound', 'outreach',
              'system', 'allowed', now() - make_interval(days => 500),
              'processing_log', now() - make_interval(days => 135)
            )
            """
        ),
        {"id": event_id, "t": tenant, "c": customer},
    )
    result = [r for r in retention.sweep(db_tx, tenant_id=tenant) if r["recordKind"] == "contact_event"]
    assert result[0]["deleted"] >= 1
    assert db_tx.execute(
        text("SELECT count(*) FROM contact_events WHERE id = :id"), {"id": event_id}
    ).scalar() == 0


# ---------------------------------------------------------------------------
# Stamping and the subject register
# ---------------------------------------------------------------------------


def test_the_expiry_is_stamped_at_write(db_tx):
    _require(db_tx)
    tenant, customer = _subject(db_tx)
    from agent_core.treatment import decisions

    decision_id = decisions.record(
        conn=db_tx,
        tenant_id=tenant,
        customer_id=customer,
        account_id=None,
        interaction_id=None,
        trigger_kind="dpd_tick",
        trigger_ref=uuid.uuid4().hex[:8],
        mode="shadow",
        variant=None,
        recommender="ev",
        recommender_version="1",
        feature_schema_version="1",
        features={},
        candidates=[],
        excluded={},
        chosen_action="wait",
        chosen_channel=None,
        scheduled_at=None,
        expected_value=0.0,
        propensity=None,
        explore_kind=None,
        policy_version=None,
        suppression_reason=None,
        rationale="stamped at write",
        latency_ms=1,
    )
    row = db_tx.execute(
        text(
            "SELECT retention_class, retain_until, created_at"
            " FROM treatment_decisions WHERE id = :id"
        ),
        {"id": decision_id},
    ).mappings().first()
    assert row["retention_class"] == retention.IDENTIFIED
    # One year from now, not a predicate evaluated later.
    assert row["retain_until"] > datetime.now(timezone.utc) + timedelta(days=360)


def test_backfill_stamps_older_rows_and_is_idempotent(db_tx):
    _require(db_tx)
    tenant, customer = _subject(db_tx)
    decision_id = f"TD-BF-{uuid.uuid4().hex[:10].upper()}"
    db_tx.execute(
        text(
            """
            INSERT INTO treatment_decisions (
              id, tenant_id, customer_id, trigger_kind, trigger_ref, mode,
              recommender, recommender_version, feature_schema_version,
              features, candidates, excluded, chosen_action, created_at
            ) VALUES (
              :id, :t, :c, 'dpd_tick', :ref, 'shadow', 'ev', '1', '1',
              '{}'::jsonb, '[]'::jsonb, '{}'::jsonb, 'wait',
              now() - make_interval(days => 30)
            )
            """
        ),
        {"id": decision_id, "t": tenant, "c": customer, "ref": uuid.uuid4().hex[:8]},
    )
    first = retention.backfill(db_tx, tenant_id=tenant, record_kind="treatment_decision")
    assert first >= 1
    assert retention.backfill(db_tx, tenant_id=tenant, record_kind="treatment_decision") == 0
    assert db_tx.execute(
        text("SELECT retain_until FROM treatment_decisions WHERE id = :id"),
        {"id": decision_id},
    ).scalar() is not None


def test_a_pseudonym_is_per_subject_and_stable(db_tx):
    _require(db_tx)
    tenant, customer = _subject(db_tx)
    first = retention.pseudonym_for(db_tx, tenant_id=tenant, subject_id=customer)
    assert first.startswith("SUBJ-")
    assert retention.pseudonym_for(db_tx, tenant_id=tenant, subject_id=customer) == first
    other = db_tx.execute(
        text("SELECT id FROM customers WHERE tenant_id = :t AND id <> :c ORDER BY id LIMIT 1"),
        {"t": tenant, "c": customer},
    ).scalar()
    if other:
        # A per-tenant salt cannot be destroyed for one borrower. This can.
        assert retention.pseudonym_for(db_tx, tenant_id=tenant, subject_id=str(other)) != first


def test_erasure_destroys_the_subject_key(db_tx):
    _require(db_tx)
    tenant, customer = _subject(db_tx)
    if not schema_ready.has_table(db_tx, "subject_requests"):
        pytest.skip("W4 schema not applied")
    import subject_rights

    actor = db_tx.execute(text("SELECT id FROM users ORDER BY id LIMIT 1")).scalar()
    if not actor:
        pytest.skip("no user")
    request = subject_rights.create_request(
        db_tx,
        tenant_id=tenant,
        customer_id=customer,
        kind="erasure",
        actor_user_id=str(actor),
    )
    subject_rights.fulfil_erasure(db_tx, request["id"], actor_user_id=str(actor))

    row = db_tx.execute(
        text(
            "SELECT destroyed_at, destroy_reason FROM subject_keys"
            " WHERE tenant_id = :t AND subject_id = :s"
        ),
        {"t": tenant, "s": customer},
    ).mappings().first()
    assert row is not None and row["destroyed_at"] is not None
    assert request["id"] in row["destroy_reason"]

    # Idempotent: a second erasure does not move the date destruction happened,
    # because that date is itself the evidence.
    assert retention.destroy_subject_key(
        db_tx, tenant_id=tenant, subject_id=customer, reason="again"
    ) is False
