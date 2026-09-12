"""Routing rules and their audit.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import db

from fastapi import APIRouter
from fastapi import HTTPException
from schemas import (
    OkResponse,
    RoutingAuditEntryResponse,
    RoutingReorderRequest,
    RoutingRuleCreateRequest,
    RoutingRuleExecutionResponse,
    RoutingRuleListResponse,
    RoutingRulePatchRequest,
    RoutingSimulateRequest,
    RoutingSimulateResponse,
)

from api_support import _handle_write, Utf8JSONResponse, ROUTER_DEPENDENCIES

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.get("/routing-rules", response_model=list[RoutingRuleListResponse])
def list_routing_rules():
    """Priority-ordered routing library with matched-execution aggregates."""
    return db.list_routing_rules()

@router.get(
    "/routing-rules/{rule_id}/executions",
    response_model=list[RoutingRuleExecutionResponse],
)
def list_routing_rule_executions(rule_id: str):
    try:
        return db.list_routing_rule_executions(rule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/routing-rules", response_model=RoutingRuleListResponse)
def create_routing_rule(payload: RoutingRuleCreateRequest):
    return _handle_write(db.create_routing_rule, payload.model_dump(exclude_unset=True, by_alias=True))

@router.patch("/routing-rules/{rule_id}", response_model=RoutingRuleListResponse)
def patch_routing_rule(rule_id: str, payload: RoutingRulePatchRequest):
    return _handle_write(
        db.patch_routing_rule, rule_id, payload.model_dump(exclude_unset=True, by_alias=True)
    )

@router.post("/routing-rules/simulate", response_model=RoutingSimulateResponse)
def simulate_routing_rules(payload: RoutingSimulateRequest):
    """Dry-run of the rule library against a hand-built context; writes nothing."""
    return db.simulate_routing_rules(payload.context.model_dump())

@router.post("/routing-rules/reorder", response_model=list[RoutingRuleListResponse])
def reorder_routing_rules(payload: RoutingReorderRequest):
    return _handle_write(db.reorder_routing_rules, payload.orderedIds)

@router.delete("/routing-rules/{rule_id}", response_model=OkResponse)
def delete_routing_rule(rule_id: str):
    _handle_write(db.delete_routing_rule, rule_id)
    return {"ok": True}

@router.get("/routing-audit", response_model=list[RoutingAuditEntryResponse])
def list_routing_audit():
    return db.list_routing_audit()

