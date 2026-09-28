"""Integrations: providers, connectors, MCP, gateway, vault.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import db
import os

from fastapi import APIRouter
from fastapi import HTTPException
from schemas import (
    BankBreachCoverageResponse,
    BankComplaintEventResponse,
    BankComplaintFiledResponse,
    BankComplaintFileRequest,
    BankContractStatusResponse,
    BankFairnessResponse,
    BankIngestResponse,
    BankManifestIngestRequest,
    BankManifestResponse,
    BankOutboxItemResponse,
    BankReadinessResponse,
    BankReconciliationBreakResponse,
    GatewayStatusResponse,
    McpKeyMintedResponse,
    McpKeyMintRequest,
    McpKeyResponse,
    McpStatusResponse,
    McpTaskResponse,
    OkResponse,
)

from api_support import _handle_write, Utf8JSONResponse, ROUTER_DEPENDENCIES

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.get("/mcp/keys", response_model=list[McpKeyResponse])
def list_mcp_keys_api():
    from agent_core.mcp_http.auth import list_keys

    return list_keys()

@router.post("/mcp/keys", response_model=McpKeyMintedResponse)
def mint_mcp_key_api(payload: McpKeyMintRequest):
    from agent_core.mcp_http.auth import mint_key

    return _handle_write(mint_key, name=payload.name or "key", scopes=payload.scopes)

@router.post("/mcp/keys/{key_id}/rotate", response_model=McpKeyMintedResponse)
def rotate_mcp_key_api(key_id: str):
    from agent_core.mcp_http.auth import rotate_key

    return _handle_write(rotate_key, key_id)

@router.post("/mcp/keys/{key_id}/revoke", response_model=OkResponse)
def revoke_mcp_key_api(key_id: str):
    from agent_core.mcp_http.auth import revoke_key

    _handle_write(revoke_key, key_id)
    return {"ok": True}

@router.get("/mcp/tasks", response_model=list[McpTaskResponse])
def list_mcp_tasks_api(status: str | None = None):
    from agent_core.mcp_http.tasks import list_tasks

    return list_tasks(status=status)

@router.get("/mcp/tasks/{task_id}", response_model=McpTaskResponse)
def get_mcp_task_api(task_id: str):
    from agent_core.mcp_http.tasks import get_task

    row = get_task(task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="mcp_task_not_found")
    return row

@router.get("/mcp/status", response_model=McpStatusResponse)
def mcp_status_api():
    from agent_core.platform_flags import mcp_apps_enabled, mcp_http_enabled, mcp_tasks_enabled

    host = (os.getenv("MCP_HTTP_HOST") or "127.0.0.1").strip()
    port = os.getenv("MCP_HTTP_PORT") or "8081"
    return {
        "stdioCommand": "python -m mcp_server",
        "httpEnabled": mcp_http_enabled(),
        "httpUrl": f"http://{host}:{port}/mcp",
        "tasksEnabled": mcp_tasks_enabled(),
        "appsEnabled": mcp_apps_enabled(),
        "mtls": bool((os.getenv("MCP_TLS_CAFILE") or "").strip()),
        "resources": [
            "customer://{id}",
            "account://{id}/ledger",
            "kb://snapshot/{id}",
            "interaction://{id}/trace",
            "policy://authority-matrix",
        ],
    }

@router.get("/gateway/status", response_model=GatewayStatusResponse)
def gateway_status_api():
    from agent_core.platform_flags import llm_gateway_enabled
    from llm_gateway.client import PROFILES, base_url, cap_inr, spent_today_inr

    profiles = {}
    for p in PROFILES:
        env_model = os.getenv(f"LLM_GATEWAY_{p.upper()}_MODEL")
        profiles[p] = {
            "capInr": cap_inr(p),
            "spentTodayInr": spent_today_inr(p),
            "model": env_model,
            "envModel": env_model,
        }
    return {
        "enabled": llm_gateway_enabled(),
        "baseUrl": base_url() or None,
        "profiles": profiles,
        "killSwitch": "azure_openai" if not llm_gateway_enabled() else None,
        "voiceSloMs": 800,
    }

@router.get("/integrations/bank/contracts", response_model=BankContractStatusResponse)
def bank_contract_status():
    from bank_boundary import api as bank_api

    return bank_api.read(bank_api.contract_status)

@router.get("/integrations/bank/manifests", response_model=list[BankManifestResponse])
def bank_manifests():
    from bank_boundary import api as bank_api

    return bank_api.read(bank_api.manifests)

@router.post("/integrations/bank/manifests", response_model=BankIngestResponse)
def bank_ingest_manifest(body: BankManifestIngestRequest):
    from bank_boundary import api as bank_api
    from bank_boundary.ingest import IngestRejected

    try:
        return bank_api.write(bank_api.ingest_manifest, body=body)
    except IngestRejected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.get("/integrations/bank/reconciliation", response_model=list[BankReconciliationBreakResponse])
def bank_reconciliation():
    from bank_boundary import api as bank_api

    return bank_api.read(bank_api.reconciliation)

@router.get("/integrations/bank/readiness", response_model=BankReadinessResponse)
def bank_readiness():
    from bank_boundary import api as bank_api

    return bank_api.read(bank_api.readiness)

@router.get("/integrations/bank/outbox", response_model=list[BankOutboxItemResponse])
def bank_outbox():
    from bank_boundary import api as bank_api

    return bank_api.read(bank_api.outbox_state)

@router.get("/integrations/bank/breach-coverage", response_model=BankBreachCoverageResponse)
def bank_breach_coverage():
    from bank_boundary import api as bank_api

    return bank_api.read(bank_api.breach_coverage)

@router.get("/integrations/bank/fairness", response_model=BankFairnessResponse)
def bank_fairness():
    from bank_boundary import api as bank_api

    return bank_api.read(bank_api.fairness)

@router.post("/integrations/bank/complaints", response_model=BankComplaintFiledResponse)
def bank_file_complaint(body: BankComplaintFileRequest):
    from bank_boundary import api as bank_api
    from bank_boundary.ingest import IngestRejected

    try:
        return bank_api.write(
            bank_api.file_complaint,
            customer_id=body.customerId,
            kind=body.kind,
            actor_user_id=db._actor_user_id(),
        )
    except IngestRejected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.get("/integrations/bank/complaints", response_model=list[BankComplaintEventResponse])
def bank_list_complaints():
    from bank_boundary import api as bank_api

    return bank_api.read(bank_api.list_complaints)
