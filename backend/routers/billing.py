"""Billing and export jobs.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import db

from fastapi import APIRouter
from fastapi import HTTPException, Query, Response
from schemas import (
    BillingBudgetRuleResponse,
    BillingOverviewResponse,
    BudgetRuleUpsertRequest,
    ExportJobCreateRequest,
    ExportJobPatchRequest,
    ExportJobResponse,
)

from api_support import _handle_write, Utf8JSONResponse, ROUTER_DEPENDENCIES

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.get("/billing", response_model=BillingOverviewResponse)
def get_billing(
    period: str = Query("mtd"),
    env: str = Query("production"),
):
    """Billing & Usage Analytics — filtered spend, budgets, invoices.

    Always the caller's tenant. The screen used to send ``tenantId`` and the
    server used to honour it, so any holder of ``billing:read`` could read
    another bank's spend by editing a query string. A deployment serves one
    bank; the query-string selector never had a legitimate second value.
    """
    try:
        return db.billing_overview(period, db.current_tenant(), env)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

# CSV download by design. Listed in tests/test_route_structure.py::_UNTYPED_BY_DESIGN.
@router.get("/billing/export.csv", response_class=Response)
def export_billing_csv(
    period: str = Query("mtd"),
    env: str = Query("production"),
):
    try:
        csv_body = db.billing_export_csv(period, db.current_tenant(), env)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="billing-usage.csv"'},
    )

@router.post("/billing/budgets/{budget_id}/rules", response_model=BillingBudgetRuleResponse)
def create_budget_rule(budget_id: str, payload: BudgetRuleUpsertRequest):
    try:
        return db.upsert_budget_rule(budget_id, payload.model_dump())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.patch("/billing/budgets/{budget_id}/rules/{rule_id}", response_model=BillingBudgetRuleResponse)
def patch_budget_rule(budget_id: str, rule_id: str, payload: BudgetRuleUpsertRequest):
    try:
        return db.upsert_budget_rule(budget_id, payload.model_dump(), rule_id=rule_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

# 204 with no body by design. Listed in tests/test_route_structure.py::_UNTYPED_BY_DESIGN.
@router.delete("/billing/budgets/{budget_id}/rules/{rule_id}", status_code=204, response_class=Response)
def delete_budget_rule(budget_id: str, rule_id: str):
    try:
        db.delete_budget_rule(budget_id, rule_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)

@router.get("/export-jobs", response_model=list[ExportJobResponse])
def list_export_jobs(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_export_jobs(limit=limit, offset=offset)

@router.post("/export-jobs", response_model=ExportJobResponse)
def create_export_job(payload: ExportJobCreateRequest):
    return _handle_write(db.create_export_job, payload.model_dump(exclude_unset=True))

@router.patch("/export-jobs/{job_id}", response_model=ExportJobResponse)
def patch_export_job(job_id: str, payload: ExportJobPatchRequest):
    return _handle_write(db.patch_export_job, job_id, payload.model_dump(exclude_unset=True))

