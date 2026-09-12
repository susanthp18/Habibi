"""The supervisor floor and the dashboard.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

# The authored flow graph is a domain model, not a transport shape — it is
# shared verbatim by the API, the validator and the voice runtime, so it is
# defined once in flow_graph and reused here rather than restated.
from flow_graph import FlowGraph, FlowIssue, FlowValidation  # noqa: F401

from schemas.common import (
    AuthorityPolicyResponse,
)

class StaffResponse(BaseModel):
    """Assignable actors (humans + bots). Frontend pickers resolve names → ids
    from this instead of hardcoded maps that silently drift from the DB."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    kind: Literal["human", "bot"]
    team: str | None = None
    status: str | None = None


class TeamResponse(BaseModel):
    """Queue / team roster for pickers (callbacks, routing)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str


# ---------------------------------------------------------------------------
# My Workspace — Assigned queue (Phase 3B — reads from work_items view)
# ---------------------------------------------------------------------------

WorkItemEntityType = Literal[
    "dispute",
    "callback",
    "document_request",
    "promise",
    "followup",
    "lead",
    "bounce",
]


WorkItemSla = Literal["ok", "warn", "breach"]


class WorkItemResponse(BaseModel):
    """Assigned-queue row — mirrors Habibi QueueRow + entityType for tab bucketing."""

    model_config = ConfigDict(extra="forbid")

    id: str
    customer: str
    accountId: str
    type: str
    detail: str
    amount: float | None = None
    ageHours: int
    sla: WorkItemSla
    slaLabel: str
    entityType: WorkItemEntityType
    status: str | None = None
    assigneeUserId: str | None = None
    customerId: str | None = None
    enactedBy: str | None = None


# ---------------------------------------------------------------------------
# Workspace summary (StatsStrip + RightRail)
# ---------------------------------------------------------------------------


class WorkspaceStatsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    callsHandled: int
    callsHandledDelta: str
    aht: str
    ahtDelta: str
    resolutions: int
    resolutionRate: str
    promisesCount: int
    promisesAmount: float
    windowLabel: str


class WorkspaceNextCallbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    customer: str
    accountId: str
    reason: str
    time: str
    timezone: str
    inMinutes: int


class WorkspaceSlaCountdownResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    remaining: str
    level: WorkItemSla
    enactedBy: str | None = None


class WorkspaceNextLeadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    customer: str
    accountId: str
    productName: str
    amount: float | None = None
    stage: str
    window: str | None = None
    reason: str


class WorkspaceSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stats: WorkspaceStatsResponse
    nextCallback: WorkspaceNextCallbackResponse | None = None
    nextLead: WorkspaceNextLeadResponse | None = None
    slaCountdowns: list[WorkspaceSlaCountdownResponse]
    outsideWindowCount: int


# ── Floor / Webhooks / Integrations (ops screens) ─────────────────────────────


class FloorStatsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    callsInProgress: int
    avgSentiment: float
    criticalAlerts: int
    queueDepth: int
    agentsAvailable: int
    agentsOnCall: int
    botAtRisk: int
    longestWaitSec: int


class FloorSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calls: list[dict[str, Any]]
    alerts: list[dict[str, Any]]
    stats: FloorStatsResponse
    agents: list[dict[str, Any]] = []


class SupervisorActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interactionId: str
    action: Literal["listen_in", "whisper", "barge", "force_handoff"]
    note: str | None = None


# ── Floor: work-runtime jobs, copilot pack, supervisor actions, alerts ───────


class WorkRuntimeJobResponse(BaseModel):
    """work_runtime.adapter_pg._public — also the floor approval row."""

    id: str
    workflowType: str
    status: str
    customerId: str | None = None
    payload: dict[str, Any] = {}
    result: dict[str, Any] = {}
    error: str | None = None
    idempotencyKey: str
    inputRequiredReason: str | None = None
    approvedBy: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


class FloorApprovalSignalRequest(BaseModel):
    """``name`` or ``signal`` names the verb; ``userId`` is what the adapter
    records as approver. The whole body is stored on the signal row."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    signal: str | None = None
    userId: str | None = Field(default=None, validation_alias=AliasChoices("userId", "user_id"))


class CopilotTreatmentResponse(BaseModel):
    decisionId: str | None = None
    action: str | None = None
    channel: str | None = None
    rationale: str | None = None
    enacted: bool = False
    enactedBy: str | None = None
    scheduledAt: str | None = None


class CopilotEnginesResponse(BaseModel):
    authority: AuthorityPolicyResponse
    treatment: CopilotTreatmentResponse
    #: The latest live-QA row of the interaction pack, or nothing yet.
    liveQa: dict[str, Any] | None = None


class CopilotCardChipResponse(BaseModel):
    botId: str | None = None
    displayName: str | None = None
    skills: list[str] = []


class FloorCopilotResponse(BaseModel):
    interactionId: str
    customerId: str | None = None
    whisperDraft: str
    engineDraft: str
    engines: CopilotEnginesResponse
    vetoes: list[str]
    card: CopilotCardChipResponse
    approvals: list[WorkRuntimeJobResponse]


class SupervisorActionResponse(BaseModel):
    id: str
    ok: bool
    action: str
    interactionId: str
    audioJoined: bool


class FloorAlertAckResponse(BaseModel):
    id: str
    ok: bool
