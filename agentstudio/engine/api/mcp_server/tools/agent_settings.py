"""MCP tools that read and change an agent's speech and model settings.

Settings are written as the agent's draft (``model_configuration_v2_override``)
through the same route the Voice Studio editor uses, so validation, secret
merging and masking are identical. Secrets never cross MCP: they are neither
returned nor accepted; keys are set in Voice Studio.
"""

from __future__ import annotations

import copy
from typing import Any

from fastapi import HTTPException

from api.db import db_client
from api.mcp_server.auth import authenticate_mcp_request
from api.mcp_server.tracing import traced_tool
from api.services.configuration.ai_model_configuration import (
    WORKFLOW_MODEL_CONFIGURATION_V2_OVERRIDE_KEY,
    get_effective_ai_model_configuration_for_workflow,
    get_resolved_ai_model_configuration,
)

_SECTIONS = ("llm", "stt", "tts")
_SECRET_FIELDS = {"api_key", "credentials", "aws_access_key", "aws_secret_key", "aws_session_token"}


def _error_result(code: str, message: str) -> dict[str, Any]:
    return {"updated": False, "error_code": code, "error": message}


def _public(section: Any) -> dict[str, Any] | None:
    if section is None:
        return None
    data = section.model_dump(mode="json", exclude_none=True)
    return {k: v for k, v in data.items() if k not in _SECRET_FIELDS}


async def _current(workflow_id: int, organization_id: int):
    workflow = await db_client.get_workflow(workflow_id, organization_id=organization_id)
    if workflow is None:
        return None, {}
    draft = await db_client.get_draft_version(workflow_id)
    source = draft or workflow.released_definition
    return workflow, copy.deepcopy((source.workflow_configurations if source else None) or {})


async def _settings(workflow_id: int, organization_id: int, configs: dict) -> dict[str, Any]:
    effective = await get_effective_ai_model_configuration_for_workflow(
        organization_id=organization_id, workflow_configurations=configs,
    )
    own = bool(configs.get(WORKFLOW_MODEL_CONFIGURATION_V2_OVERRIDE_KEY) or configs.get("model_overrides"))
    return {
        "workflow_id": workflow_id,
        "source": "agent" if own else "organization",
        **{name: _public(getattr(effective, name, None)) for name in _SECTIONS},
        "call_dispositions": list(configs.get("call_dispositions") or []),
    }


async def _organization_pipeline(organization_id: int) -> dict[str, Any]:
    resolved = await get_resolved_ai_model_configuration(organization_id=organization_id)
    if resolved.organization_configuration is None:
        return {}
    data = resolved.organization_configuration.model_dump(mode="json", exclude_none=True)
    return (data.get("byok") or {}).get("pipeline") or {}


@traced_tool
async def get_agent_settings(workflow_id: int) -> dict[str, Any]:
    """Read an agent's speech-to-text, voice and model settings (secrets omitted).

    `source` is "agent" when the agent has its own settings, "organization"
    when it inherits the organization's. Reads the draft when one exists.
    """
    user = await authenticate_mcp_request()
    workflow, configs = await _current(workflow_id, user.selected_organization_id)
    if workflow is None:
        return {"found": False, "error": f"Workflow {workflow_id} not found"}
    return {"found": True, **await _settings(workflow_id, user.selected_organization_id, configs)}


@traced_tool
async def update_agent_settings(
    workflow_id: int,
    stt: dict | None = None,
    tts: dict | None = None,
    llm: dict | None = None,
    call_dispositions: list[dict] | None = None,
) -> dict[str, Any]:
    """Change an agent's speech-to-text, voice or model settings, or its call
    outcomes, as a draft.

    Each argument is a partial section merged over the agent's current one
    (its own settings, else the organization's). Nothing is live until the
    agent is published in Voice Studio. Examples:
    - stt: {"languages": ["en-IN", "hi-IN", "ta-IN"], "language_id_mode": "continuous"}
    - tts: {"voice": "en-IN-NeerjaNeural", "voice_map": {"hi-IN": "hi-IN-SwaraNeural",
      "ta-IN": "ta-IN-PallaviNeural"}, "speed": 1.0, "style": "empathetic"}
    - llm: {"model": "gpt-4.1"}
    - call_dispositions: [{"code": "promise_to_pay", "description": "The customer
      committed to an amount and date and promise_to_pay succeeded."}, ...] --
      replaces the agent's list. The classifier picks one of these when a call
      ends at an exit without its own call_disposition.

    Keys and other secrets are never accepted here; set them in Voice Studio.
    A section may switch to the provider the organization's Models page uses
    (tts: {"provider": "fish", "voice": "..."}): it starts from the organization's
    section, whose key is copied server-side.

    On failure the result has `updated: false`, an `error_code` and an `error`:
    - `not_found` — no such workflow in this organization.
    - `secret_field` — a key or credential was passed; set it in Voice Studio.
    - `provider_change` — the organization's Models page does not use that provider,
      so there is no key to switch to; set it there (or in the agent's Voice Studio settings).
    - `invalid_settings` — nothing to change, or the settings failed validation
      (unsupported language, too many languages, a language with no voice, …).
    """
    user = await authenticate_mcp_request()
    changes = {name: fields for name, fields in (("stt", stt), ("tts", tts), ("llm", llm)) if fields}
    if not changes and call_dispositions is None:
        return _error_result("invalid_settings", "Pass at least one of stt, tts, llm or call_dispositions.")
    secrets = sorted(f"{name}.{field}" for name, fields in changes.items()
                     for field in fields if field in _SECRET_FIELDS)
    if secrets:
        return _error_result("secret_field", "Secrets are set in Voice Studio, not here: " + ", ".join(secrets))

    workflow, configs = await _current(workflow_id, user.selected_organization_id)
    if workflow is None:
        return _error_result("not_found", f"Workflow {workflow_id} not found")

    if call_dispositions is not None:
        configs["call_dispositions"] = call_dispositions
    if changes:
        base = configs.get(WORKFLOW_MODEL_CONFIGURATION_V2_OVERRIDE_KEY)
        if not base:
            resolved = await get_resolved_ai_model_configuration(
                organization_id=user.selected_organization_id,
            )
            if resolved.organization_configuration is None:
                return _error_result("invalid_settings", "The organization has no model configuration to start from.")
            base = resolved.organization_configuration.model_dump(mode="json", exclude_none=True)
        base = copy.deepcopy(base)
        pipeline = (base.get("byok") or {}).get("pipeline")
        if not pipeline:
            return _error_result("invalid_settings", "Agent settings apply to speech pipelines (bring-your-own-key mode).")
        organization_pipeline = None
        for name, fields in changes.items():
            current = pipeline.get(name) or {}
            if fields.get("provider") and fields["provider"] != current.get("provider"):
                if organization_pipeline is None:
                    organization_pipeline = await _organization_pipeline(user.selected_organization_id)
                organization_section = organization_pipeline.get(name) or {}
                if organization_section.get("provider") != fields["provider"]:
                    return _error_result(
                        "provider_change",
                        f"The organization's Models page does not use {fields['provider']} for {name}; "
                        "set it and its key there first, or change it in the agent's Voice Studio settings.",
                    )
                # Nothing of the old provider's section carries over. The
                # organization's section, key included, is copied server-side; the
                # key never crosses MCP (results omit secrets).
                pipeline[name] = {**organization_section, **fields}
                continue
            pipeline[name] = {**current, **fields}
        configs[WORKFLOW_MODEL_CONFIGURATION_V2_OVERRIDE_KEY] = base
        configs.pop("model_overrides", None)

    # The editor's own save path: validation, secret merge and draft write.
    from api.routes.workflow import UpdateWorkflowRequest, update_workflow
    from api.schemas.workflow_configurations import WorkflowConfigurationDefaults

    try:
        await update_workflow(
            workflow_id,
            UpdateWorkflowRequest(
                workflow_configurations=WorkflowConfigurationDefaults.model_validate(configs),
            ),
            user,
        )
    except HTTPException as exc:
        return _error_result("invalid_settings", str(exc.detail))
    except ValueError as exc:
        return _error_result("invalid_settings", str(exc))
    _, saved = await _current(workflow_id, user.selected_organization_id)
    return {"updated": True, **await _settings(workflow_id, user.selected_organization_id, saved)}
