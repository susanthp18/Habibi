"""What the statutory-rules screen reads and refuses.

The approver has to see the rules, not a label; and a reject that touched no
row used to answer "rejected" anyway.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import policy_rules
from agent_core.treatment import schema_ready


def _draft(conn) -> str:
    return policy_rules.create_draft(
        conn,
        scope="client",
        version=98,
        label="review-cite",
        effective_from=datetime(2031, 1, 1, tzinfo=timezone.utc),
        effective_to=None,
        tenant_id="hdfc.retail",
        notes="read me",
        rules=[
            {
                "kind": "calling_window",
                "channel": "voice",
                "params": {"startHour": 9, "endHour": 17},
                "citation": "review-cite",
            }
        ],
        actor_user_id=None,
    )


def test_the_list_carries_each_sets_rules(db_tx) -> None:
    if not schema_ready.w4_ready(db_tx):
        pytest.skip("W4 schema not applied")
    set_id = _draft(db_tx)
    row = next(r for r in policy_rules.list_rule_sets(db_tx, tenant_id="hdfc.retail") if r["id"] == set_id)
    assert row["notes"] == "read me"
    assert row["rules"] == [
        {
            "kind": "calling_window",
            "channel": "voice",
            "params": {"startHour": 9, "endHour": 17},
            "citation": "review-cite",
        }
    ]


def test_reject_refuses_what_is_not_pending(db_tx) -> None:
    if not schema_ready.w4_ready(db_tx):
        pytest.skip("W4 schema not applied")
    with pytest.raises(KeyError):
        policy_rules.reject_publication(db_tx, "PRS-NO-SUCH", actor_user_id=None)
    set_id = _draft(db_tx)
    with pytest.raises(ValueError, match="not_pending_approval"):
        policy_rules.reject_publication(db_tx, set_id, actor_user_id=None)


def _admins(conn) -> list[str]:
    from sqlalchemy import text

    return list(
        conn.execute(
            text("SELECT user_id FROM user_roles WHERE role_id = 'role-admin' ORDER BY user_id LIMIT 2")
        ).scalars()
    )


def test_a_statutory_set_publishes_only_in_platform_scope(db_tx, monkeypatch) -> None:
    """Submit on a statutory set was a row-security 500: the app role may read
    a tenant-less row and, outside platform scope, may not write it."""
    from sqlalchemy import text

    import authz
    import db_compliance

    if not schema_ready.w4_ready(db_tx):
        pytest.skip("W4 schema not applied")
    statutory = db_tx.execute(
        text("SELECT id FROM policy_rule_sets WHERE tenant_id IS NULL AND publication_state = 'draft' LIMIT 1")
    ).scalar()
    admins = _admins(db_tx)
    if statutory is None or len(admins) < 2:
        pytest.skip("needs a draft statutory set and two admins")
    monkeypatch.setenv("POLICY_PRODUCTION_PUBLICATION", "true")
    outsider = db_tx.execute(
        text("SELECT id FROM users WHERE id NOT IN (SELECT user_id FROM user_roles WHERE role_id = 'role-admin') LIMIT 1")
    ).scalar()

    # 1. An unscoped tenant write is refused, and loudly. Row security hides
    #    the row from UPDATE, which matches nothing and raises nothing; the
    #    lifecycle used to report "pending_approval" over an unchanged draft.
    if db_tx.execute(text("SELECT current_user")).scalar() != "collections":
        with pytest.raises(PermissionError, match="policy_rule_set_not_writable"):
            with db_tx.begin_nested():
                policy_rules.submit_for_approval(db_tx, statutory, actor_user_id=admins[0])
    # 2. Without perm-platform-write the app refuses before the database has to.
    if outsider and not authz.has_permission(outsider, authz.PLATFORM_WRITE):
        with pytest.raises(PermissionError, match="platform_write_required"):
            db_compliance.submit_policy_rule_set(statutory, actor_user_id=outsider)
    # 3. The lifecycle, four eyes and all.
    assert db_compliance.submit_policy_rule_set(statutory, actor_user_id=admins[0])["state"] == "pending_approval"
    with pytest.raises(ValueError, match="maker_checker_required"):
        db_compliance.approve_policy_rule_set(statutory, actor_user_id=admins[0])
    assert db_compliance.approve_policy_rule_set(statutory, actor_user_id=admins[1])["state"] == "published"


def test_break_glass_self_approval_is_allowlisted_reasoned_and_audited(db_tx, monkeypatch) -> None:
    """The maker may approve their own set only when the server names them,
    only with a written reason, and the audit chain says it was break-glass."""
    from sqlalchemy import text

    import db_compliance

    if not schema_ready.w4_ready(db_tx):
        pytest.skip("W4 schema not applied")
    statutory = db_tx.execute(
        text(
            "SELECT id FROM policy_rule_sets WHERE tenant_id IS NULL "
            "AND publication_state IN ('draft', 'pending_approval') LIMIT 1"
        )
    ).scalar()
    admins = _admins(db_tx)
    if statutory is None or not admins:
        pytest.skip("needs an unpublished statutory set and an admin")
    maker = admins[0]
    monkeypatch.setenv("POLICY_PRODUCTION_PUBLICATION", "true")
    state = db_tx.execute(
        text("SELECT publication_state FROM policy_rule_sets WHERE id = :id"), {"id": statutory}
    ).scalar()
    if state == "pending_approval":
        # Already submitted (on the live server, by its real maker): that
        # person is the one a self-approval is about.
        maker = db_tx.execute(
            text("SELECT published_by_user_id FROM policy_rule_sets WHERE id = :id"), {"id": statutory}
        ).scalar()
    else:
        db_compliance.submit_policy_rule_set(statutory, actor_user_id=maker)

    reason = "Sole platform operator on the demo tenant; RBI text confirmed 2026-09-25."
    monkeypatch.setenv("POLICY_SELF_APPROVE_USERS", "")
    with pytest.raises(ValueError, match="maker_checker_required"):
        db_compliance.approve_policy_rule_set(statutory, actor_user_id=maker)
    with pytest.raises(PermissionError, match="self_approval_not_permitted"):
        db_compliance.approve_policy_rule_set(statutory, actor_user_id=maker, self_approval_reason=reason)

    monkeypatch.setenv("POLICY_SELF_APPROVE_USERS", f"someone-else, {maker}")
    with pytest.raises(ValueError, match="self_approval_reason_too_short"):
        db_compliance.approve_policy_rule_set(statutory, actor_user_id=maker, self_approval_reason="ok")
    listed = {r["id"]: r for r in db_compliance.list_policy_rule_sets(tenant_id="hdfc.retail", actor_user_id=maker)}
    assert listed[statutory]["selfApprovable"] is True

    out = db_compliance.approve_policy_rule_set(statutory, actor_user_id=maker, self_approval_reason=reason)
    assert out["state"] == "published"
    entry = db_tx.execute(
        text(
            "SELECT payload FROM audit_log WHERE entity_type = 'policy_rule_set' AND entity_id = :id "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"id": statutory},
    ).scalar()
    assert entry["decision"] == "approved" and entry["breakGlass"] is True
    assert entry["reason"] == reason
