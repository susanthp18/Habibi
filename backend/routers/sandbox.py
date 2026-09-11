"""Sandbox runs and twins.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import db
import sandbox_runtime
import secrets

from fastapi import APIRouter
from fastapi import HTTPException
from schemas import (
    IdStatusResponse,
    PaymentEventWebhookResponse,
    SandboxPaymentEventRequest,
    SandboxRunCreateRequest,
    SandboxRunDetailResponse,
    SandboxRunResponse,
    SandboxScenarioResponse,
    SandboxTurnCreateRequest,
    SandboxTurnResponse,
    SimulationTwinResponse,
    TuningPresetResponse,
    TwinRunRequest,
    TwinRunResponse,
)

from api_support import _handle_write, Utf8JSONResponse, ROUTER_DEPENDENCIES

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.post(
    "/sandbox/payment-events",
    response_model=PaymentEventWebhookResponse,
    response_model_exclude_unset=True,
)
def sandbox_payment_event(payload: SandboxPaymentEventRequest):
    """Dev-only: same ingest() as the HMAC webhook, source defaults to sandbox."""
    import payment_events as pe
    import payments

    if payments.is_production():
        raise HTTPException(status_code=403, detail="sandbox_payment_events_disabled")
    body = payload.model_dump(exclude_none=True)
    body.setdefault("source", "sandbox")
    if not body.get("sourceRef") and not body.get("source_ref"):
        body["sourceRef"] = f"sandbox-{secrets.token_hex(8)}"
    try:
        return pe.ingest_and_deliver(db.engine, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/twins", response_model=list[SimulationTwinResponse])
def list_simulation_twins():
    from agent_core.twin import ensure_default_twin, list_twins

    ensure_default_twin()
    return list_twins()

@router.post("/twins/{twin_id}/run", response_model=TwinRunResponse)
def run_simulation_twin(twin_id: str, payload: TwinRunRequest | None = None):
    from agent_core.twin import replay_bounce_ladder

    return replay_bounce_ladder(twin_id, state=payload.state if payload else None)

@router.post("/sandbox/runs", response_model=SandboxRunResponse)
def create_sandbox_run(payload: SandboxRunCreateRequest):
    """Start a sandbox session bound to a prompt version (or active deployment)."""
    body = payload.model_dump()
    if body.get("context") is None:
        body.pop("context", None)
    else:
        body["context"] = {k: v for k, v in body["context"].items() if v is not None}
    try:
        return sandbox_runtime.create_sandbox_run(body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith("kb_snapshot_not_found"):
            raise HTTPException(status_code=400, detail=msg) from exc
        raise HTTPException(status_code=409, detail=msg) from exc

@router.get("/sandbox/scenarios", response_model=list[SandboxScenarioResponse])
def list_sandbox_scenarios():
    """Scripted personas + customer turns for the sandbox picker."""
    return db.list_sandbox_scenarios()

@router.get("/sandbox/runs/{run_id}", response_model=SandboxRunDetailResponse)
def get_sandbox_run(run_id: str):
    """Run + persisted turns (ascending turnIndex) with grounded chunk titles."""
    try:
        return db.get_sandbox_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/sandbox/runs/{run_id}/turns", response_model=SandboxTurnResponse)
def append_sandbox_turn(run_id: str, payload: SandboxTurnCreateRequest):
    """Customer turn → KB retrieve + Azure chat → persisted bot reply."""
    body = payload.model_dump()
    if body.get("context") is None:
        body.pop("context", None)
    else:
        body["context"] = {k: v for k, v in body["context"].items() if v is not None}
    try:
        return sandbox_runtime.append_sandbox_turn(run_id, body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

@router.post("/sandbox/runs/{run_id}/complete", response_model=IdStatusResponse)
def complete_sandbox_run(run_id: str):
    return _handle_write(sandbox_runtime.complete_sandbox_run, run_id)

@router.get("/sandbox/tuning/presets", response_model=list[TuningPresetResponse])
def list_sandbox_tuning_presets():
    from agent_core.tuning import list_presets

    return list_presets()

