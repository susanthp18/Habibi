"""A2A tasks.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

# The authored flow graph is a domain model, not a transport shape — it is
# shared verbatim by the API, the validator and the voice runtime, so it is
# defined once in flow_graph and reused here rather than restated.
from flow_graph import FlowGraph, FlowIssue, FlowValidation  # noqa: F401

# ---------------------------------------------------------------------------
# --- Outbound / Compliance / Floor / A2A routers (response_model closure) ---
# Response models list every key the builder emits — a key missing here is
# silently dropped from the wire. Optional fields mark keys a branch may omit;
# those routes pair the model with response_model_exclude_unset=True. Raw
# SQL rows keep their snake_case spelling because the frontend reads it.
# ---------------------------------------------------------------------------


# ── A2A (agent_core.a2a): the Agent Card, partners, tasks ────────────────────


class A2aSkillResponse(BaseModel):
    id: str
    name: str
    description: str


class A2aCapabilitiesResponse(BaseModel):
    streaming: bool
    pushNotifications: bool


class A2aAuthenticationResponse(BaseModel):
    schemes: list[str]


class A2aProviderResponse(BaseModel):
    organization: str


class A2aAgentCardResponse(BaseModel):
    """The A2A 0.2.2 Agent Card exactly as agent_card_document emits it."""

    name: str | None = None
    description: str
    url: str
    version: str
    protocolVersion: str
    capabilities: A2aCapabilitiesResponse
    defaultInputModes: list[str]
    defaultOutputModes: list[str]
    skills: list[A2aSkillResponse]
    authentication: A2aAuthenticationResponse
    provider: A2aProviderResponse


class A2aPartnerResponse(BaseModel):
    id: str
    name: str
    cardUrl: str | None = None
    certFingerprint: str | None = None
    certDn: str | None = None
    botId: str | None = None
    allowedSkills: list[str]
    status: str | None = None


class A2aPartnerUpsertRequest(BaseModel):
    """Fields optional on purpose: upsert_partner is the validator (400 with
    its own reason codes), the model only names the body and forbids extras."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str | None = None
    certPem: str | None = Field(default=None, validation_alias=AliasChoices("certPem", "cert_pem"))
    certDn: str | None = Field(default=None, validation_alias=AliasChoices("certDn", "cert_dn"))
    botId: str | None = Field(default=None, validation_alias=AliasChoices("botId", "bot_id"))
    cardUrl: str | None = Field(default=None, validation_alias=AliasChoices("cardUrl", "card_url"))
    allowedSkills: list[str] | None = Field(
        default=None, validation_alias=AliasChoices("allowedSkills", "allowed_skills")
    )


class A2aTaskResponse(BaseModel):
    """_map_task. create_task's fallback is {id, status} only, hence exclude_unset."""

    id: str
    status: str | None = None
    partnerId: str | None = None
    botId: str | None = None
    skillId: str | None = None
    input: dict[str, Any] = {}
    output: dict[str, Any] = {}
    certDn: str | None = None
    error: str | None = None
    createdAt: str | None = None


class A2aTaskRequest(BaseModel):
    """Extra keys are kept, not forbidden: with no ``input`` object the whole
    body is the skill input (``payload=inner or payload``)."""

    model_config = ConfigDict(extra="allow")

    botId: str | None = Field(default=None, validation_alias=AliasChoices("botId", "bot_id"))
    skillId: str | None = Field(default=None, validation_alias=AliasChoices("skillId", "skill_id"))
    input: dict[str, Any] | None = None
    inputRequired: bool | None = None


class A2aTaskSignalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "approve"
