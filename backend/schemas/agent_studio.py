"""Prompt lint and roles: the request and response shapes of the Voice Studio
prompt lint (``routers/voice_studio_admin``) and the Roles page (``routers/roles``).

One module of the ``schemas`` package; ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class Guardrails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prohibited: list[str]
    escalateAbuse: bool
    escalateLegal: bool
    neverQuoteRate: bool
    neverPromiseWaiver: bool
    alwaysDiscloseRecording: bool
    refusePoliticsReligion: bool
    maxTurns: int
    maxSeconds: int


class PromptLintRequest(BaseModel):
    """Deterministic prompt checks (+ optional Azure LLM pass)."""

    model_config = ConfigDict(extra="forbid")

    prompt: str
    guardrails: Guardrails
    includeLlm: bool = False


class RolePermissionsPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permissionIds: list[str] = Field(default_factory=list, validation_alias=AliasChoices("permissionIds", "permission_ids"))


class RolePermissionResponse(BaseModel):
    id: str
    module: str
    action: str
    description: str
    #: What this permission unlocks in Voice Studio (the gateway's own rules).
    studioActions: list[str] = []


class RoleGrantResponse(BaseModel):
    role_id: str
    role: str
    permission_id: str


class RoleResponse(BaseModel):
    id: str
    name: str
    permissionIds: list[str]


class RolesCatalogResponse(BaseModel):
    """Roles page. `grants` is the resolved set the enforcer will honour."""

    permissions: list[RolePermissionResponse]
    agentPublishRoles: list[str]
    grants: list[RoleGrantResponse]
    roles: list[RoleResponse]
