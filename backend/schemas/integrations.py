"""Integrations and the provider registry.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

# The authored flow graph is a domain model, not a transport shape — it is
# shared verbatim by the API, the validator and the voice runtime, so it is
# defined once in flow_graph and reused here rather than restated.
from flow_graph import FlowGraph, FlowIssue, FlowValidation  # noqa: F401

class ProviderEnabledPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


# ---------------------------------------------------------------------------
# Provider registry (Agent Studio → Providers)
# ---------------------------------------------------------------------------


class ProviderModelItem(BaseModel):
    """One row of the capability matrix, joined to its provider."""

    model_config = ConfigDict(extra="forbid")

    id: str
    providerId: str
    providerName: str
    kind: str
    modelId: str
    displayName: str
    serviceClass: str
    locales: list[str] = Field(default_factory=list)
    streaming: bool = True
    codeSwitch: bool = False
    onPrem: bool = False
    diarization: bool = False
    styles: list[str] = Field(default_factory=list)
    costPerUnit: float | None = None
    costUnit: str | None = None
    #: NULL until a shadow run measures it against our own audio.
    measuredLatencyP50Ms: int | None = None
    measuredLatencyP95Ms: int | None = None
    notes: str = ""
    #: The controls this model honours, rendered generically by the inspector.
    #: Empty means "not yet mapped" — the UI shows nothing rather than showing
    #: another provider's knobs, which would be controls that do nothing.
    paramsSchema: list[dict[str, Any]] = Field(default_factory=list)
    enabled: bool = True
    #: False when no API key is present, so the picker can show the provider
    #: greyed rather than hiding it — "why can't I pick X" must be answerable
    #: from the screen.
    configured: bool = True
    #: Whether the model can be constructed for a live call: ``live``,
    #: ``preview_only`` (auditionable but no streaming integration), or
    #: ``unavailable`` (the service class does not import — a missing Pipecat
    #: extra, or a class that was never written). A key alone does not make a
    #: model runnable, and binding one that is not silently fell back to Azure.
    runtime: str = "live"
    #: Why, when ``runtime`` is not ``live``. Shown as the tooltip on the chip.
    runtimeDetail: str = ""
    #: True when two identical requests give two different performances, so a
    #: "new take" control is meaningful. Deterministic engines get no such
    #: button rather than one that appears to do nothing. See
    #: ``ModelSpec.sampling`` for the measurements.
    sampling: bool = False


class ProviderBindingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    botId: str | None = None
    slot: str
    locale: str | None = None
    providerModelId: str
    providerId: str
    providerName: str
    modelId: str
    displayName: str
    voiceRef: str | None = None
    priority: int
    settings: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ProviderBindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: str = Field(pattern="^(stt|tts|llm)$")
    providerModelId: str
    botId: str | None = None
    locale: str | None = None
    voiceRef: str | None = None
    priority: int = Field(default=100, ge=1, le=1000)
    settings: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ProviderPoolKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tail: str
    uses: int
    retired: bool
    lastError: str = ""


class ProviderPoolStatus(BaseModel):
    """Key-pool health. Surfaces free-tier exhaustion before a demo hits it."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    total: int
    available: int
    retired: int
    sessionsBound: int
    keys: list[ProviderPoolKey] = Field(default_factory=list)


# ── Integrations: env-backed providers (ops_screens) ─────────────────────────


class ProviderFieldResponse(BaseModel):
    key: str
    label: str
    secret: bool = False


class ProviderUsageStatResponse(BaseModel):
    label: str
    value: str


class ProviderEnvStatusResponse(BaseModel):
    values: dict[str, str]
    #: The configured region or null -- never a default the runtime did not use.
    region: str | None
    health: str
    latencyMs: int
    enabled: bool
    usageStats: list[ProviderUsageStatResponse]
    costMonth: str
    unitLabel: str
    credentialsLocked: bool


class ProviderResponse(BaseModel):
    id: str
    name: str
    vendor: str
    category: str
    capability: str
    description: str
    docsUrl: str
    brandInitial: str
    brandColor: str
    capabilities: list[str]
    fields: list[ProviderFieldResponse]
    perEnv: dict[str, ProviderEnvStatusResponse]


class ProviderTestLogResponse(BaseModel):
    id: str
    at: str
    providerId: str
    env: str
    ok: bool
    latencyMs: int
    message: str
    payload: str | None = None


# ── Integrations: MCP connectors, vault, keys, tasks ─────────────────────────


class ConnectorResponse(BaseModel):
    id: str
    slug: str
    displayName: str
    kind: str
    url: str | None = None
    authRef: str | None = None
    allowPrefixes: list[str]
    dataClass: list[str]
    ttlMs: int | None = None
    timeoutMs: int | None = None
    allowedEnv: str | None = None
    status: str
    health: str
    lastToolsListAt: str | None = None
    toolsCache: list[dict[str, Any]]
    cimdIssuer: str | None = None
    cimdClientId: str | None = None
    circuitOpenedAt: str | None = None
    circuitFails: int


class ConnectorUpsertRequest(BaseModel):
    """Field names as the console sends them; snake_case accepted because the
    persist layer already read both spellings."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    id: str | None = None
    url: str | None = None
    kind: str = "remote_mcp"
    displayName: str | None = Field(default=None, validation_alias=AliasChoices("displayName", "display_name"))
    authRef: str | None = Field(default=None, validation_alias=AliasChoices("authRef", "auth_ref"))
    allowPrefixes: list[str] | None = Field(default=None, validation_alias=AliasChoices("allowPrefixes", "allow_prefixes"))
    dataClass: list[str] | None = Field(default=None, validation_alias=AliasChoices("dataClass", "data_class"))
    ttlMs: int | None = Field(default=None, validation_alias=AliasChoices("ttlMs", "ttl_ms"))
    timeoutMs: int | None = Field(default=None, validation_alias=AliasChoices("timeoutMs", "timeout_ms"))
    allowedEnv: str | None = Field(default=None, validation_alias=AliasChoices("allowedEnv", "allowed_env"))
    status: str | None = None


class ConnectorHealthTestResponse(BaseModel):
    """First-party: ok/tool/kind. Remote: ok/tools, or ok=false/error."""

    ok: bool
    tool: str | None = None
    kind: str | None = None
    tools: int | None = None
    error: str | None = None


class ConnectorCimdRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issuer: str


class ConnectorCimdResponse(BaseModel):
    ok: bool
    clientId: str
    issuer: str


class VaultRefResponse(BaseModel):
    id: str
    name: str
    purpose: str
    backend: str
    azureSecretName: str | None = None
    lastRotatedAt: str | None = None
    lastUsedAt: str | None = None
    createdAt: str | None = None
    hasSecret: bool


class VaultRefPutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    purpose: str = "other"
    secret: str


class VaultRefRotateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: str


class McpKeyResponse(BaseModel):
    id: str
    name: str
    prefix: str
    scopes: list[str]
    revoked: bool
    lastUsedAt: str | None = None
    createdAt: str | None = None


class McpKeyMintedResponse(BaseModel):
    """The one response that carries the raw key — shown once."""

    id: str
    name: str
    prefix: str
    scopes: list[str]
    key: str


class McpKeyMintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "key"
    scopes: list[str] = Field(default_factory=list)


class McpTaskResponse(BaseModel):
    id: str
    kind: str
    status: str
    customerId: str | None = None
    payload: dict[str, Any]
    result: dict[str, Any]
    error: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


class McpStatusResponse(BaseModel):
    stdioCommand: str
    httpEnabled: bool
    httpUrl: str
    tasksEnabled: bool
    appsEnabled: bool
    mtls: bool
    resources: list[str]


# ── Integrations: LLM gateway + canary ───────────────────────────────────────


class GatewayProfileResponse(BaseModel):
    capInr: float
    model: str | None = None
    envModel: str | None = None
    canaryModel: str | None = None


class GatewayEnvVarResponse(BaseModel):
    name: str
    value: str


class GatewayCanaryGatesResponse(BaseModel):
    regression: bool
    redteam: bool
    twin: bool
    injectionClosed: bool
    voiceSloOk: bool
    voiceSloMs: int | None = None
    budgetMs: int


class GatewayCanaryResponse(BaseModel):
    id: str
    candidateModel: str
    stage: str
    status: str
    regressionReportId: str | None = None
    redteamReportId: str | None = None
    twinReportId: str | None = None
    voiceSloMs: int | None = None
    injectionClosed: bool
    copyToEnv: list[GatewayEnvVarResponse]
    appliedEnv: bool
    createdAt: str | None = None
    updatedAt: str | None = None
    #: Only on propose/promote — the stage that was just run.
    gates: GatewayCanaryGatesResponse | None = None


class GatewayStatusResponse(BaseModel):
    enabled: bool
    baseUrl: str | None = None
    profiles: dict[str, GatewayProfileResponse]
    canary: GatewayCanaryResponse | None = None
    killSwitch: str | None = None
    voiceSloMs: int


class GatewayCanaryStateResponse(BaseModel):
    current: GatewayCanaryResponse | None = None
    history: list[GatewayCanaryResponse]


class GatewayCanaryProposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidateModel: str = Field(default="", validation_alias=AliasChoices("candidateModel", "candidate_model"))
    skipRedteam: bool = Field(default=False, validation_alias=AliasChoices("skipRedteam", "skip_redteam"))


class GatewayCanaryPromoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skipRedteam: bool = Field(default=False, validation_alias=AliasChoices("skipRedteam", "skip_redteam"))


# ── Integrations: bank boundary (raw rows, snake_case as bank_boundary.api emits)


class BankContractBindingResponse(BaseModel):
    contract_code: str
    schema_version: str
    adapter: str
    state: str
    bound_at: datetime


class BankContractStatusResponse(BaseModel):
    bindings: list[BankContractBindingResponse]
    ready: bool


class BankManifestResponse(BaseModel):
    id: str
    contract_code: str
    source: str
    business_date: date
    state: str
    reject_reason: str | None = None


class BankIngestResponse(BaseModel):
    id: str
    state: str
    replayed: bool


class BankReconciliationBreakResponse(BaseModel):
    id: str
    kind: str
    detail: dict[str, Any]
    contract_code: str
    business_date: date


class BankReadinessResponse(BaseModel):
    shadowUnlocked: bool
    waitOnly: bool
    nonContacting: bool
    reasons: list[str]
    consecutiveOk: dict[str, int]
    veto: str | None = None


class BankOutboxItemResponse(BaseModel):
    id: str
    contract_code: str
    idempotency_key: str
    state: str
    park_reason: str | None = None


class BankBreachDetailResponse(BaseModel):
    kind: str
    customer_id: str
    at: datetime


class BankBreachCoverageResponse(BaseModel):
    breaches: int
    breach_details: list[BankBreachDetailResponse]
    ledger_coverage_share: float
    sources_represented: list[str]
    green: bool
    n_events: int


class BankFairnessResponse(BaseModel):
    covered: bool
    n_subjects: int
    ready: bool


class BankComplaintFiledResponse(BaseModel):
    id: str
    state: str


class BankComplaintEventResponse(BaseModel):
    id: str
    customer_id: str
    direction: str
    kind: str
    event_time: datetime


class BankManifestIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contractCode: str
    schemaVersion: str = "bank-boundary.v1"
    source: str
    businessDate: str
    sourceRef: str
    controlCount: int
    controlSumPaise: int
    eventTime: str
    portfolioId: str = ""
    rows: list[dict] = []


class BankComplaintFileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customerId: str
    kind: str = "grievance"
    note: str | None = None
