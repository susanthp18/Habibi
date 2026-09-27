"""PayInt Voice Studio: what PayInt keeps per engine agent.

    GET /voice-studio/guardrails/{workflow_id}   the agent's guardrails (defaults when unset)
    PUT /voice-studio/guardrails/{workflow_id}   replace them (audited)
    GET /voice-studio/checks/scenarios           scripted customer scenarios
    GET/POST /voice-studio/checks                graded rehearsals of an agent (voice_studio_checks)
    GET  /voice-studio/agents/{id}/preflight     release gate, live version, last checks run
    POST /voice-studio/agents/{id}/publish       publish the draft with a changelog note
    POST /voice-studio/agents/{id}/rollback      release an earlier version again
    GET  /voice-studio/releases                  changelog (one agent or all)

The engine owns agents; these are PayInt's rules checked on every bot turn of
the agent's calls and WhatsApp threads (voice_studio.flag_turns).
"""

from __future__ import annotations

from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

import authz
import voice_studio
import voice_studio_routing
from api_support import ROUTER_DEPENDENCIES, Utf8JSONResponse
from routers import agentstudio_gateway as gateway

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)


# Request bodies. Shapes only: the domain rules (an inbound choice needs a
# number, an MCP key's scopes and expiry, ...) stay in the service functions,
# which answer with a readable reason.
class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoutingChoiceRequest(_Body):
    workflowId: int  # noqa: N815
    channel: Literal["inbound", "outbound", "whatsapp"]
    objective: str | None = Field(default=None, max_length=200)
    configId: int | None = None  # noqa: N815
    phoneId: int | None = None  # noqa: N815


class GuardrailsRequest(_Body):
    # Unknown rule keys are dropped by voice_studio.save_guardrails.
    guardrails: dict[str, Any] = Field(default_factory=dict)


class ChecksRunRequest(_Body):
    workflowId: int  # noqa: N815
    scenarioIds: list[str] = Field(default_factory=list, max_length=100)  # noqa: N815


class PublishRequest(_Body):
    note: str | None = Field(default=None, max_length=2000)


class RollbackRequest(_Body):
    versionId: int  # noqa: N815
    note: str | None = Field(default=None, max_length=2000)


class ToolReviewRequest(_Body):
    decision: Literal["approved", "rejected", "revoked"]


class McpKeyCreateRequest(_Body):
    name: str = Field(max_length=100)
    scopes: list[str] = Field(max_length=10)
    expiresInDays: int = 30  # noqa: N815


class PromptLintRequest(_Body):
    prompt: str = Field(default="", max_length=20000)
    workflowId: int | None = None  # noqa: N815
    isOpening: bool = False  # noqa: N815
    greeting: str = Field(default="", max_length=2000)


class SimulateRequest(_Body):
    workflowId: int  # noqa: N815
    persona: str = Field(default="", max_length=4000)
    maxTurns: int | None = Field(default=None, ge=1, le=40)  # noqa: N815


@router.get("/voice-studio/routing")
async def get_routing() -> dict[str, Any]:
    return await run_in_threadpool(voice_studio_routing.list_routing)


@router.post("/voice-studio/routing/check")
async def check_routing(body: RoutingChoiceRequest) -> dict[str, Any]:
    try:
        return await run_in_threadpool(
            voice_studio_routing.check_selection, body.workflowId, body.channel,
            objective=body.objective, config_id=body.configId, phone_id=body.phoneId,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "invalid_request") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc) or "routing_failed") from exc


@router.put("/voice-studio/routing")
async def put_routing(request: Request, body: RoutingChoiceRequest) -> dict[str, Any]:
    actor = gateway._actor(request)
    if authz.enforcement_enabled() and (
        not actor or not authz.has_permission(actor, authz.AGENT_PUBLISH)
        or not authz.has_permission(actor, authz.VOICE_OPERATE)
    ):
        raise HTTPException(status_code=403, detail="forbidden:agent_publish_and_voice_operate")
    try:
        result = await run_in_threadpool(
            voice_studio_routing.assign, body.workflowId, body.channel,
            objective=body.objective, config_id=body.configId, phone_id=body.phoneId,
            actor=actor,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "invalid_request") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc) or "routing_failed") from exc
    return result


@router.get("/voice-studio/guardrails/{workflow_id}")
async def get_guardrails(workflow_id: int) -> dict[str, Any]:
    rules = await run_in_threadpool(voice_studio.guardrails_for, workflow_id)
    return {"workflowId": workflow_id, "guardrails": rules, "defaults": voice_studio.DEFAULT_GUARDRAILS}


@router.put("/voice-studio/guardrails/{workflow_id}")
async def put_guardrails(workflow_id: int, request: Request, body: GuardrailsRequest) -> dict[str, Any]:
    actor = gateway._actor(request)
    rules = await run_in_threadpool(voice_studio.save_guardrails, workflow_id, body.guardrails, actor)
    await run_in_threadpool(gateway._audit, actor, "PUT", f"/guardrails/{workflow_id}", 200)
    return {"workflowId": workflow_id, "guardrails": rules, "defaults": voice_studio.DEFAULT_GUARDRAILS}


@router.get("/voice-studio/checks/scenarios")
async def check_scenarios() -> list[dict[str, Any]]:
    import voice_studio_checks

    rows = await run_in_threadpool(voice_studio_checks.scenarios)
    return [{"id": r["id"], "name": r["name"], "turns": r["turns"]} for r in rows]


@router.get("/voice-studio/checks")
async def list_checks(workflowId: int) -> list[dict[str, Any]]:  # noqa: N803 -- the UI's query name
    import voice_studio_checks

    return await run_in_threadpool(voice_studio_checks.runs, workflowId)


@router.post("/voice-studio/checks")
async def run_checks(request: Request, body: ChecksRunRequest) -> dict[str, Any]:
    import voice_studio_checks

    actor = gateway._actor(request)
    try:
        started = await run_in_threadpool(voice_studio_checks.start, body.workflowId, body.scenarioIds, actor)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "invalid_request") from exc
    await run_in_threadpool(gateway._audit, actor, "POST", f"/checks/{body.workflowId}", 200)
    return started


def _require(request: Request, permission: str) -> str | None:
    actor = gateway._actor(request)
    if authz.enforcement_enabled() and (not actor or not authz.has_permission(actor, permission)):
        raise HTTPException(status_code=403, detail=f"forbidden:{permission}")
    return actor


def _engine_reason(resp: httpx.Response) -> str:
    try:
        detail = resp.json().get("detail")
    except ValueError:
        detail = None
    if isinstance(detail, list):  # FastAPI validation errors
        detail = "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)
    return str(detail or resp.reason_phrase or "engine refused the request")


def _release(fn, *args) -> Any:
    try:
        return fn(*args)
    except PermissionError as exc:  # the release gate refused
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "invalid_request") from exc
    except httpx.HTTPStatusError as exc:
        # The engine refused (e.g. a tool without an approved revision) or failed.
        status = 409 if exc.response.status_code < 500 else 502
        raise HTTPException(status_code=status, detail=f"Voice Studio engine: {_engine_reason(exc.response)}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Voice Studio engine unavailable") from exc


@router.get("/voice-studio/agents/{workflow_id}/preflight")
async def release_preflight(workflow_id: int) -> dict[str, Any]:
    import voice_studio_releases

    return await run_in_threadpool(voice_studio_releases.preflight, workflow_id)


@router.post("/voice-studio/agents/{workflow_id}/publish")
async def release_publish(workflow_id: int, request: Request, body: PublishRequest) -> dict[str, Any]:
    import voice_studio_releases

    actor = _require(request, authz.AGENT_PUBLISH)
    result = await run_in_threadpool(_release, voice_studio_releases.publish, workflow_id, body.note, actor)
    await run_in_threadpool(gateway._audit, actor, "POST", f"/workflow/{workflow_id}/publish", 200)
    return result


@router.post("/voice-studio/agents/{workflow_id}/rollback")
async def release_rollback(workflow_id: int, request: Request, body: RollbackRequest) -> dict[str, Any]:
    import voice_studio_releases

    actor = _require(request, authz.AGENT_PUBLISH)
    result = await run_in_threadpool(
        _release, voice_studio_releases.rollback, workflow_id, body.versionId, body.note, actor
    )
    await run_in_threadpool(gateway._audit, actor, "POST", f"/workflow/{workflow_id}/rollback", 200)
    return result


@router.get("/voice-studio/agents/{workflow_id}/quality")
async def release_quality(workflow_id: int, days: int = 90) -> list[dict[str, Any]]:
    """Per released version: calls, QA, critical fails, violations, agent-spoken PII, containment, mood."""
    import voice_studio_quality

    return await run_in_threadpool(voice_studio_quality.by_version, workflow_id, days=max(1, min(days, 365)))


@router.get("/voice-studio/runs/{run_id}/interaction")
async def run_interaction(run_id: int) -> dict[str, Any]:
    """The PayInt call an engine run was filed as: its recording is played
    through PayInt (redacted unless the viewer may hear the original)."""
    import db
    from sqlalchemy import text

    def lookup() -> dict[str, Any]:
        with db.engine.connect() as conn:
            row = conn.execute(text(
                """
                SELECT s.interaction_id,
                       q.total_score, q.band, q.status AS qa_status,
                       (SELECT count(*) FROM redaction_records r JOIN pii_findings f ON f.redaction_id = r.id
                         WHERE r.interaction_id = s.interaction_id AND f.accepted) AS pii_masked,
                       (SELECT count(*) FROM violations v WHERE v.interaction_id = s.interaction_id) AS violations,
                       (SELECT j.status FROM call_intelligence_jobs j WHERE j.interaction_id = s.interaction_id)
                         AS processing
                  FROM voice_sessions s
                  LEFT JOIN qa_scorecards q ON q.interaction_id = s.interaction_id
                 WHERE s.id = :sid
                """), {"sid": f"VS-studio-{run_id}"}).mappings().first()
        if row is None:
            return {"interactionId": None}
        return {
            "interactionId": row["interaction_id"],
            "qaTotal": float(row["total_score"]) if row["total_score"] is not None else None,
            "qaBand": row["band"], "qaStatus": row["qa_status"],
            "piiMasked": int(row["pii_masked"] or 0), "violations": int(row["violations"] or 0),
            "processing": row["processing"],
        }

    return await run_in_threadpool(lookup)


class ScenarioFromCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interactionId: str = Field(min_length=1)  # noqa: N815


@router.post("/voice-studio/checks/scenarios/from-call")
async def scenario_from_call(request: Request, body: ScenarioFromCallRequest) -> dict[str, Any]:
    """Turn a real call (a QA fail, a violation) into a scripted check."""
    import voice_studio_checks

    actor = _require(request, authz.EVAL_RUN)
    try:
        return await run_in_threadpool(voice_studio_checks.scenario_from_call, body.interactionId, actor)
    except KeyError:
        raise HTTPException(status_code=404, detail="interaction_not_found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/voice-studio/releases")
async def release_history(workflowId: int | None = None, limit: int = 50) -> list[dict[str, Any]]:  # noqa: N803
    import voice_studio_releases

    return await run_in_threadpool(voice_studio_releases.history, workflowId, limit)


@router.post("/voice-studio/releases/reconcile")
async def reconcile_releases(request: Request, workflowId: int | None = None) -> list[dict[str, Any]]:  # noqa: N803
    import voice_studio_releases

    _require(request, authz.AGENT_PUBLISH)
    return await run_in_threadpool(voice_studio_releases.reconcile_pending, workflowId)


@router.post("/voice-studio/tools/{tool_uuid}/revisions/{revision}/review")
async def review_tool(tool_uuid: str, revision: int, request: Request,
                      body: ToolReviewRequest) -> dict[str, Any]:
    import voice_studio_tools

    actor = _require(request, authz.TOOL_APPROVE)
    if not actor:
        raise HTTPException(status_code=401, detail="A named reviewer is required")
    try:
        return await run_in_threadpool(
            voice_studio_tools.review, tool_uuid, revision, body.decision, actor,
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=409, detail=f"Voice Studio engine: {_engine_reason(exc.response)}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Voice Studio engine unavailable") from exc


@router.get("/voice-studio/mcp-keys")
async def list_studio_mcp_keys(request: Request) -> list[dict[str, Any]]:
    import voice_studio_mcp_keys

    actor = _require(request, authz.AGENT_EDIT)
    return await run_in_threadpool(voice_studio_mcp_keys.list_keys, actor)


@router.post("/voice-studio/mcp-keys")
async def create_studio_mcp_key(request: Request, body: McpKeyCreateRequest) -> dict[str, Any]:
    import voice_studio_mcp_keys

    actor = _require(request, authz.AGENT_EDIT)
    try:
        return await run_in_threadpool(
            voice_studio_mcp_keys.mint, actor, name=body.name, scopes=body.scopes, days=body.expiresInDays,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/voice-studio/mcp-keys/{key_id}/rotate")
async def rotate_studio_mcp_key(key_id: str, request: Request) -> dict[str, Any]:
    import voice_studio_mcp_keys

    actor = _require(request, authz.AGENT_EDIT)
    try:
        return await run_in_threadpool(voice_studio_mcp_keys.rotate, actor, key_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc


@router.delete("/voice-studio/mcp-keys/{key_id}")
async def revoke_studio_mcp_key(key_id: str, request: Request) -> dict[str, str]:
    import voice_studio_mcp_keys

    actor = _require(request, authz.AGENT_EDIT)
    try:
        await run_in_threadpool(voice_studio_mcp_keys.revoke, actor, key_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    return {"status": "revoked"}


@router.post("/voice-studio/prompt/lint")
async def prompt_lint(body: PromptLintRequest) -> dict[str, Any]:
    """Lint a node prompt as the engine renders it, with its per-turn input cost."""
    import voice_studio_prompt_lint

    rules = await run_in_threadpool(voice_studio.guardrails_for, body.workflowId) if body.workflowId else {}
    return await run_in_threadpool(
        lambda: voice_studio_prompt_lint.lint_with_estimate(
            body.prompt, rules, is_opening=body.isOpening, spoken_first=body.greeting,
        )
    )


@router.post("/voice-studio/checks/simulate")
async def simulate_customer(request: Request, body: SimulateRequest) -> dict[str, Any]:
    """An AI customer, described in plain words, talks to the agent; graded like a check."""
    import voice_studio_checks

    actor = _require(request, authz.EVAL_RUN)
    try:
        started = await run_in_threadpool(
            voice_studio_checks.start_simulation, body.workflowId, body.persona,
            actor, body.maxTurns or voice_studio_checks.SIMULATION_MAX_TURNS,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "invalid_request") from exc
    await run_in_threadpool(gateway._audit, actor, "POST", f"/checks/{body.workflowId}/simulate", 200)
    return started
