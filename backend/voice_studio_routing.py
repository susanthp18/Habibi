"""Published Voice Studio agent validation and explicit PayInt channel routing.

The engine owns workflow definitions and tools. PayInt validates the approved
business-tool seam before a definition can be routed to real customers.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text

import voice_studio
from env_utils import env_str

APPROVED_ARGUMENTS: dict[str, dict[str, str]] = {
    "verify_identity": {"method": "string", "value": "string"},
    "account_position": {},
    "promise_to_pay": {"amount": "number", "date": "string"},
    "request_callback": {"when": "string"},
    "flag_dispute": {"type": "string", "summary": "string"},
    "transfer_to_human": {},
}
REQUIRED_PRESETS = {
    "workflow_run_id": "number", "agent_id": "string", "direction": "string",
    "customer_id": "string", "account_id": "string", "channel": "string",
    "interaction_id": "string",
}


def _audit_assignment(conn: Any, actor: str | None, channel: str, target: str,
                      old_id: int | None, new_id: int) -> None:
    from agent_core import change_log
    import db

    change_log.record_agentstudio_change(
        conn, tenant_id=db.current_tenant(), actor_user_id=actor,
        entry_id=f"as-{uuid.uuid4().hex}", method="PUT",
        path=f"/routing/{channel}/{target}/{old_id or 'none'}-to-{new_id}", status=200,
    )


def _published(workflow_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    workflow = voice_studio.engine_call("GET", f"/workflow/fetch/{workflow_id}")
    versions = voice_studio.engine_call("GET", f"/workflow/{workflow_id}/versions") or []
    published = next((v for v in versions if v.get("status") == "published"), None)
    if not workflow or workflow.get("status") != "active" or not published:
        raise ValueError("Choose an active agent with a published definition.")
    return workflow, published


def _tools() -> dict[str, dict[str, Any]]:
    rows = voice_studio.engine_call("GET", "/tools/?status=active") or []
    tools = {str(row["tool_uuid"]): row for row in rows}
    for uid, tool in tools.items():
        revisions = voice_studio.engine_call("GET", f"/tools/{uid}/revisions") or []
        tool["_revision"] = revisions[0] if revisions else None
    return tools


def _manifest_tools(workflow_id: int, definition_id: int) -> dict[str, dict[str, Any]]:
    rows = voice_studio.engine_call(
        "GET", f"/workflow/{workflow_id}/versions/{definition_id}/tool-manifest",
    ) or []
    tools: dict[str, dict[str, Any]] = {}
    for binding in rows:
        uid = str(binding.get("toolUuid") or "")
        snapshot = binding.get("snapshot") or {}
        tools[uid] = {**snapshot, "tool_uuid": uid, "_revision": binding}
    return tools


def _hook_credential() -> str | None:
    rows = voice_studio.engine_call("GET", "/credentials/") or []
    return next((str(r.get("uuid")) for r in rows
                 if r.get("name") == "PayInt hooks" and r.get("credential_type") == "bearer_token"), None)


def _check_tool(tool: dict[str, Any], credential: str | None) -> list[str]:
    name = str(tool.get("name") or "")
    if name not in APPROVED_ARGUMENTS:
        return []  # Additional Studio tools remain builder-owned.
    definition = tool.get("definition") or {}
    config = definition.get("config") or {}
    hooks = env_str("VOICE_STUDIO_HOOKS_URL", "http://api:8000/voice-studio/hooks").rstrip("/")
    if name == "transfer_to_human":
        resolver = config.get("resolver") or {}
        valid = (
            definition.get("type") == "transfer_call"
            and config.get("destination_source") == "dynamic"
            and resolver.get("url") == f"{hooks}/transfer"
            and resolver.get("credential_uuid") == credential
        )
        errors = [] if valid else [f"{name}: approved transfer resolver or credential differs"]
        presets = {p.get("name"): p for p in resolver.get("preset_parameters") or []}
        for param, kind in REQUIRED_PRESETS.items():
            if presets.get(param, {}).get("type") != kind or not presets.get(param, {}).get("value_template"):
                errors.append(f"{name}: engine context preset {param} is missing")
        return errors
    expected_url = f"{hooks}/tools/{name}"
    errors = []
    if definition.get("type") != "http_api" or config.get("method") != "POST" or config.get("url") != expected_url:
        errors.append(f"{name}: approved POST endpoint differs")
    if not credential or config.get("credential_uuid") != credential:
        errors.append(f"{name}: PayInt hooks credential is missing")
    params = {p.get("name"): p for p in config.get("parameters") or []}
    for param, kind in APPROVED_ARGUMENTS[name].items():
        if params.get(param, {}).get("type") != kind or not params.get(param, {}).get("required"):
            errors.append(f"{name}: required {param} parameter must be {kind}")
    presets = {p.get("name"): p for p in config.get("preset_parameters") or []}
    for param, kind in REQUIRED_PRESETS.items():
        if presets.get(param, {}).get("type") != kind or not presets.get(param, {}).get("value_template"):
            errors.append(f"{name}: engine context preset {param} is missing")
    return errors


def validate_definition(definition: dict[str, Any], *, channel: str | None = None,
                        active_tools: dict[str, dict[str, Any]] | None = None,
                        credential_uuid: str | None = None,
                        released: bool = False) -> dict[str, Any]:
    nodes = (definition or {}).get("nodes") or []
    edges = (definition or {}).get("edges") or []
    tools = active_tools if active_tools is not None else _tools()
    credential = credential_uuid if credential_uuid is not None else _hook_credential()
    errors: list[str] = []
    warnings: list[str] = []
    used: dict[str, dict[str, Any]] = {}
    node_tool_names: dict[str, set[str]] = {}
    for node in nodes:
        node_id = str(node.get("id") or "")
        node_tool_names[node_id] = set()
        for uid in (node.get("data") or {}).get("tool_uuids") or []:
            tool = tools.get(str(uid))
            if not tool:
                errors.append(f"{node.get('id')}: attached tool {uid} is not active")
                continue
            used[str(uid)] = tool
            name = str(tool.get("name") or "")
            node_tool_names[node_id].add(name)
            revision = tool.get("_revision") or {}
            state = revision.get("state")
            policy = revision.get("policy") or {}
            grandfathered = released and state == "legacy" and name in APPROVED_ARGUMENTS
            if state != "approved" and not grandfathered:
                errors.append(f"{node_id}: {name} revision is not approved")
            if channel and policy and channel not in policy.get("channels", []):
                errors.append(f"{node_id}: {name} revision does not allow {channel}")
            if channel and state == "approved" and not policy:
                errors.append(f"{node_id}: {name} approved revision has no live policy")
            errors.extend(_check_tool(tool, credential))
    names = {str(tool.get("name")) for tool in used.values()}
    if channel in {"outbound", "inbound", "whatsapp"} and "verify_identity" not in names:
        errors.append("The agent must attach approved verify_identity before account actions.")
    start = next((n for n in nodes if n.get("type") == "startCall"), {})
    start_data = start.get("data") or {}
    start_id = start.get("id")
    if channel and not start_id:
        errors.append("The agent needs a start node")
    # Account tools must be unreachable until an identity node has run. The
    # runtime also checks verification, but the graph must not promise success
    # or leak a position before that check.
    sensitive = {"account_position", "promise_to_pay", "request_callback", "flag_dispute"}
    sensitive.update(str(tool.get("name")) for tool in used.values()
                     if (tool.get("_revision") or {}).get("policy", {}).get("min_identity") == "challenge")
    if channel and start_id:
        graph: dict[str, list[str]] = {}
        for edge in edges:
            graph.setdefault(str(edge.get("source")), []).append(str(edge.get("target")))
        pending = [str(start_id)]
        seen: set[str] = set()
        while pending:
            node_id = pending.pop()
            if node_id in seen:
                continue
            seen.add(node_id)
            attached = node_tool_names.get(node_id, set())
            if attached & sensitive:
                errors.append(f"{node_id}: account tools are reachable before identity verification")
            if "verify_identity" not in attached:
                pending.extend(graph.get(node_id, []))
    if channel:
        end_ids = {str(n.get("id")) for n in nodes if n.get("type") == "endCall"}
        actions = {"promise_to_pay", "request_callback", "flag_dispute"}
        for node_id, attached in node_tool_names.items():
            if not attached & actions:
                continue
            if not any(str(edge.get("source")) == node_id and str(edge.get("target")) in end_ids
                       for edge in edges):
                continue
            failure_edges = [edge for edge in edges if str(edge.get("source")) == node_id
                             and str(edge.get("target")) in end_ids
                             and (edge.get("data") or {}).get("allow_failed_action") is True]
            if not failure_edges:
                warnings.append(f"{node_id}: add a failure close path for rejected actions")
    global_prompt = " ".join(str((n.get("data") or {}).get("prompt") or "") for n in nodes if n.get("type") == "globalNode").lower()
    if channel == "inbound":
        outgoing = {e.get("target") for e in edges if e.get("source") == start_id}
        node_ids = {n.get("id") for n in nodes if n.get("type") == "agentNode"
                    and "general" in str((n.get("data") or {}).get("name") or "").lower()}
        if (start_data.get("pre_call_fetch_mode") != "inbound" or len(outgoing) < 2
                or not (outgoing & node_ids) or "inbound" not in global_prompt):
            errors.append("Inbound agent needs inbound pre-call lookup and an intent choice before account help.")
    elif channel == "whatsapp":
        if "whatsapp" not in global_prompt or start_data.get("pre_call_fetch_mode") == "inbound":
            errors.append("WhatsApp agent must have a channel-specific opening without call pre-fetch.")
    elif channel == "outbound" and "outbound" not in (global_prompt + " " + str(start_data.get("prompt") or "").lower()):
        errors.append("Outbound agent needs an explicit outbound opening.")
    triggers = [n.get("data") or {} for n in nodes if n.get("type") == "trigger" and (n.get("data") or {}).get("enabled")]
    trigger_paths = [str(t.get("trigger_path") or "") for t in triggers if t.get("trigger_path")]
    if channel == "outbound" and len(trigger_paths) != 1:
        errors.append("Outbound agent needs exactly one enabled API trigger.")
    return {"ok": not errors, "errors": sorted(set(errors)), "warnings": sorted(set(warnings)),
            "toolUuids": sorted(used),
            "triggerPath": trigger_paths[0] if len(trigger_paths) == 1 else None}


def preflight(workflow_id: int, channel: str) -> dict[str, Any]:
    if channel not in {"outbound", "inbound", "whatsapp"}:
        raise ValueError("Unknown channel")
    workflow, version = _published(workflow_id)
    result = validate_definition(
        version.get("workflow_json") or {}, channel=channel,
        active_tools=_manifest_tools(workflow_id, int(version["id"])),
        released=True,
    )
    return {**result, "workflowId": workflow_id, "name": workflow.get("name"),
            "definitionId": version.get("id"), "version": version.get("version_number")}


def check_selection(workflow_id: int, channel: str, *, objective: str | None = None,
                    config_id: int | None = None, phone_id: int | None = None) -> dict[str, Any]:
    checked = preflight(workflow_id, channel)
    if channel == "inbound":
        if config_id is None or phone_id is None:
            raise ValueError("Choose an inbound phone number")
        phone = voice_studio.engine_call("GET", f"/organizations/telephony-configs/{config_id}/phone-numbers/{phone_id}")
        if not phone or not phone.get("is_active", True):
            raise ValueError("Choose an active phone number in this organization")
    elif channel == "outbound" and (not objective or not objective.strip() or objective.strip().lower() == "whatsapp"):
        raise ValueError("Choose an outbound objective (use '*' only for the outbound default)")
    return checked


def outbound_trigger_path(workflow_id: int) -> str:
    """Use the selected agent's published trigger, never a stored caller path."""
    _workflow, version = _published(workflow_id)
    nodes = (version.get("workflow_json") or {}).get("nodes") or []
    paths = [str((node.get("data") or {}).get("trigger_path")) for node in nodes
             if node.get("type") == "trigger" and (node.get("data") or {}).get("enabled")
             and (node.get("data") or {}).get("trigger_path")]
    if len(paths) != 1:
        raise ValueError("The selected published outbound agent needs exactly one API trigger")
    return paths[0]


def validate_publish(workflow_id: int) -> dict[str, Any]:
    """Check the draft the engine is about to publish, including live routes."""
    workflow = voice_studio.engine_call("GET", f"/workflow/fetch/{workflow_id}") or {}
    if workflow.get("version_status") != "draft":
        raise ValueError("No draft to publish")
    routes = list_routing()
    channels = set()
    if any(n.get("workflowId") == workflow_id for n in routes["numbers"]):
        channels.add("inbound")
    for binding in routes["bindings"]:
        if binding["engine_workflow_id"] == workflow_id:
            channels.add("whatsapp" if binding["objective"] == "whatsapp" else "outbound")
    results = [validate_definition(workflow.get("workflow_definition") or {}, channel=channel)
               for channel in channels] if channels else [validate_definition(workflow.get("workflow_definition") or {})]
    errors = sorted({e for result in results for e in result["errors"]})
    if channels:
        errors = sorted(set(errors) | {warning for result in results for warning in result["warnings"]})
    return {"ok": not errors, "errors": errors, "channels": sorted(channels)}


def list_routing() -> dict[str, Any]:
    import db

    workflows = voice_studio.engine_call("GET", "/workflow/summary") or []
    with db.engine.connect() as conn:
        bindings = [dict(r) for r in conn.execute(text(
            "SELECT objective, engine_workflow_id, label FROM voice_studio_agents "
            "WHERE tenant_id = :t AND enabled ORDER BY objective"
        ), {"t": db.current_tenant()}).mappings()]
    configs = voice_studio.engine_call("GET", "/organizations/telephony-configs") or {}
    configs = configs.get("configurations", []) if isinstance(configs, dict) else configs
    numbers = []
    for config in configs:
        found = voice_studio.engine_call("GET", f"/organizations/telephony-configs/{config['id']}/phone-numbers") or {}
        found = found.get("phone_numbers", []) if isinstance(found, dict) else found
        for number in found:
            address = str(number.get("address") or "")
            numbers.append({"id": number["id"], "configId": config["id"],
                            "label": number.get("label") or config.get("name"),
                            "addressMasked": f"••••{address[-4:]}",
                            "workflowId": number.get("inbound_workflow_id"),
                            "active": number.get("is_active", True)})
    return {"agents": [{"id": w["id"], "name": w["name"]} for w in workflows],
            "bindings": bindings, "numbers": numbers}


def _restore_inbound(path: str, previous_workflow_id: int | None) -> None:
    rollback = ({"inbound_workflow_id": previous_workflow_id} if previous_workflow_id
                else {"clear_inbound_workflow": True})
    restored = voice_studio.engine_call("PUT", path, json=rollback)
    if ((restored or {}).get("provider_sync") or {}).get("ok") is not True:
        raise RuntimeError("Inbound routing rollback did not sync; restore the previous mapping manually")


def assign(workflow_id: int, channel: str, *, objective: str | None = None,
           config_id: int | None = None, phone_id: int | None = None,
           actor: str | None = None) -> dict[str, Any]:
    import db

    if channel == "outbound" and objective is not None:
        objective = objective.strip()
    checked = check_selection(workflow_id, channel, objective=objective,
                              config_id=config_id, phone_id=phone_id)
    if not checked["ok"]:
        raise ValueError("; ".join(checked["errors"]))
    if channel == "inbound":
        if config_id is None or phone_id is None:
            raise ValueError("Choose an inbound phone number")
        path = f"/organizations/telephony-configs/{config_id}/phone-numbers/{phone_id}"
        previous = voice_studio.engine_call("GET", path)
        if not previous or not previous.get("is_active", True):
            raise ValueError("Choose an active phone number in this organization")
        old_id = previous.get("inbound_workflow_id")
        try:
            updated = voice_studio.engine_call("PUT", path, json={"inbound_workflow_id": workflow_id})
        except Exception:
            _restore_inbound(path, old_id)
            raise RuntimeError("Inbound routing response failed; previous mapping was restored") from None
        if ((updated or {}).get("provider_sync") or {}).get("ok") is not True:
            _restore_inbound(path, old_id)
            raise RuntimeError("Provider rejected inbound routing; previous mapping was restored")
        try:
            with db.engine.begin() as conn:
                _audit_assignment(conn, actor, channel, str(phone_id), old_id, workflow_id)
        except Exception:
            _restore_inbound(path, old_id)
            raise RuntimeError("Routing audit failed; previous inbound mapping was restored") from None
        return {"channel": channel, "workflowId": workflow_id, "previousWorkflowId": old_id,
                "phoneId": phone_id, "definitionId": checked["definitionId"]}
    if channel == "whatsapp":
        objective = "whatsapp"
    elif not objective or objective == "whatsapp" or not objective.strip():
        raise ValueError("Choose an outbound objective (use '*' only for the outbound default)")
    with db.engine.begin() as conn:
        old_id = conn.execute(text(
            "SELECT engine_workflow_id FROM voice_studio_agents WHERE tenant_id = :t AND objective = :o"
        ), {"t": db.current_tenant(), "o": objective}).scalar_one_or_none()
        voice_studio.ensure_bot(conn, workflow_id, str(checked["name"]))
        conn.execute(text("""
            INSERT INTO voice_studio_agents
              (tenant_id, objective, engine_workflow_id, trigger_path, label, updated_by_user_id)
            VALUES (:t, :o, :w, :p, :l, :u)
            ON CONFLICT (tenant_id, objective) DO UPDATE SET
              engine_workflow_id = EXCLUDED.engine_workflow_id,
              trigger_path = EXCLUDED.trigger_path, label = EXCLUDED.label,
              enabled = true, updated_by_user_id = EXCLUDED.updated_by_user_id, updated_at = now()
        """), {"t": db.current_tenant(), "o": objective, "w": workflow_id,
                "p": checked["triggerPath"] or "not-used", "l": checked["name"], "u": actor})
        _audit_assignment(conn, actor, channel, str(objective), old_id, workflow_id)
    return {"channel": channel, "objective": objective, "workflowId": workflow_id,
            "definitionId": checked["definitionId"]}
