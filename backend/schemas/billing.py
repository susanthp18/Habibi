"""Billing and usage analytics.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The authored flow graph is a domain model, not a transport shape — it is
# shared verbatim by the API, the validator and the voice runtime, so it is
# defined once in flow_graph and reused here rather than restated.
from flow_graph import FlowGraph, FlowIssue, FlowValidation  # noqa: F401

# ---------------------------------------------------------------------------
# Billing & Usage Analytics
# ---------------------------------------------------------------------------

BillingEnv = Literal["production", "sandbox"]


BillingPeriod = Literal["mtd", "7d", "30d", "quarter"]


BillingServiceCategory = Literal["LLM", "Voice", "Messaging", "Infra"]


BillingRuleSeverity = Literal["info", "warn", "critical"]


BillingInvoiceStatus = Literal["paid", "pending", "draft"]


class BillingServiceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    provider: str
    category: BillingServiceCategory
    unit: str
    unitCostInr: float
    color: str


class BillingDayPointResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    values: dict[str, float]


class BillingTenantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    resolvedCalls: int
    ahtSec: int
    budgetInr: float
    spendShare: float


class BillingTenantBreakdownResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    resolvedCalls: int
    ahtSec: int
    budgetInr: float
    spend: float
    spendPrev: float
    costPerCall: float
    budgetPct: float


class BillingBudgetRuleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    threshold: float
    channels: list[str]
    action: str
    severity: BillingRuleSeverity


class BillingBudgetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    env: BillingEnv
    month: str
    monthlyCapInr: float
    rules: list[BillingBudgetRuleResponse]


class BillingAlertResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    when: str
    ruleId: str
    env: BillingEnv
    message: str


class BillingInvoiceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    month: str
    status: BillingInvoiceStatus
    amountInr: float
    issuedAt: str


class BillingModelSpendResponse(BaseModel):
    """Spend for one (service, model) pair.

    billing_services carries a single blended llm_chat row, so this is the only
    place a gpt-5 turn can be told apart from a gpt-4o-mini one.
    """

    model_config = ConfigDict(extra="forbid")

    serviceId: str
    serviceName: str
    unit: str
    color: str
    model: str
    sourceRef: str | None = None
    units: float
    costInr: float
    calls: int


class BillingOverviewResponse(BaseModel):
    """Full /billing payload — already filtered by period / tenant / env."""

    model_config = ConfigDict(extra="forbid")

    asOf: str
    period: BillingPeriod
    env: BillingEnv
    tenantId: str
    services: list[BillingServiceResponse]
    tenants: list[BillingTenantResponse]
    daily: list[BillingDayPointResponse]
    previousDaily: list[BillingDayPointResponse]
    spend: float
    spendPrev: float
    forecast: float
    costPerCall: float
    costPerCallPrev: float
    resolvedCalls: int
    budgetCap: float
    spendByEnv: dict[str, float]
    budgets: list[BillingBudgetResponse]
    alerts: list[BillingAlertResponse]
    invoices: list[BillingInvoiceResponse]
    tenantBreakdown: list[BillingTenantBreakdownResponse]
    serviceTenantSpend: dict[str, dict[str, float]]
    # Measured cost per call, over calls carrying attributed usage. Distinct
    # from costPerCall above, which allocates all spend across resolved calls.
    # 0 with attributedCalls == 0 means "window predates metering", not "free".
    attributedCostPerCall: float
    attributedCalls: int
    modelSpend: list[BillingModelSpendResponse]


class BudgetRuleUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: float = Field(ge=1, le=200)
    channels: list[str] = Field(min_length=1)
    action: str = Field(min_length=1)
    severity: BillingRuleSeverity = "warn"


ExportFormat = Literal["pdf", "csv", "audio-zip"]


ExportScope = Literal["transcript", "audio", "metadata"]


ExportStatus = Literal["queued", "ready", "failed"]


class ExportJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    at: str
    actor: str
    actorRole: str
    recordIds: list[str]
    format: ExportFormat
    scope: list[ExportScope]
    watermark: str
    status: ExportStatus
    downloadCount: int
    entitiesRedacted: int


class ExportJobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recordIds: list[str] = Field(min_length=1)
    format: ExportFormat = "pdf"
    scope: list[ExportScope] = Field(default_factory=lambda: ["transcript"])
    watermark: str = ""
    actorRole: str = "Compliance Officer"


class ExportJobPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ExportStatus | None = None
    bumpDownload: bool | None = None
