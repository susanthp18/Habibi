"""Agent Studio: cards, prompt versions, flow, deployments, roles.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import authz
import db
import flow_graph

from fastapi import APIRouter
from agent_core.cards.compile import CompileError, CompileReport
from fastapi import (
    File,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from schemas import (
    AgentCardCloneRequest,
    AgentCardCompileRequest,
    AgentCardPatchRequest,
    AgentStudioArchiveResponse,
    AgentStudioCardResponse,
    AgentStudioChangeLogResponse,
    AgentStudioGraphResponse,
    AgentStudioOkResponse,
    AgentStudioScriptNameResponse,
    AgentStudioScriptRunResponse,
    AgentStudioSkillDeleteResponse,
    AgentStudioSkillResponse,
    AgentStudioSkillSummaryResponse,
    AgentStudioTemplateResponse,
    BotDeploymentResponse,
    ConnectorAttachRequest,
    DeploymentExperimentResponse,
    DeploymentExperimentRollbackResponse,
    EffectiveContractResponse,
    EntryBindingResponse,
    EntryBindingUpsert,
    FlowGraph,
    FlowToolResponse,
    FlowValidation,
    PersonaPresetResponse,
    PolicyEngineResponse,
    PromptLintRequest,
    PromptLintResponse,
    PromptTokenEstimateRequest,
    PromptTokenEstimateResponse,
    PromptVersionCreateRequest,
    PromptVersionPatchRequest,
    PromptVersionPublishRequest,
    PromptVersionResponse,
    ExperimentRollbackRequest,
    RolePermissionsPatchRequest,
    RoleResponse,
    RolesCatalogResponse,
    SkillAttachRequest,
    SkillCloneRequest,
    SkillCreateRequest,
    SkillPatchRequest,
    SkillRevertRequest,
    SkillScriptRunRequest,
)
from sqlalchemy.exc import IntegrityError
from typing import Any

from api_support import _handle_write, _read_upload_capped, Utf8JSONResponse, ROUTER_DEPENDENCIES

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.get("/prompt-versions", response_model=list[PromptVersionResponse])
def list_prompt_versions(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
    botId: str | None = Query(default=None),
):
    """Prompt Studio version history (newest first)."""
    return db.list_prompt_versions(limit=limit, offset=offset, bot_id=botId)

@router.get("/prompt-versions/published", response_model=PromptVersionResponse)
def get_published_prompt_version(botId: str | None = Query(default=None)):
    """Editor live badge — published row for this bot (Collections by default)."""
    row = db.get_published_prompt_version(botId)
    if row is None:
        raise HTTPException(status_code=404, detail="published_prompt_not_found")
    return row

@router.get("/prompt-versions/{version_id}", response_model=PromptVersionResponse)
def get_prompt_version(version_id: str):
    row = db.get_prompt_version(version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="prompt_version_not_found")
    return row

@router.get("/flow/tools", response_model=list[FlowToolResponse])
def list_flow_tools():
    """Tools an authored flow node may call.

    Introspected from the live registry rather than listed here, so the editor
    cannot drift from what the runtime will actually accept.
    """
    return flow_graph.tool_catalog()

@router.get("/flow/built-in", response_model=FlowGraph)
def get_built_in_flow():
    """The built-in collections conversation, as an authored graph.

    Lets the Flow tab start from the shipped conversation instead of a blank
    canvas. Read from ``agent_core/cards/graphs/collections.json`` -- the one
    definition, which the first-party card publishes like any other graph.
    Loading it only fills the editor; nothing changes until the draft is
    published.
    """
    from voice.flow_export import built_in_collections_graph

    return built_in_collections_graph()

@router.get("/flow/transitions", response_model=dict[str, list[str]])
def get_flow_transitions():
    """tool key -> node keys that tool moves the conversation to.

    The built-in tools transition by node key, so a graph that uses reserved
    keys has real transitions with no authored edges — twelve nodes and zero
    lines on the canvas. The editor draws these as ghost edges so what leads
    where is visible without inventing edges the runtime would ignore.
    """
    return flow_graph.implicit_transitions()

@router.get("/flow/variables", response_model=list[str])
def flow_variables():
    """The live-call variables a graph may interpolate or branch on.

    `SESSION_VARIABLES` called itself "the contract the Flow editor
    advertises" while the editor advertised nothing -- authors typed variable
    names from memory into the condition editor.
    """
    from voice.flows_dynamic import SESSION_VARIABLES

    return list(SESSION_VARIABLES)

@router.get("/flow/reserved-keys", response_model=dict[str, str])
def list_flow_reserved_keys():
    """Node keys the built-in tools transition to by name.

    A graph is free to ignore them; using one wires up that built-in hop. The
    editor surfaces these so the choice is visible rather than a trap.

    Also the keys that carry a built-in *directive* (`voice/node_contracts.
    NODE_DIRECTIVES`): the runtime appends a developer instruction to those
    nodes whatever the author wrote, and `confirm_identity` -- reached by being
    dialled, not by a tool -- was the one key with runtime behaviour and no
    hint. Read pipecat-free: node_contracts imports nothing.
    """
    from voice.node_contracts import NODE_DIRECTIVES

    out = dict(flow_graph.RESERVED_NODE_KEYS)
    for key, directive in NODE_DIRECTIVES.items():
        note = f"carries a built-in directive on this step: {directive[:80].rstrip()}…"
        out[key] = f"{out[key]}; {note}" if key in out else note
    return out

@router.get("/agent-studio/cards", response_model=list[AgentStudioCardResponse])
def list_agent_studio_cards(includeArchived: bool = Query(default=False)):
    return db.list_agent_studio_cards(include_archived=includeArchived)

@router.get("/agent-studio/policy-engines", response_model=list[PolicyEngineResponse])
def list_agent_studio_policy_engines():
    """The engines a card cannot unbind, and the mode each actually runs in."""
    return db.policy_engines()

@router.get("/agent-studio/entry-bindings", response_model=list[EntryBindingResponse])
def list_agent_studio_entry_bindings():
    """Which card answers each channel and dialled number. Authored here, read
    by `resolve_entry` on every inbound contact once DOOR_ENABLED is on."""
    return db.list_entry_bindings()

@router.put("/agent-studio/entry-bindings", response_model=EntryBindingResponse)
def put_agent_studio_entry_binding(payload: EntryBindingUpsert):
    return _handle_write(db.set_entry_binding, payload.model_dump())

@router.delete("/agent-studio/entry-bindings/{binding_id}", response_model=EntryBindingResponse)
def delete_agent_studio_entry_binding(binding_id: str):
    return _handle_write(db.remove_entry_binding, binding_id)

@router.get("/agent-studio/templates", response_model=list[AgentStudioTemplateResponse])
def list_agent_studio_templates():
    from agent_core.cards.templates import templates

    return templates()

@router.post("/agent-studio/cards/clone", response_model=AgentStudioCardResponse)
def clone_agent_studio_card(payload: AgentCardCloneRequest):
    from agent_core.cards.clone import clone_card

    return _handle_write(
        clone_card,
        template_id=payload.templateId,
        source_bot_id=payload.sourceBotId,
        name=payload.name,
    )

@router.get("/agent-studio/cards/{bot_id}", response_model=AgentStudioCardResponse)
def get_agent_studio_card(bot_id: str):
    row = db.get_agent_studio_card(bot_id)
    if row is None:
        raise HTTPException(status_code=404, detail="agent_card_not_found")
    return row

@router.patch("/agent-studio/cards/{bot_id}", response_model=PromptVersionResponse)
def patch_agent_studio_card(bot_id: str, payload: AgentCardPatchRequest):
    """Patch the latest draft for this bot, creating one from published if needed."""
    sent = payload.model_dump(exclude_unset=True)
    card = payload.agentCard
    versions = db.list_prompt_versions(bot_id=bot_id, limit=20)
    draft = next((v for v in versions if v["status"] == "draft"), None)
    if draft is None:
        published = db.get_published_prompt_version(bot_id)
        if published is None:
            raise HTTPException(status_code=404, detail="agent_card_not_found")
        draft = db.restore_prompt_version_as_draft(published["id"])
    body: dict[str, Any] = {}
    if isinstance(card, dict):
        body["agentCard"] = card
    if "flow" in sent:
        body["flow"] = sent["flow"]
    if not body:
        return draft
    return _handle_write(db.patch_prompt_version, draft["id"], body)

@router.post("/agent-studio/cards/{bot_id}/archive", response_model=AgentStudioArchiveResponse)
def archive_agent_studio_card(bot_id: str):
    """Retire a tenant card. Refuses first-party and the runtime entry bot.

    An active production deployment is retired here, not refused — this text
    used to say otherwise, and it was the description OpenAPI served long after
    the guard was removed for making the feature unreachable (publish always
    leaves an active deployment).
    """
    return _handle_write(db.archive_agent_studio_card, bot_id)

@router.post("/agent-studio/cards/{bot_id}/restore", response_model=AgentStudioArchiveResponse)
def restore_agent_studio_card(bot_id: str):
    """Put a retired card back on the roster. Does not redeploy it."""
    return _handle_write(db.restore_agent_studio_card, bot_id)

@router.get(
    "/agent-studio/change-log",
    response_model=AgentStudioChangeLogResponse,
    response_model_exclude_unset=True,
)
def get_agent_change_log(
    botId: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
):
    """Who changed what an agent says, when, and what the compiler said then.

    Hash-chained: the response carries a `chain` verdict, so a rewritten or
    deleted historical entry is visible rather than merely absent.
    """
    return db.agent_change_log(botId, limit=limit)

@router.post("/agent-studio/cards/{bot_id}/compile", response_model=CompileReport)
def compile_agent_studio_card(bot_id: str, payload: AgentCardCompileRequest | None = None):
    body = payload or AgentCardCompileRequest()
    return db.compile_agent_studio_card(
        bot_id,
        card_raw=body.agentCard or None,
        flow=body.flow,
        # Preview what publish will ship, not what the card was authored with.
        traffic_pct=int(body.trafficPct) if body.trafficPct is not None else None,
        auto_rollback=body.autoRollback,
        # G15 reads the mouth columns, which the editor holds unsaved between
        # autosaves. Omitted, the preview gates the last saved voice rather than
        # the one the Publish button is about to ship.
        voice=body.voice,
        persona=body.persona,
    )

@router.get(
    "/agent-studio/cards/{bot_id}/effective-contract",
    response_model=EffectiveContractResponse,
)
def get_agent_studio_effective_contract(bot_id: str):
    """Read-only compiled artefact: published if persisted, else a draft preview."""
    try:
        return db.get_effective_contract(bot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/agent-studio/cards/{bot_id}/publish", response_model=PromptVersionResponse)
def publish_agent_studio_card(bot_id: str, payload: PromptVersionPublishRequest):
    """Publish one of this bot's drafts — the one the caller names, by preference.

    This used to take ``next(v for v in newest_20 if v["status"] == "draft")``:
    whichever draft happened to sort first inside an arbitrary window, with no
    way for the caller to say which draft it meant. A bot with two open drafts
    therefore published a version nobody selected, and the studio — which tracks
    the exact draft it is editing — could not express its choice through this
    endpoint at all.

    So: publish what was asked for; publish the only draft when there is exactly
    one; and refuse rather than guess when there is more than one and no
    instruction. Guessing here promotes text to production.
    """
    versions = db.list_prompt_versions(bot_id=bot_id)
    drafts = [v for v in versions if v["status"] == "draft"]
    if payload.versionId:
        chosen = next((v for v in drafts if v["id"] == payload.versionId), None)
        if chosen is None:
            # Distinguish "not a draft of this bot" from "not a draft", since the
            # caller can fix only one of those.
            exists = any(v["id"] == payload.versionId for v in versions)
            raise HTTPException(
                status_code=409 if exists else 404,
                detail="prompt_version_not_draft" if exists else "prompt_version_not_found",
            )
        return publish_prompt_version(chosen["id"], payload)
    if not drafts:
        raise HTTPException(status_code=409, detail="no_draft_to_publish")
    if len(drafts) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "ambiguous_draft_to_publish: this bot has "
                f"{len(drafts)} open drafts ({', '.join(v['id'] for v in drafts)}). "
                "Name one with versionId."
            ),
        )
    return publish_prompt_version(drafts[0]["id"], payload)

@router.post("/agent-studio/cards/{bot_id}/connectors", response_model=PromptVersionResponse)
def attach_agent_studio_connector(bot_id: str, payload: ConnectorAttachRequest):
    from agent_core.cards.clone import attach_connector_to_card

    connector_id = payload.connectorId.strip()
    if not connector_id:
        raise HTTPException(status_code=422, detail="connector_id_required")
    return _handle_write(
        attach_connector_to_card,
        bot_id,
        connector_id=connector_id,
        allow_prefixes=payload.allowPrefixes or None,
    )

@router.get("/agent-studio/cards/{bot_id}/graph", response_model=AgentStudioGraphResponse)
def get_agent_studio_graph(bot_id: str):
    card = db.get_agent_studio_card(bot_id)
    if card is None:
        raise HTTPException(status_code=404, detail="agent_card_not_found")
    raw = card.get("agentCard") or {}
    handoffs = raw.get("handoffs") if isinstance(raw, dict) else []
    return {
        "botId": bot_id,
        # Reachability rides along because list_agent_studio_cards already
        # computed it: the allowlist editor can then say whether a target takes
        # traffic today, and whether this card's own allowlist routes anything.
        "nodes": [
            {
                "id": c["botId"],
                "label": c["name"],
                "reachability": c["reachability"],
                "deploymentStatus": c["deploymentStatus"],
            }
            for c in db.list_agent_studio_cards()
        ],
        "edges": [
            {"from": bot_id, "to": h.get("to_bot_id")}
            for h in (handoffs or [])
            if isinstance(h, dict)
        ],
    }

@router.get("/agent-studio/skills", response_model=list[AgentStudioSkillSummaryResponse])
def list_agent_studio_skills():
    from agent_core.skills.persist import list_skills

    return list_skills()

@router.get("/agent-studio/skills/scripts", response_model=list[AgentStudioScriptNameResponse])
def list_agent_studio_scripts():
    """Allowlisted code-mode scripts. The editor's picker hardcoded this list, so
    a new script was invisible and a removed one was still offered.

    Declared above /skills/{skill_id} — FastAPI matches in definition order, and
    the parameterised route would otherwise swallow "scripts".
    """
    from agent_core.skills.scripts import SCRIPT_NAMES

    return [{"name": n} for n in SCRIPT_NAMES]

@router.get(
    "/agent-studio/skills/{skill_id}",
    response_model=AgentStudioSkillResponse,
    response_model_exclude_unset=True,
)
def get_agent_studio_skill(skill_id: str):
    from agent_core.skills.persist import get_skill

    row = get_skill(skill_id)
    if row is None:
        raise HTTPException(status_code=404, detail="skill_not_found")
    return row

@router.post(
    "/agent-studio/skills",
    response_model=AgentStudioSkillResponse,
    response_model_exclude_unset=True,
)
def create_agent_studio_skill(payload: SkillCreateRequest):
    from agent_core.skills.persist import create_draft_skill

    return _handle_write(create_draft_skill, payload.model_dump())

@router.patch(
    "/agent-studio/skills/{skill_id}",
    response_model=AgentStudioSkillResponse,
    response_model_exclude_unset=True,
)
def patch_agent_studio_skill(skill_id: str, payload: SkillPatchRequest):
    from agent_core.skills.persist import patch_skill

    # exclude_unset: patch_skill treats a present key as an intentional write.
    return _handle_write(patch_skill, skill_id, payload.model_dump(exclude_unset=True))

@router.delete("/agent-studio/skills/{skill_id}", response_model=AgentStudioSkillDeleteResponse)
def delete_agent_studio_skill(skill_id: str):
    """Delete an unsigned tenant/gardener skill that no card is using.

    First-party, signed, or attached skills are refused (409) rather than
    orphaning a published card's pinned pack.
    """
    from agent_core.skills.persist import delete_skill

    return _handle_write(delete_skill, skill_id)

@router.post(
    "/agent-studio/skills/{skill_id}/sign",
    response_model=AgentStudioSkillResponse,
    response_model_exclude_unset=True,
)
def sign_agent_studio_skill(skill_id: str):
    from agent_core.skills.persist import sign_skill

    return _handle_write(sign_skill, skill_id)

@router.post(
    "/agent-studio/skills/{skill_id}/revert",
    response_model=AgentStudioSkillResponse,
    response_model_exclude_unset=True,
)
def revert_agent_studio_skill(skill_id: str, payload: SkillRevertRequest | None = None):
    from agent_core.skills.persist import revert_skill

    return _handle_write(revert_skill, skill_id, payload.versionId if payload else None)

@router.post(
    "/agent-studio/skills/{skill_id}/clone",
    response_model=AgentStudioSkillResponse,
    response_model_exclude_unset=True,
)
def clone_agent_studio_skill(skill_id: str, payload: SkillCloneRequest | None = None):
    from agent_core.skills.persist import clone_skill

    return _handle_write(clone_skill, skill_id, payload.slug if payload else None)

@router.post("/agent-studio/skills/{skill_id}/attach", response_model=AgentStudioOkResponse)
def attach_agent_studio_skill(skill_id: str, payload: SkillAttachRequest):
    from agent_core.skills.persist import attach_skill_to_prompt

    version_id = payload.promptVersionId.strip()
    if not version_id:
        raise HTTPException(status_code=422, detail="prompt_version_id_required")
    _handle_write(attach_skill_to_prompt, version_id, skill_id)
    return {"ok": True}

@router.post("/agent-studio/skills/{skill_id}/detach", response_model=AgentStudioOkResponse)
def detach_agent_studio_skill(skill_id: str, payload: SkillAttachRequest):
    from agent_core.skills.persist import detach_skill_from_prompt

    version_id = payload.promptVersionId.strip()
    if not version_id:
        raise HTTPException(status_code=422, detail="prompt_version_id_required")
    _handle_write(detach_skill_from_prompt, version_id, skill_id)
    return {"ok": True}

@router.get("/agent-studio/skills/{skill_id}/export", response_class=StreamingResponse)
def export_agent_studio_skill(skill_id: str):
    import io
    import zipfile

    from agent_core.skills.persist import get_skill

    row = get_skill(skill_id)
    if row is None:
        raise HTTPException(status_code=404, detail="skill_not_found")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", row.get("markdown") or "")
        refs = (row.get("pack") or {}).get("references") or {}
        for name, body in refs.items():
            zf.writestr(f"references/{name}", body)
    buf.seek(0)
    filename = f"{row.get('slug') or skill_id}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@router.post(
    "/agent-studio/skills/import",
    response_model=AgentStudioSkillResponse,
    response_model_exclude_unset=True,
)
async def import_agent_studio_skill(file: UploadFile = File(...)):
    import io
    import zipfile

    from agent_core.skills.pack import parse_skill_md
    from agent_core.skills.persist import upsert_skill_from_pack

    raw = await _read_upload_capped(file, max_bytes=2_000_000)
    md = ""
    refs: dict[str, str] = {}
    if (file.filename or "").endswith(".md"):
        md = raw.decode("utf-8")
    else:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if name.endswith("SKILL.md"):
                    md = zf.read(name).decode("utf-8")
                elif "/references/" in name or name.startswith("references/"):
                    refs[name.split("references/", 1)[-1]] = zf.read(name).decode("utf-8")
    if not md:
        raise HTTPException(status_code=422, detail="skill_md_missing")
    pack = parse_skill_md(md)
    pack.references = refs
    pack.origin = "tenant"
    pack.signed = False
    return upsert_skill_from_pack(pack, origin="tenant", signed=False)

@router.post(
    "/agent-studio/skills/run-script",
    response_model=AgentStudioScriptRunResponse,
    response_model_exclude_unset=True,
)
def run_agent_studio_script(payload: SkillScriptRunRequest):
    """`payload` is typed as an object: posting `[1, 2]` is a 422, not a run
    against no arguments that returns a verdict reading as computed."""
    from agent_core.skills.scripts import run_script

    return run_script(payload.name.strip(), payload.payload)

@router.get("/roles", response_model=RolesCatalogResponse)
def list_roles_catalog():
    """Roles page. Grants are the resolved set the enforcer will honour."""
    catalog = [
        {"id": pid, "module": module, "action": action, "description": description}
        for pid, module, action, description in authz.PERMISSION_CATALOG
    ]
    rows = db.list_role_grant_rows()
    explicit_by_role: dict[str, list[str]] = {}
    role_meta: dict[str, tuple[str, bool]] = {}
    role_order: list[str] = []
    for row in rows:
        rid = row["role_id"]
        if rid not in role_meta:
            role_meta[rid] = (row["role_name"], row["configured_at"] is not None)
            role_order.append(rid)
            explicit_by_role[rid] = []
        if row["permission_id"]:
            explicit_by_role[rid].append(row["permission_id"])
    roles_out: list[dict[str, Any]] = []
    grants: list[dict[str, Any]] = []
    publishers: set[str] = set()
    for rid in role_order:
        name, configured = role_meta[rid]
        resolved = sorted(
            authz.resolve_role_grants(name, explicit_by_role[rid], configured=configured)
        )
        roles_out.append({"id": rid, "name": name, "permissionIds": resolved})
        for pid in resolved:
            grants.append({"role_id": rid, "role": name, "permission_id": pid})
            if pid == authz.AGENT_PUBLISH:
                publishers.add(name)
    return {
        "permissions": catalog,
        "agentPublishRoles": sorted(publishers),
        "grants": grants,
        "roles": roles_out,
    }

@router.patch("/roles/{role_id}/permissions", response_model=RoleResponse)
def patch_role_permissions(role_id: str, payload: RolePermissionsPatchRequest):
    return _handle_write(db.replace_role_permissions, role_id, list(payload.permissionIds))

@router.post("/flow/validate", response_model=FlowValidation)
def validate_flow(graph: FlowGraph):
    """Structural check. Errors block publish; warnings are advisory.

    The editor calls this as you draw, so a graph is never published with a
    dangling edge or two nodes sharing a transition key.
    """
    return flow_graph.validate_graph(
        graph, known_tools=[t["key"] for t in flow_graph.tool_catalog()]
    )

@router.get("/persona-presets", response_model=list[PersonaPresetResponse])
def list_persona_presets():
    return db.list_persona_presets()

@router.get("/bot-deployments", response_model=list[BotDeploymentResponse])
def list_bot_deployments(
    environment: str | None = Query(default=None),
    status: str | None = Query(default=None),
    botId: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """Runtime deployments — authoritative for what runs (Sandbox / live)."""
    return db.list_bot_deployments(
        environment=environment, status=status, bot_id=botId, limit=limit, offset=offset
    )

@router.get("/bot-deployments/active", response_model=BotDeploymentResponse)
def get_active_bot_deployment(
    environment: str = Query(default="production"),
    botId: str | None = Query(default=None),
):
    """Thin wrapper over get_active_deployment — 404 if none active."""
    row = db.get_active_deployment(bot_id=botId, environment=environment)
    if row is None:
        raise HTTPException(status_code=404, detail="active_deployment_not_found")
    return row

@router.get("/bot-deployments/experiments", response_model=list[DeploymentExperimentResponse])
def list_deployment_experiments(botId: str | None = Query(default=None)):
    from agent_core.canary import list_experiments

    return list_experiments(bot_id=botId)

@router.post(
    "/bot-deployments/experiments/{experiment_id}/rollback",
    response_model=DeploymentExperimentRollbackResponse,
    response_model_exclude_unset=True,
)
def rollback_deployment_experiment(experiment_id: str, payload: ExperimentRollbackRequest | None = None):
    from agent_core.canary import rollback_experiment

    reason = (payload.reason if payload else "") or "manual"
    try:
        return rollback_experiment(experiment_id, reason=reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

def _require_agent_edit_for_card(body: dict[str, Any]) -> None:
    """The dedicated Studio card route is the writer of ``agentCard``.

    Generic prompt-version create/patch stay BOT_WRITE for prompt/persona.
    Carrying a card through those bodies is an AGENT_EDIT act.
    """
    if "agentCard" in body or "agent_card" in body:
        uid = db._actor_user_id()
        if not uid or not authz.has_permission(uid, authz.AGENT_EDIT):
            raise HTTPException(status_code=403, detail="agent_edit_required")

@router.post("/prompt-versions", response_model=PromptVersionResponse)
def create_prompt_version(payload: PromptVersionCreateRequest):
    """Create a draft — jsonb validated by nested Pydantic models."""
    _require_agent_edit_for_card(payload.model_dump(exclude_unset=True))
    body = payload.model_dump()
    return _handle_write(db.create_prompt_version, body)

@router.patch("/prompt-versions/{version_id}", response_model=PromptVersionResponse)
def patch_prompt_version(version_id: str, payload: PromptVersionPatchRequest):
    """Update draft only — 409 if the version is published/archived.

    ``agentCard`` is the compile-time contract, not a prompt slider. Mutating it
    through the generic BOT_WRITE patch is how a role that cannot open Studio
    could still rewrite handoffs and tools. AGENT_EDIT is required when the
    body carries a card.
    """
    body = payload.model_dump(exclude_unset=True)
    _require_agent_edit_for_card(body)
    return _handle_write(db.patch_prompt_version, version_id, body)

@router.post("/prompt-versions/{version_id}/publish", response_model=PromptVersionResponse)
def publish_prompt_version(version_id: str, payload: PromptVersionPublishRequest):
    """Publish draft + swap active prod deployment atomically.

    Optional kbSnapshotId from Sandbox Promote pins the deployment bundle.
    Tuning comes from the authored prompt version, never browser rehearsal state.
    Concurrent publish that loses the unique published index returns 409.
    An authored conversation graph with validation errors returns 422
    ``flow_invalid`` — drafts stay savable; publish is the compiler.
    """
    try:
        return db.publish_prompt_version(
            version_id,
            payload.summary,
            kb_snapshot_id=payload.kbSnapshotId,
            # Tuning is authored on the prompt version. Rehearsal controls are
            # ephemeral and cannot overwrite it during promotion.
            tuning=None,
            traffic_pct=payload.trafficPct,
            shadow=payload.shadow,
            auto_rollback=payload.autoRollback,
        )
    except flow_graph.FlowInvalidError as exc:
        raise HTTPException(status_code=422, detail=exc.http_detail()) from exc
    except CompileError as exc:
        raise HTTPException(status_code=exc.report.http_status(), detail=exc.http_detail()) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        logger.warning("write rejected by a database constraint: %s", exc.orig)
        raise HTTPException(status_code=409, detail="constraint_violation") from exc

@router.post("/prompt-versions/lint", response_model=PromptLintResponse)
def lint_prompt_version(payload: PromptLintRequest):
    """Deterministic prompt lint (unknown vars, disclosure, prohibited words).

    Optional includeLlm=true runs an Azure checklist pass — never auto-edits.
    """
    import prompt_lint

    findings = prompt_lint.lint_prompt(
        payload.prompt,
        payload.guardrails.model_dump(),
        include_llm=payload.includeLlm,
    )
    return {"findings": findings}

@router.post("/prompt-versions/estimate-tokens", response_model=PromptTokenEstimateResponse)
def estimate_prompt_tokens(payload: PromptTokenEstimateRequest):
    """Tiktoken (cl100k_base) prompt token count + input-$ estimate for Studio.

    Returns two figures. ``tokens`` is the authored text, which is what the
    editor shows a character count for. ``assembledTokens`` is the whole system
    message as the runtime builds it — authored prompt, generated guardrail
    rules, persona directions, tenant-local time and (on voice) the naturalness
    overlay — and is only present when the caller supplies guardrails, since
    without them the assembly would be a guess wearing the clothes of a
    measurement.

    The second figure is the one that bills. It is re-sent on every LLM call,
    2-3x per turn through Flows, so a card whose authored prompt is 100 tokens
    can be paying for 800.

    Cost is the meter's chat-input price (``PRICE_CHAT_INPUT_USD_PER_1M``, the
    one book billing reads) — prompt-input only, not a full turn (completion /
    RAG context excluded).
    """
    from kb_chunking import count_tokens
    from usage_meter import chat_input_usd_per_1m

    text = payload.prompt or ""
    if len(text) > 200_000:
        raise HTTPException(status_code=400, detail="prompt_too_large")
    tokens = count_tokens(text)
    usd_per_1m = chat_input_usd_per_1m()

    def _cost(count: int) -> float:
        return round(count * usd_per_1m / 1_000_000.0, 6)

    assembled_tokens: int | None = None
    if payload.guardrails is not None:
        # Assemble with the real builders rather than re-implementing the
        # concatenation here or in the browser. The generated sections are
        # several times the size of the authored text and they change whenever
        # a guardrail is toggled or the naturalness overlay is edited; a second
        # copy of that arithmetic would be wrong within a week.
        from agent_core.prompt import build_system_prompt, default_context
        from prompt_render import render_system_prompt, strip_unrendered_crm_tokens

        persona = payload.persona.model_dump() if payload.persona is not None else {}
        guardrails = payload.guardrails.model_dump()
        ctx = default_context({"language": persona["language"]} if persona else None)
        # Same two steps the runtimes take, so the count reflects the CRM lines
        # that get deleted rather than the ones that were typed.
        rendered = strip_unrendered_crm_tokens(render_system_prompt(text, ctx))
        if payload.channel == "voice":
            from voice.natural import build_voice_system_prompt

            assembled = build_voice_system_prompt(rendered, guardrails, persona=persona or None)
        else:
            assembled = build_system_prompt(
                rendered_prompt=rendered,
                persona=persona,
                guardrails=guardrails,
                context_blocks=[],
                channel="whatsapp",
            )
        assembled_tokens = count_tokens(assembled)

    return {
        "tokens": tokens,
        "encoding": "cl100k_base",
        "usdPer1M": usd_per_1m,
        "costUsd": _cost(tokens),
        "source": "tiktoken",
        "assembledTokens": assembled_tokens,
        "assembledCostUsd": None if assembled_tokens is None else _cost(assembled_tokens),
    }

@router.post("/prompt-versions/{version_id}/restore-as-draft", response_model=PromptVersionResponse)
def restore_prompt_version_as_draft(version_id: str):
    """Copy archived/published → new draft; never overwrites live."""
    return _handle_write(db.restore_prompt_version_as_draft, version_id)

@router.post("/prompt-versions/{version_id}/discard", response_model=PromptVersionResponse)
def discard_prompt_version(version_id: str):
    """Archive a draft — editor discard path. 409 if not a draft."""
    return _handle_write(db.discard_prompt_version, version_id)

@router.post("/bot-deployments/{deployment_id}/rollback", response_model=BotDeploymentResponse)
def rollback_bot_deployment(deployment_id: str):
    """Activate prior deployment and re-publish its prompt version (invariant)."""
    try:
        return db.rollback_bot_deployment(deployment_id)
    except CompileError as exc:
        raise HTTPException(status_code=exc.report.http_status(), detail=exc.http_detail()) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0] if exc.args else str(exc))) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        logger.warning("write rejected by a database constraint: %s", exc.orig)
        raise HTTPException(status_code=409, detail="constraint_violation") from exc

