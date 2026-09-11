"""Compliance: consent, violations, redaction, PII findings.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import db

from fastapi import APIRouter
from fastapi import HTTPException, Query
from schemas import (
    ConsentListResponse,
    ConsentPatchRequest,
    CustomerResponse,
    OptOutCreateRequest,
    PiiFindingPatchRequest,
    PiiFindingPatchResponse,
    RedactionAudioMuteRequest,
    RedactionRecordListResponse,
    RedactionRecordPatchRequest,
    RedactionRulePatchRequest,
    RedactionRuleResponse,
    ViolationListResponse,
    ViolationNoteCreateRequest,
    ViolationPatchRequest,
)
from typing import Any

from api_support import _handle_write, Utf8JSONResponse, ROUTER_DEPENDENCIES

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.get("/consent", response_model=list[ConsentListResponse])
def list_consent(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_consent(limit=limit, offset=offset)

@router.patch("/consent/{customer_id}", response_model=CustomerResponse)
def patch_consent(customer_id: str, payload: ConsentPatchRequest):
    # exclude_unset (not exclude_none) so an explicit null can clear/renew fields.
    return _handle_write(db.patch_consent, customer_id, payload.model_dump(exclude_unset=True))

@router.post("/consent/{customer_id}/opt-out", response_model=CustomerResponse)
def opt_out(customer_id: str, payload: OptOutCreateRequest):
    return _handle_write(db.opt_out, customer_id, payload.model_dump(exclude_unset=True))

@router.get("/compliance/rule-coverage")
def get_rule_coverage():
    """Per rule: does a detector exist, and what has it actually found?

    The Compliance Risk page could previously show a rule with no violations
    and a rule nobody is checking as the same thing — an empty row. Fifteen of
    the sixteen seeded rules were in the second category. `state` is the
    three-way answer: clean / breached / unverified.
    """
    from agent_core import compliance

    return compliance.detector_coverage()

@router.post("/compliance/rescan")
def rescan_compliance(
    limit: int = Query(200, ge=1, le=2000),
    all: bool = Query(False, description="Drain the whole queue, not one batch"),
):
    """Re-judge interactions the ledger has not evaluated at this rules version.

    The worker does this on a timer; this endpoint exists so a rule change can
    be applied to history on demand instead of waiting for the next tick.
    """
    from agent_core import compliance

    return compliance.backfill(batch=limit) if all else compliance.sweep(limit=limit)

@router.get("/violations", response_model=list[ViolationListResponse])
def list_violations():
    return db.list_violations()

@router.patch("/violations/{violation_id}", response_model=ViolationListResponse)
def patch_violation(violation_id: str, payload: ViolationPatchRequest):
    # exclude_unset (not exclude_none) so explicit null clears assignee.
    return _handle_write(db.patch_violation, violation_id, payload.model_dump(exclude_unset=True))

@router.post("/violations/{violation_id}/notes")
def add_violation_note(violation_id: str, payload: ViolationNoteCreateRequest):
    return _handle_write(db.add_violation_note, violation_id, payload.model_dump())

@router.get("/redaction-records", response_model=list[RedactionRecordListResponse])
def list_redaction_records():
    """Redaction Hub queue — nested findings + audio segments. Masked PII only for non-Admin."""
    return db.list_redaction_records()

@router.get("/redaction-records/{redaction_id}", response_model=RedactionRecordListResponse)
def get_redaction_record(redaction_id: str):
    try:
        return db.get_redaction_record(redaction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.get("/redaction-rules", response_model=list[RedactionRuleResponse])
def list_redaction_rules():
    return db.list_redaction_rules()

@router.patch("/redaction-records/{redaction_id}", response_model=RedactionRecordListResponse)
def patch_redaction_record(redaction_id: str, payload: RedactionRecordPatchRequest):
    return _handle_write(
        db.patch_redaction_record, redaction_id, payload.model_dump(exclude_unset=True)
    )

@router.patch("/pii-findings/{finding_id}", response_model=PiiFindingPatchResponse)
def patch_pii_finding(finding_id: str, payload: PiiFindingPatchRequest):
    return _handle_write(
        db.patch_pii_finding, finding_id, payload.model_dump(exclude_unset=True)
    )

@router.patch("/redaction-records/{redaction_id}/audio-mute")
def patch_redaction_audio_mute(redaction_id: str, payload: RedactionAudioMuteRequest):
    return _handle_write(
        db.patch_audio_segment_mute,
        redaction_id,
        payload.findingId,
        payload.muted,
    )

@router.patch("/redaction-rules/{pii_type}", response_model=RedactionRuleResponse)
def patch_redaction_rule(pii_type: str, payload: RedactionRulePatchRequest):
    return _handle_write(
        db.patch_redaction_rule, pii_type, payload.model_dump(exclude_unset=True)
    )

@router.get("/compliance/policy-export")
def export_policy_bundle(fmt: str = Query(default="opa")):
    from agent_core.policy_export import bundle

    try:
        return bundle(fmt=fmt)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.get("/compliance/policy-rules")
def list_policy_rule_sets():
    import policy_rules

    with db.engine.connect() as conn:
        return policy_rules.list_rule_sets(conn, tenant_id=db.current_tenant())

@router.post("/compliance/policy-rules")
def create_policy_rule_draft(payload: dict[str, Any]):
    import policy_rules
    from schemas import PolicyRuleDraftRequest

    body = PolicyRuleDraftRequest.model_validate(payload)
    with db.engine.begin() as conn:
        try:
            set_id = policy_rules.create_draft(
                conn,
                scope=body.scope,
                version=body.version,
                label=body.label,
                effective_from=body.effectiveFrom,
                effective_to=body.effectiveTo,
                notes=body.notes,
                tenant_id=body.tenantId or (
                    None if body.scope == "statutory" else db.current_tenant()
                ),
                product_id=body.productId,
                rules=body.rules,
                actor_user_id=db._actor_user_id(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": set_id}

@router.post("/compliance/policy-rules/{set_id}/submit")
def submit_policy_rule_set(set_id: str):
    import policy_rules

    with db.engine.begin() as conn:
        try:
            policy_rules.submit_for_approval(
                conn, set_id, actor_user_id=db._actor_user_id()
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": set_id, "state": "pending_approval"}

@router.post("/compliance/policy-rules/{set_id}/approve")
def approve_policy_rule_set(set_id: str):
    import policy_rules

    with db.engine.begin() as conn:
        try:
            policy_rules.approve_publication(
                conn, set_id, actor_user_id=db._actor_user_id()
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": set_id, "state": "published"}

@router.post("/compliance/policy-rules/{set_id}/reject")
def reject_policy_rule_set(set_id: str):
    import policy_rules

    with db.engine.begin() as conn:
        policy_rules.reject_publication(
            conn, set_id, actor_user_id=db._actor_user_id()
        )
    return {"id": set_id, "state": "rejected"}

@router.post("/compliance/policy-replay")
def run_policy_replay(payload: dict[str, Any] | None = None):
    import policy_replay
    from datetime import datetime, timezone

    body = payload or {}
    start = (
        datetime.fromisoformat(str(body.get("windowStart")))
        if body.get("windowStart")
        else datetime(1970, 1, 1, tzinfo=timezone.utc)
    )
    end = (
        datetime.fromisoformat(str(body.get("windowEnd")))
        if body.get("windowEnd")
        else datetime.now(timezone.utc)
    )
    with db.engine.begin() as conn:
        return policy_replay.replay(
            conn,
            window_start=start,
            window_end=end,
            expected_digest=body.get("expectedDigest"),
            tenant_id=db.current_tenant(),
        )

@router.get("/compliance/complaint-pack/{customer_id}")
def get_complaint_pack(customer_id: str):
    import complaint_pack

    with db.engine.connect() as conn:
        try:
            return complaint_pack.compose(
                conn, tenant_id=db.current_tenant(), customer_id=customer_id
            )
        except complaint_pack.IncompletePack as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.get("/compliance/subject-requests")
def list_subject_requests(overdueOnly: bool = Query(default=False)):
    import subject_rights

    with db.engine.connect() as conn:
        return subject_rights.list_requests(
            conn, tenant_id=db.current_tenant(), overdue_only=overdueOnly
        )

@router.post("/compliance/subject-requests")
def create_subject_request(payload: dict[str, Any]):
    import subject_rights
    from schemas import SubjectRequestCreateRequest

    body = SubjectRequestCreateRequest.model_validate(payload)
    with db.engine.begin() as conn:
        try:
            return subject_rights.create_request(
                conn,
                tenant_id=db.current_tenant(),
                customer_id=body.customerId,
                kind=body.kind,
                actor_user_id=db._actor_user_id(),
                note=body.note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post("/compliance/subject-requests/{request_id}/transition")
def transition_subject_request(request_id: str, payload: dict[str, Any]):
    import subject_rights
    from schemas import SubjectRequestTransitionRequest
    from sqlalchemy import text as _text

    body = SubjectRequestTransitionRequest.model_validate(payload)
    with db.engine.begin() as conn:
        try:
            kind = conn.execute(
                _text("SELECT kind FROM subject_requests WHERE id = :id"),
                {"id": request_id},
            ).scalar()
            if body.state == "fulfilled" and kind == "erasure":
                return subject_rights.fulfil_erasure(
                    conn, request_id, actor_user_id=db._actor_user_id()
                )
            return subject_rights.transition(
                conn,
                request_id,
                state=body.state,
                actor_user_id=db._actor_user_id(),
                note=body.note,
                evidence_ref=body.evidenceRef,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.post("/compliance/security-incidents")
def create_security_incident(payload: dict[str, Any]):
    from schemas import SecurityIncidentCreateRequest
    from sqlalchemy import text as _text
    import uuid as _uuid

    body = SecurityIncidentCreateRequest.model_validate(payload)
    incident_id = f"INC-{_uuid.uuid4().hex[:10].upper()}"
    with db.engine.begin() as conn:
        conn.execute(
            _text(
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
                "tid": db.current_tenant(),
                "severity": body.severity,
                "summary": body.summary,
                "evidence": body.evidenceRef,
                "actor": db._actor_user_id(),
            },
        )
    return {"id": incident_id, "state": "open"}

@router.get("/compliance/security-incidents")
def list_security_incidents():
    from sqlalchemy import text as _text

    with db.engine.connect() as conn:
        rows = conn.execute(
            _text(
                """
                SELECT id, severity, state, summary, detected_at
                FROM security_incidents
                WHERE tenant_id = :tid
                ORDER BY detected_at DESC
                LIMIT 200
                """
            ),
            {"tid": db.current_tenant()},
        ).mappings().all()
    return [dict(r) for r in rows]

