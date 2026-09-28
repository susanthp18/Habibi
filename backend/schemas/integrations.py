"""Integrations and the provider registry.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Provider registry (Agent Studio → Providers)
# ---------------------------------------------------------------------------


# ── Integrations: env-backed providers (ops_screens) ─────────────────────────


# ── Integrations: MCP connectors, vault, keys, tasks ─────────────────────────


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
    #: Today's spend through this profile, tenant-wide -- what the cap is measured against.
    spentTodayInr: float = 0.0
    model: str | None = None
    envModel: str | None = None


class GatewayStatusResponse(BaseModel):
    enabled: bool
    baseUrl: str | None = None
    profiles: dict[str, GatewayProfileResponse]
    killSwitch: str | None = None
    voiceSloMs: int


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
