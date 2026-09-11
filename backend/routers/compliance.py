"""Compliance: consent, violations, redaction, PII findings.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import db
import db_compliance

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
    return db_compliance.list_policy_rule_sets(tenant_id=db.current_tenant())

@router.post("/compliance/policy-rules")
def create_policy_rule_draft(payload: dict[str, Any]):
    from schemas import PolicyRuleDraftRequest

    body = PolicyRuleDraftRequest.model_validate(payload)
    tenant_id = body.tenantId or (None if body.scope == "statutory" else db.current_tenant())
    try:
        return db_compliance.create_policy_rule_draft(
            body, tenant_id=tenant_id, actor_user_id=db._actor_user_id()
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post("/compliance/policy-rules/{set_id}/submit")
def submit_policy_rule_set(set_id: str):
    try:
        return db_compliance.submit_policy_rule_set(set_id, actor_user_id=db._actor_user_id())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post("/compliance/policy-rules/{set_id}/approve")
def approve_policy_rule_set(set_id: str):
    try:
        return db_compliance.approve_policy_rule_set(set_id, actor_user_id=db._actor_user_id())
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post("/compliance/policy-rules/{set_id}/reject")
def reject_policy_rule_set(set_id: str):
    return db_compliance.reject_policy_rule_set(set_id, actor_user_id=db._actor_user_id())

@router.post("/compliance/policy-replay")
def run_policy_replay(payload: dict[str, Any] | None = None):
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
    return db_compliance.run_policy_replay(
        window_start=start,
        window_end=end,
        expected_digest=body.get("expectedDigest"),
        tenant_id=db.current_tenant(),
    )

@router.get("/compliance/complaint-pack/{customer_id}")
def get_complaint_pack(customer_id: str):
    import complaint_pack

    try:
        return db_compliance.get_complaint_pack(customer_id, tenant_id=db.current_tenant())
    except complaint_pack.IncompletePack as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.get("/compliance/subject-requests")
def list_subject_requests(overdueOnly: bool = Query(default=False)):
    return db_compliance.list_subject_requests(
        overdue_only=overdueOnly, tenant_id=db.current_tenant()
    )

@router.post("/compliance/subject-requests")
def create_subject_request(payload: dict[str, Any]):
    from schemas import SubjectRequestCreateRequest

    body = SubjectRequestCreateRequest.model_validate(payload)
    try:
        return db_compliance.create_subject_request(
            body, tenant_id=db.current_tenant(), actor_user_id=db._actor_user_id()
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post("/compliance/subject-requests/{request_id}/transition")
def transition_subject_request(request_id: str, payload: dict[str, Any]):
    from schemas import SubjectRequestTransitionRequest

    body = SubjectRequestTransitionRequest.model_validate(payload)
    try:
        return db_compliance.transition_subject_request(
            request_id, body, actor_user_id=db._actor_user_id()
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

    body = SecurityIncidentCreateRequest.model_validate(payload)
    return db_compliance.create_security_incident(
        body, tenant_id=db.current_tenant(), actor_user_id=db._actor_user_id()
    )

@router.get("/compliance/security-incidents")
def list_security_incidents():
    return db_compliance.list_security_incidents(tenant_id=db.current_tenant())
