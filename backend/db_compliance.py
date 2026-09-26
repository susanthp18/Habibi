"""Persistence for the compliance router (policy rules, replay, subject rights, incidents).

Peeled from ``routers/compliance.py``: a router validates and returns; it does
not own a transaction or author SQL. Each function here is one route's
transaction and returns exactly the shape the handler used to. Domain errors
(``KeyError``, ``ValueError``, ``PermissionError``, ``RuntimeError``,
``complaint_pack.IncompletePack``) propagate for the router to map. Reach the
engine through :func:`_db`, never ``from db_core import engine``: the ``db_tx``
fixture wraps ``db.engine``, and a name bound from ``db_core`` bypasses that
proxy.
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import text
from typing import Any


def _db():
    """The ``db`` module object, resolved at call time."""
    import db as d

    return d


def _scope_global_set(conn: Any, set_id: str, *, actor_user_id: str | None, action: str) -> None:
    """A tenant-less (statutory) set is written only in platform scope.

    Row security refuses the write otherwise -- it used to reach the browser as
    a 500 on every Submit. Unknown ids fall through to the lifecycle function,
    which raises the 404.
    """
    row = conn.execute(
        text("SELECT tenant_id FROM policy_rule_sets WHERE id = :id"), {"id": set_id}
    ).first()
    if row is not None and row[0] is None:
        import platform_scope

        platform_scope.enter(conn, actor_user_id=actor_user_id, reason=f"{action} statutory rule set {set_id}")


def list_policy_rule_sets(*, tenant_id: str, actor_user_id: str | None = None) -> Any:
    """Every set, and per set whether *this* actor may break-glass approve it
    -- the screen offers the control only where the server would accept it."""
    import policy_rules

    with _db().engine.connect() as conn:
        rows = policy_rules.list_rule_sets(conn, tenant_id=tenant_id)
        may_self_approve = policy_rules.self_approval_allowed(conn, actor_user_id)
    for row in rows:
        row["selfApprovable"] = bool(
            may_self_approve
            and row.get("publication_state") == "pending_approval"
            and row.get("published_by_user_id") == actor_user_id
        )
    return rows


def _audit(conn: Any, set_id: str, *, actor_user_id: str | None, decision: str, **detail: Any) -> None:
    """Every publication step on the hash-chained audit log, in the same
    transaction as the step -- a decision that is not recorded did not happen."""
    from agent_core import change_log

    row = conn.execute(
        text("SELECT scope, version, label FROM policy_rule_sets WHERE id = :id"), {"id": set_id}
    ).mappings().first()
    change_log.record_policy_decision(
        conn,
        tenant_id=_db().current_tenant(),
        actor_user_id=actor_user_id,
        set_id=set_id,
        decision=decision,
        detail={**(dict(row) if row else {}), **detail},
    )


def create_policy_rule_draft(body: Any, *, tenant_id: str | None, actor_user_id: str) -> dict[str, Any]:
    import policy_rules

    with _db().engine.begin() as conn:
        if tenant_id is None:
            import platform_scope

            platform_scope.enter(conn, actor_user_id=actor_user_id, reason="draft a statutory rule set")
        set_id = policy_rules.create_draft(
            conn,
            scope=body.scope,
            version=body.version,
            label=body.label,
            effective_from=body.effectiveFrom,
            effective_to=body.effectiveTo,
            notes=body.notes,
            tenant_id=tenant_id,
            product_id=body.productId,
            rules=[rule.model_dump() for rule in body.rules],
            actor_user_id=actor_user_id,
        )
    return {"id": set_id}


def submit_policy_rule_set(set_id: str, *, actor_user_id: str) -> dict[str, Any]:
    import policy_rules

    with _db().engine.begin() as conn:
        _scope_global_set(conn, set_id, actor_user_id=actor_user_id, action="submit")
        policy_rules.submit_for_approval(conn, set_id, actor_user_id=actor_user_id)
        _audit(conn, set_id, actor_user_id=actor_user_id, decision="submitted")
    return {"id": set_id, "state": "pending_approval"}


def approve_policy_rule_set(
    set_id: str, *, actor_user_id: str, self_approval_reason: str | None = None
) -> dict[str, Any]:
    import logging

    import policy_rules

    with _db().engine.begin() as conn:
        _scope_global_set(conn, set_id, actor_user_id=actor_user_id, action="approve")
        break_glass = policy_rules.approve_publication(
            conn, set_id, actor_user_id=actor_user_id, self_approval_reason=self_approval_reason
        )
        _audit(
            conn,
            set_id,
            actor_user_id=actor_user_id,
            decision="approved",
            breakGlass=break_glass,
            reason=(self_approval_reason or "").strip() if break_glass else None,
        )
    if break_glass:
        # WARNING by design: four eyes were waived, and that should be the
        # line anyone scanning the log for this set finds first.
        logging.getLogger(__name__).warning(
            "policy.break_glass self-approval · set=%s · actor=%s · reason=%r",
            set_id,
            actor_user_id,
            (self_approval_reason or "").strip(),
        )
    return {"id": set_id, "state": "published"}


def reject_policy_rule_set(set_id: str, *, actor_user_id: str) -> dict[str, Any]:
    import policy_rules

    with _db().engine.begin() as conn:
        _scope_global_set(conn, set_id, actor_user_id=actor_user_id, action="reject")
        policy_rules.reject_publication(conn, set_id, actor_user_id=actor_user_id)
        _audit(conn, set_id, actor_user_id=actor_user_id, decision="rejected")
    return {"id": set_id, "state": "rejected"}


def run_policy_replay(
    *, window_start: datetime, window_end: datetime, expected_digest: Any, tenant_id: str
) -> Any:
    import policy_replay

    with _db().engine.begin() as conn:
        return policy_replay.replay(
            conn,
            window_start=window_start,
            window_end=window_end,
            expected_digest=expected_digest,
            tenant_id=tenant_id,
        )


def get_complaint_pack(customer_id: str, *, tenant_id: str) -> Any:
    import complaint_pack

    with _db().engine.connect() as conn:
        return complaint_pack.compose(conn, tenant_id=tenant_id, customer_id=customer_id)


def list_subject_requests(*, overdue_only: bool, tenant_id: str) -> Any:
    import subject_rights

    with _db().engine.connect() as conn:
        return subject_rights.list_requests(conn, tenant_id=tenant_id, overdue_only=overdue_only)


def create_subject_request(body: Any, *, tenant_id: str, actor_user_id: str) -> Any:
    import subject_rights

    with _db().engine.begin() as conn:
        return subject_rights.create_request(
            conn,
            tenant_id=tenant_id,
            customer_id=body.customerId,
            kind=body.kind,
            actor_user_id=actor_user_id,
            note=body.note,
        )


def transition_subject_request(request_id: str, body: Any, *, actor_user_id: str) -> Any:
    """Fulfilling an erasure request runs the erasure; every other move is a transition."""
    import subject_rights

    with _db().engine.begin() as conn:
        kind = conn.execute(
            text("SELECT kind FROM subject_requests WHERE id = :id"), {"id": request_id}
        ).scalar()
        if body.state == "fulfilled" and kind == "erasure":
            return subject_rights.fulfil_erasure(conn, request_id, actor_user_id=actor_user_id)
        return subject_rights.transition(
            conn,
            request_id,
            state=body.state,
            actor_user_id=actor_user_id,
            note=body.note,
            evidence_ref=body.evidenceRef,
        )


def create_security_incident(body: Any, *, tenant_id: str, actor_user_id: str) -> dict[str, Any]:
    d = _db()
    incident_id = d._id("INC")
    with d.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO security_incidents (
                  id, tenant_id, severity, state, summary, evidence_ref,
                  actor_user_id
                ) VALUES (
                  :id, :tid, :severity, 'open', :summary, :evidence, :actor
                )
                """
            ),
            {
                "id": incident_id,
                "tid": tenant_id,
                "severity": body.severity,
                "summary": body.summary,
                "evidence": body.evidenceRef,
                "actor": actor_user_id,
            },
        )
    return {"id": incident_id, "state": "open"}


def list_security_incidents(*, tenant_id: str) -> list[dict[str, Any]]:
    with _db().engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, severity, state, summary, detected_at
                FROM security_incidents
                WHERE tenant_id = :tid
                ORDER BY detected_at DESC
                LIMIT 200
                """
            ),
            {"tid": tenant_id},
        ).mappings().all()
    return [dict(r) for r in rows]
