"""Billing and usage analytics.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    #: Metered quantity per service that day, in the service's unit.
    units: dict[str, float] = {}


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


class BillingInvoiceLineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    serviceId: str
    serviceName: str
    unit: str
    units: float
    unitCostInr: float
    amountInr: float


class BillingInvoiceDetailResponse(BaseModel):
    """A month's cost statement, built from metered usage (billing_jobs)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    month: str
    env: BillingEnv
    status: BillingInvoiceStatus
    totalInr: float
    issuedAt: str | None = None
    lines: list[BillingInvoiceLineResponse]


class BudgetCapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monthlyCapInr: float = Field(ge=0, le=1_000_000_000)


class InvoiceStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pending", "paid"]


class BudgetRuleUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: float = Field(ge=1, le=200)
    channels: list[str] = Field(min_length=1)
    action: str = Field(min_length=1)
    severity: BillingRuleSeverity = "warn"


ExportFormat = Literal["pdf", "csv", "audio-zip"]


ExportScope = Literal["transcript", "audio", "metadata"]


ExportStatus = Literal["queued", "running", "ready", "failed"]


ExportKind = Literal["redaction", "dashboard"]


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
    kind: ExportKind = "redaction"
    mailStatus: str | None = None
    # Why a failed export could not be built (e.g. a call still being redacted).
    error: str | None = None


class ExportAccessRoleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str


class ExportJobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ExportKind = "redaction"
    recordIds: list[str] = Field(default_factory=list)
    format: ExportFormat = "pdf"
    scope: list[ExportScope] = Field(default_factory=lambda: ["transcript"])
    watermark: str = ""
    # The role allowed to download the bundle: a role id or name of this tenant.
    actorRole: str = "role-compliance-officer"
    range: str = "30d"
    segment: str = "all"
    team: str = "all"

    @model_validator(mode="after")
    def _redaction_needs_records(self) -> "ExportJobCreateRequest":
        if self.kind == "redaction" and not self.recordIds:
            raise ValueError("record_ids_required")
        if self.kind == "dashboard":
            self.format = "csv"
        return self


class ExportJobPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ExportStatus | None = None
    bumpDownload: bool | None = None
