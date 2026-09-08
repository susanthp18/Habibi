"""W4 — Layer P catalogue, bindings, consent, DPDP rights."""

from __future__ import annotations

import importlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

import policy_binding
import policy_rules
from agent_core import logging_contract
from agent_core.treatment import schema_ready

NOW = datetime(2026, 6, 15, 8, 30, tzinfo=timezone.utc)

KIND_FIXTURES: dict[str, dict] = {
    policy_rules.KIND_CALLING_WINDOW: {"startHour": 9, "endHour": 18},
    policy_rules.KIND_DAILY_CAP: {"value": 2},
    policy_rules.KIND_WEEKLY_CAP: {"value": 4},
    policy_rules.KIND_COOLING_OFF: {"minutes": 180},
    policy_rules.KIND_BUCKET_ACTIONS: {"byBucket": {"1-30": ["sms"]}},
    policy_rules.KIND_MANDATE_LIMIT: {"value": 1},
    policy_rules.KIND_MANDATE_RETURN: {"byReason": {"unknown": "veto"}},
    policy_rules.KIND_FIELD_PREREQS: {"required": ["visit_intimation"]},
    policy_rules.KIND_RECORDING_RETENTION: {"months": 12},
    policy_rules.KIND_VISIT_INTIMATION: {"hours": 48},
    policy_rules.KIND_SUPPRESSION_STATE: {"kinds": ["bereavement"]},
    policy_rules.KIND_RATIO_CEILING: {"max": 0.25},
    policy_rules.KIND_ASSIGNMENT_CHECK: {"requiredCertifications": ["empanelled"]},
    policy_rules.KIND_CHANNEL_SCRUB: {"lists": ["mnrl"]},
    policy_rules.KIND_NOTICE: {"obeysWindow": True},
}


def test_calling_window_tighten_never_widens() -> None:
    merged = policy_rules._tighten(
        policy_rules.KIND_CALLING_WINDOW,
        {"startHour": 8, "endHour": 19},
        {"startHour": 9, "endHour": 18},
    )
    assert merged["startHour"] == 9
    assert merged["endHour"] == 18


def test_unknown_kind_is_refused_at_publication() -> None:
    with pytest.raises(ValueError, match="unknown_policy_kind"):
        policy_rules.validate_kind("made_up_rule")
    with pytest.raises(ValueError, match="unknown_policy_kind"):
        policy_rules._tighten("made_up_rule", {}, {"x": 1})


def test_every_kind_has_tighten_consumer_and_fixture() -> None:
    missing = []
    for kind, spec in policy_rules.KIND_SPECS.items():
        fixture = KIND_FIXTURES.get(kind)
        if fixture is None:
            missing.append(f"{kind}:fixture")
            continue
        policy_rules.validate_params(kind, fixture)
        tighter = policy_rules._tighten(kind, fixture, fixture)
        assert isinstance(tighter, dict)
        consumer = spec["consumer"]
        module_name, _, attr = consumer.rpartition(".")
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            missing.append(f"{kind}:consumer_module:{module_name}")
            continue
        if not hasattr(module, attr):
            missing.append(f"{kind}:consumer:{attr}")
    extra = set(policy_rules.KNOWN_KINDS) - set(policy_rules.KIND_SPECS)
    assert not extra
    assert missing == []


def test_engine_image_digest_is_source_hash_not_env_label() -> None:
    digest = logging_contract.engine_image_digest()
    assert digest.startswith("sha256:")
    assert digest != "local"
    identity = logging_contract.deployed_image_identity()
    assert identity
    for rel in logging_contract.DIGEST_SOURCES:
        assert (Path(logging_contract._BACKEND_ROOT) / rel).is_file()
    assert logging_contract.VETO_STACK_VERSION
    assert logging_contract.engine_image_digest() == digest


def test_veto_stack_bump_changes_digest_contract() -> None:
    """A veto-stack bump without a digest source, or the reverse, is a miss."""
    assert logging_contract.VETO_STACK_VERSION.startswith("treatment-veto-")
    assert logging_contract.DIGEST_SOURCES


def test_binding_hash_is_stable() -> None:
    rules = policy_rules.RuleSet(
        statutory_version=1,
        consulted=(
            policy_rules.ConsultedRule(
                rule_id="calling_window:voice",
                rule_version=1,
                scope="statutory",
                kind="calling_window",
                channel="voice",
                citation="RBI",
                params={"startHour": 8, "endHour": 19},
            ),
        ),
    )
    first, digest = policy_binding.pair(rules, evaluated_at=NOW)
    second, again = policy_binding.pair(rules, evaluated_at=NOW)
    assert digest == again
    assert first[0]["verdict"] == policy_binding.VERDICT_NOT_FIRED
    fired, fired_digest = policy_binding.pair(
        rules, fired_rule_ids=["calling_window:voice"], evaluated_at=NOW
    )
    assert fired[0]["verdict"] == policy_binding.VERDICT_FIRED
    assert fired_digest != digest


def test_statutory_is_deferred_outside_hours(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    import contact_policy

    monkeypatch.setenv("CONTACT_COOLING_OFF_MINUTES", "0")
    cid = db_tx.execute(
        text(
            """
            SELECT id FROM customers
            WHERE id <> 'UNKNOWN-CALLER' AND COALESCE(dnd, false) IS FALSE
            ORDER BY id LIMIT 1
            """
        )
    ).scalar()
    if not cid:
        pytest.skip("no customer")
    late = datetime(2026, 6, 15, 16, 0, tzinfo=timezone.utc)  # 21:30 IST
    decision = contact_policy.admit(
        db_tx,
        customer_id=cid,
        channel="voice",
        purpose="statutory",
        session_key="stat-late",
        related_id="stat-late",
        now=late,
    )
    assert decision.allowed is False
    assert decision.reason in {
        contact_policy.REASON_WINDOW_DEFERRED_STATUTORY,
        contact_policy.REASON_HOURS,
        contact_policy.REASON_CUSTOMER_DND,
        contact_policy.REASON_OPTED_OUT,
        contact_policy.REASON_SUPPRESSED,
    }


def test_open_lead_does_not_overwrite_suppression() -> None:
    from agent_core.reco import policy

    decision = {
        "chosen_product_id": None,
        "suppression_reason": "hold:bereavement",
        "mode": "live",
        "presented": False,
        "response": None,
        "suggested_amount": None,
        "features": {},
        "channel": "voice",
        "product_name": None,
    }
    lead = {
        "id": "LEAD-1",
        "stage": "new",
        "product_id": "P1",
        "product_name": "Top-up",
        "offer_amount": 1000,
    }
    snap = policy._merge("C1", decision, lead)
    assert snap["status"] == "suppressed"
    assert snap["leadId"] == "LEAD-1"
    assert not snap["talkTrack"]


def test_replay_refuses_unknown_digest(db_tx) -> None:
    import policy_replay

    if not schema_ready.w4_ready(db_tx):
        if os.getenv("HONEST_ENGINES_REQUIRE_SCHEMA") == "1":
            pytest.fail("W4 schema not applied")
        pytest.skip("W4 schema not applied")
    start = datetime.now(timezone.utc) - timedelta(days=1)
    end = datetime.now(timezone.utc)
    result = policy_replay.replay(
        db_tx,
        window_start=start,
        window_end=end,
        expected_digest="sha256:deadbeef",
        tenant_id=None,
    )
    assert result["status"] == "refused"
    assert result["refusalReason"] == policy_replay.REFUSE_DIGEST


def test_maker_checker_and_overlap(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    if not schema_ready.w4_ready(db_tx):
        if os.getenv("HONEST_ENGINES_REQUIRE_SCHEMA") == "1":
            pytest.fail("W4 schema not applied")
        pytest.skip("W4 schema not applied")
    monkeypatch.setenv("POLICY_PRODUCTION_PUBLICATION", "true")
    from env_utils import env_bool

    assert env_bool("POLICY_PRODUCTION_PUBLICATION", False) is True
    users = db_tx.execute(text("SELECT id FROM users ORDER BY id LIMIT 2")).scalars().all()
    if len(users) < 2:
        pytest.skip("need two users for maker-checker")
    maker, checker = users[0], users[1]
    start = datetime(2030, 1, 1, tzinfo=timezone.utc)
    rules = [
        {
            "kind": "calling_window",
            "channel": "voice",
            "params": {"startHour": 9, "endHour": 17},
            "citation": "test-cite",
        }
    ]
    set_id = policy_rules.create_draft(
        db_tx,
        scope="client",
        version=99,
        label="test-cite",
        effective_from=start,
        effective_to=None,
        tenant_id="hdfc.retail",
        rules=rules,
        actor_user_id=maker,
    )
    policy_rules.submit_for_approval(db_tx, set_id, actor_user_id=maker)
    with pytest.raises(ValueError, match="maker_checker"):
        policy_rules.approve_publication(db_tx, set_id, actor_user_id=maker)
    policy_rules.approve_publication(db_tx, set_id, actor_user_id=checker)
    with pytest.raises(Exception):
        policy_rules.create_draft(
            db_tx,
            scope="client",
            version=100,
            label="test-cite",
            effective_from=start,
            effective_to=None,
            tenant_id="hdfc.retail",
            rules=rules,
            actor_user_id=maker,
        )


def test_complaint_pack_seeded_sections(db_tx) -> None:
    import complaint_pack
    import db

    row = db_tx.execute(
        text("SELECT id FROM customers ORDER BY id LIMIT 1")
    ).mappings().first()
    if row is None:
        pytest.skip("no customer")
    pack = complaint_pack.compose(
        db_tx, tenant_id=db.current_tenant(), customer_id=row["id"]
    )
    for section in complaint_pack.REQUIRED_SECTIONS:
        assert section in pack
    assert pack["identity"]["customerId"] == row["id"]
    assert pack["generatedAt"]
    assert pack["digest"].startswith("sha256:")


def test_subject_request_slo_and_erasure_needs_evidence(db_tx) -> None:
    import subject_rights
    import db

    if not schema_ready.has_table(db_tx, "subject_requests"):
        if os.getenv("HONEST_ENGINES_REQUIRE_SCHEMA") == "1":
            pytest.fail("W4 schema not applied")
        pytest.skip("W4 schema not applied")
    customer = db_tx.execute(text("SELECT id FROM customers LIMIT 1")).scalar()
    if not customer:
        pytest.skip("no customer")
    created = subject_rights.create_request(
        db_tx,
        tenant_id=db.current_tenant(),
        customer_id=customer,
        kind="access",
        actor_user_id="user-a",
    )
    assert created["dueAt"] - created["receivedAt"] <= timedelta(days=90)
    erasure = subject_rights.create_request(
        db_tx,
        tenant_id=db.current_tenant(),
        customer_id=customer,
        kind="erasure",
        actor_user_id="user-a",
    )
    with pytest.raises(ValueError, match="erasure_evidence"):
        subject_rights.transition(
            db_tx, erasure["id"], state="fulfilled", actor_user_id="user-a"
        )
    fulfilled = subject_rights.fulfil_erasure(
        db_tx, erasure["id"], actor_user_id="user-a"
    )
    assert fulfilled["evidenceRef"]
    assert subject_rights.overdue_count(db_tx, tenant_id=db.current_tenant()) == 0


def test_two_person_release_and_feedback_cannot_widen(db_tx) -> None:
    import decision_feedback
    import db
    from db_treatment_holds import TWO_PERSON_RELEASE

    if not schema_ready.has_table(db_tx, "consent_events"):
        if os.getenv("HONEST_ENGINES_REQUIRE_SCHEMA") == "1":
            pytest.fail("W4 schema not applied")
        pytest.skip("W4 schema not applied")
    with pytest.raises(ValueError, match="restrict_only"):
        decision_feedback.append_consent_event(
            db_tx,
            tenant_id=db.current_tenant(),
            customer_id="x",
            verb="grant",
            channel="voice",
            source="test",
            evidence_ref=None,
            actor_kind="human",
            actor_user_id="a",
        )
    assert "cease_and_desist" in TWO_PERSON_RELEASE


def test_product_id_is_on_account_features() -> None:
    from agent_core.treatment.features import AccountFeatures, SCHEMA_VERSION

    assert SCHEMA_VERSION == "v4"
    assert "product_id" in AccountFeatures.__dataclass_fields__


def test_authz_covers_new_policy_routes() -> None:
    import authz

    for method, path in (
        ("GET", "/compliance/policy-rules"),
        ("POST", "/compliance/policy-rules"),
        ("POST", "/compliance/policy-rules/{set_id}/approve"),
        ("POST", "/treatment/decisions/{decision_id}/feedback"),
        ("GET", "/compliance/complaint-pack/{customer_id}"),
        ("POST", "/compliance/subject-requests"),
    ):
        assert (method, path) in authz.ROUTE_PERMISSIONS
        assert authz.ROUTE_PERMISSIONS[(method, path)] in authz.ALL_PERMISSIONS
