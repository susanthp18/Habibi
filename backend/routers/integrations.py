"""Integrations: providers, connectors, MCP, gateway, vault.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import db
import ops_screens
import os

from fastapi import APIRouter
from fastapi import HTTPException, Query
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
    ConnectorCimdRequest,
    ConnectorCimdResponse,
    ConnectorHealthTestResponse,
    ConnectorResponse,
    ConnectorUpsertRequest,
    GatewayCanaryPromoteRequest,
    GatewayCanaryProposeRequest,
    GatewayCanaryResponse,
    GatewayCanaryStateResponse,
    GatewayStatusResponse,
    McpKeyMintedResponse,
    McpKeyMintRequest,
    McpKeyResponse,
    McpStatusResponse,
    McpTaskResponse,
    OkResponse,
    ProviderBindingInput,
    ProviderBindingItem,
    ProviderEnabledPatchRequest,
    ProviderModelItem,
    ProviderPoolStatus,
    ProviderResponse,
    ProviderTestLogResponse,
    VaultRefPutRequest,
    VaultRefResponse,
    VaultRefRotateRequest,
)

from api_support import _handle_write, Utf8JSONResponse, ROUTER_DEPENDENCIES

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.get("/providers", response_model=list[ProviderResponse])
def list_providers(env: str = Query(default="sandbox")):
    return ops_screens.list_providers(env)

@router.patch("/providers/{provider_id}/configs/{environment}", response_model=ProviderResponse)
def patch_provider_config(
    provider_id: str, environment: str, payload: ProviderEnabledPatchRequest
):
    try:
        return ops_screens.patch_provider_enabled(
            provider_id, environment, payload.enabled
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/providers/{provider_id}/test", response_model=ProviderTestLogResponse)
def test_provider(provider_id: str, env: str = Query(default="sandbox")):
    try:
        return ops_screens.test_provider(provider_id, env)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.get("/providers/{provider_id}/test-logs", response_model=list[ProviderTestLogResponse])
def list_provider_test_logs(provider_id: str):
    return ops_screens.list_provider_test_logs(provider_id)

@router.get("/connectors", response_model=list[ConnectorResponse])
def list_connectors_api():
    from agent_core.connectors.persist import list_connectors

    return list_connectors()

@router.post("/connectors", response_model=ConnectorResponse)
def upsert_connector_api(payload: ConnectorUpsertRequest):
    from agent_core.connectors.persist import upsert_connector

    return _handle_write(upsert_connector, payload.model_dump(exclude_none=True))

@router.get("/connectors/{connector_id}", response_model=ConnectorResponse)
def get_connector_api(connector_id: str):
    from agent_core.connectors.persist import get_connector

    row = get_connector(connector_id)
    if row is None:
        raise HTTPException(status_code=404, detail="connector_not_found")
    return row

@router.post("/connectors/{connector_id}/approve", response_model=ConnectorResponse)
def approve_connector_api(connector_id: str):
    from agent_core.connectors.persist import approve

    return _handle_write(approve, connector_id)

@router.post(
    "/connectors/{connector_id}/test",
    response_model=ConnectorHealthTestResponse,
    response_model_exclude_unset=True,
)
def test_connector_api(connector_id: str):
    from agent_core.connectors.persist import health_test

    return _handle_write(health_test, connector_id)

@router.post("/connectors/{connector_id}/cimd", response_model=ConnectorCimdResponse)
def cimd_connector_api(connector_id: str, payload: ConnectorCimdRequest):
    from agent_core.connectors.persist import cimd_connect

    issuer = payload.issuer.strip()
    return _handle_write(cimd_connect, connector_id, issuer)

@router.get("/vault/refs", response_model=list[VaultRefResponse])
def list_vault_refs_api():
    from agent_core.vault.persist import list_refs

    return list_refs()

@router.post("/vault/refs", response_model=VaultRefResponse)
def put_vault_ref_api(payload: VaultRefPutRequest):
    from agent_core.vault.persist import put_secret

    return _handle_write(
        put_secret,
        name=payload.name,
        purpose=payload.purpose or "other",
        secret=payload.secret,
    )

@router.post("/vault/refs/{ref_id}/rotate", response_model=VaultRefResponse)
def rotate_vault_ref_api(ref_id: str, payload: VaultRefRotateRequest):
    from agent_core.vault.persist import rotate

    return _handle_write(rotate, ref_id, payload.secret)

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
    from llm_gateway import canary as gw_canary
    from llm_gateway.client import PROFILES, base_url, cap_inr

    profiles = {}
    for p in PROFILES:
        env_model = os.getenv(f"LLM_GATEWAY_{p.upper()}_MODEL")
        override = None
        try:
            override = gw_canary.model_for(p)
        except Exception:
            override = None
        profiles[p] = {
            "capInr": cap_inr(p),
            "model": override or env_model,
            "envModel": env_model,
            "canaryModel": override,
        }
    return {
        "enabled": llm_gateway_enabled(),
        "baseUrl": base_url() or None,
        "profiles": profiles,
        "canary": gw_canary.current(),
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

@router.get("/gateway/canary", response_model=GatewayCanaryStateResponse)
def get_gateway_canary():
    from llm_gateway import canary as gw_canary

    return {"current": gw_canary.current(), "history": gw_canary.list_canaries()}

@router.post("/gateway/canary", response_model=GatewayCanaryResponse)
def propose_gateway_canary(payload: GatewayCanaryProposeRequest):
    from llm_gateway import canary as gw_canary

    try:
        return gw_canary.propose(payload.candidateModel, skip_redteam=payload.skipRedteam)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post("/gateway/canary/{canary_id}/promote", response_model=GatewayCanaryResponse)
def promote_gateway_canary(canary_id: str, payload: GatewayCanaryPromoteRequest | None = None):
    from llm_gateway import canary as gw_canary

    try:
        return gw_canary.promote(
            canary_id,
            skip_redteam=bool(payload and payload.skipRedteam),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.get("/providers/models", response_model=list[ProviderModelItem])
def list_provider_models(kind: str | None = Query(default=None, pattern="^(stt|tts|llm)$")):
    """The capability matrix. Unconfigured providers are returned too, marked
    ``configured: false`` — hiding them makes "why can't I pick X?" unanswerable
    from the screen."""
    from agent_core.providers import persist as pv
    from agent_core.providers.registry import (
        RUNTIME_LIVE,
        configured_providers,
        find_model,
        runtime_status,
    )

    live = configured_providers()
    out = []
    for row in pv.list_models(kind):
        # A key makes a provider *configured*; it does not make the model
        # *runnable*. Both are reported because they fail differently: no key is
        # something the operator can fix from the Integrations screen, a missing
        # service class is not.
        spec = find_model(row["provider_id"], row["model_id"])
        runtime, detail = runtime_status(spec) if spec is not None else (RUNTIME_LIVE, "")
        out.append(
            {
                "id": row["id"],
                "providerId": row["provider_id"],
                "providerName": row["provider_name"],
                "kind": row["kind"],
                "modelId": row["model_id"],
                "displayName": row["display_name"],
                "serviceClass": row["service_class"],
                "locales": list(row["locales"] or []),
                "streaming": bool(row["streaming"]),
                "codeSwitch": bool(row["code_switch"]),
                "onPrem": bool(row["on_prem"]),
                "diarization": bool(row["diarization"]),
                "styles": list(row["styles"] or []),
                "costPerUnit": float(row["cost_per_unit"]) if row["cost_per_unit"] is not None else None,
                "costUnit": row["cost_unit"],
                "measuredLatencyP50Ms": row["measured_latency_p50_ms"],
                "measuredLatencyP95Ms": row["measured_latency_p95_ms"],
                "notes": row["notes"] or "",
                "paramsSchema": list(row["params_schema"] or []),
                "enabled": bool(row["enabled"]),
                "configured": row["provider_id"] in live,
                "runtime": runtime,
                "runtimeDetail": detail,
                # Read off the registry rather than the row: it is a measured
                # property of the vendor's engine, not tenant configuration, so
                # it has no business being editable per deployment.
                "sampling": bool(spec.sampling) if spec is not None else False,
            }
        )
    return out

@router.get("/providers/bindings", response_model=list[ProviderBindingItem])
def list_provider_bindings(botId: str | None = Query(default=None)):
    """Bindings for a bot plus the tenant defaults it inherits."""
    from agent_core.providers import persist as pv

    return [
        {
            "id": b["id"],
            "botId": b["bot_id"],
            "slot": b["slot"],
            "locale": b["locale"],
            "providerModelId": b["provider_model_id"],
            "providerId": b["provider_id"],
            "providerName": b["provider_name"],
            "modelId": b["model_id"],
            "displayName": b["display_name"],
            "voiceRef": b["voice_ref"],
            "priority": int(b["priority"]),
            "settings": dict(b["settings"] or {}),
            "enabled": bool(b["enabled"]),
        }
        for b in pv.list_bindings(tenant_id=db.current_tenant(), bot_id=botId)
    ]

@router.post("/providers/bindings", response_model=ProviderBindingItem)
def upsert_provider_binding(payload: ProviderBindingInput):
    from agent_core.providers import persist as pv

    binding_id = pv.upsert_binding(
        tenant_id=db.current_tenant(),
        slot=payload.slot,
        provider_model_id=payload.providerModelId,
        bot_id=payload.botId,
        locale=payload.locale,
        voice_ref=payload.voiceRef,
        priority=payload.priority,
        settings=payload.settings,
        enabled=payload.enabled,
    )
    rows = [b for b in pv.list_bindings(tenant_id=db.current_tenant(), bot_id=payload.botId)
            if b["id"] == binding_id]
    if not rows:
        raise HTTPException(status_code=500, detail="binding_write_failed")
    b = rows[0]
    return {
        "id": b["id"],
        "botId": b["bot_id"],
        "slot": b["slot"],
        "locale": b["locale"],
        "providerModelId": b["provider_model_id"],
        "providerId": b["provider_id"],
        "providerName": b["provider_name"],
        "modelId": b["model_id"],
        "displayName": b["display_name"],
        "voiceRef": b["voice_ref"],
        "priority": int(b["priority"]),
        "settings": dict(b["settings"] or {}),
        "enabled": bool(b["enabled"]),
    }

@router.delete("/providers/bindings/{binding_id}", response_model=OkResponse)
def delete_provider_binding(binding_id: str):
    from agent_core.providers import persist as pv

    if not pv.delete_binding(tenant_id=db.current_tenant(), binding_id=binding_id):
        raise HTTPException(status_code=404, detail="binding_not_found")
    return {"ok": True}

@router.get("/providers/pools", response_model=list[ProviderPoolStatus])
def list_provider_pools():
    """Key-pool health, so free-tier exhaustion is visible before a demo hits it."""
    from agent_core.providers import pool as pool_mod
    from agent_core.providers.registry import SEED

    # Touch every seeded provider so a pool that has never been acquired from
    # still reports (total=0) rather than being absent from the list.
    for spec in SEED:
        pool_mod.get_pool(spec.slug)
    return [
        {
            "provider": s.provider,
            "total": s.total,
            "available": s.available,
            "retired": s.retired,
            "sessionsBound": s.sessions_bound,
            "keys": s.keys,
        }
        for s in pool_mod.all_stats()
    ]

