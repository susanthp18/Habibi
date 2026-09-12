"""Platform: health, readiness, switches, bot analytics.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

# The authored flow graph is a domain model, not a transport shape — it is
# shared verbatim by the API, the validator and the voice runtime, so it is
# defined once in flow_graph and reused here rather than restated.
from flow_graph import FlowGraph, FlowIssue, FlowValidation  # noqa: F401

class MeResponse(BaseModel):
    """The acting user. One identity for the UI chrome and the actor recorded on
    writes — hardcoding a different name in the shell makes the audit trail lie."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    kind: Literal["human", "bot"] = "human"
    team: str | None = None
    status: str | None = None
    #: What this actor may do, as the route table enforces it.
    permissions: list[str] = []
    tenantId: str


class PresenceResponse(BaseModel):
    """Agent availability from agent_presence (My Workspace toggle)."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["available", "on_break", "wrap_up", "offline"]
    sinceAt: str


class PresencePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["available", "on_break", "wrap_up", "offline"]


class BotAnalyticsDailyPointResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    sessions: int
    contained: int
    escalated: int
    abandoned: int
    avgTurns: float
    latencyP50: float
    latencyP90: float
    latencyP99: float
    sentiment: float
    upsellPresented: int = 0
    ptpCaptured: int = 0


class BotAnalyticsIntentSentimentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    positive: int
    neutral: int
    negative: int


class BotAnalyticsIntentAggResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    sessions: int
    contained: int
    escalated: int
    abandoned: int
    avgTurns: float
    avgLatencyMs: float
    sentiment: BotAnalyticsIntentSentimentResponse


class BotAnalyticsEscalationReasonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    count: int
    trendDelta: float


class BotAnalyticsUnansweredQuestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    hits: int
    lastSeen: str
    topIntent: str
    hasKbDoc: bool
    suggestedFix: Literal["kb", "prompt", "both"]


class BotAnalyticsTurnsBucketResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    min: int
    max: int
    count: int


class BotAnalyticsFunnelStageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    count: int


class BotAnalyticsCardAggResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    botId: str
    sessions: int
    contained: int
    escalated: int
    containment: float
    handoffRate: float
    latencyP99: float
    sloMs: int = 800


class BotAnalyticsSkillBucketResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skillId: str
    activations: int


class BotAnalyticsResponse(BaseModel):
    """Conversation & Bot Analytics screen shape — live aggregates from interactions.

    KPIs are not included; the frontend derive them via computeKpis(dailySeries).
    """

    model_config = ConfigDict(extra="forbid")

    dailySeries: list[BotAnalyticsDailyPointResponse]
    intentAggs: list[BotAnalyticsIntentAggResponse]
    escalationReasons: list[BotAnalyticsEscalationReasonResponse]
    unansweredQuestions: list[BotAnalyticsUnansweredQuestionResponse]
    turnsHistogram: list[BotAnalyticsTurnsBucketResponse]
    funnelStages: list[BotAnalyticsFunnelStageResponse]
    byCard: list[BotAnalyticsCardAggResponse] = []
    skillHistogram: list[BotAnalyticsSkillBucketResponse] = []


# ── Platform ─────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: Literal["ok"]


class PoolSnapshotResponse(BaseModel):
    poolSize: int
    maxOverflow: int
    capacity: int
    checkedOut: int
    overflow: int
    available: int
    statementTimeoutMs: int
    poolRecycle: int


class MinioPingResponse(BaseModel):
    ok: bool
    configured: bool
    detail: str | None = None
    bucket: str | None = None


class CircuitSnapshotResponse(BaseModel):
    name: str
    state: Literal["closed", "open", "half_open"]
    failures: int
    threshold: int
    resetTimeoutS: float


class ReadinessResponse(BaseModel):
    """The 200 branch of /ready; the 503 branch carries the same dict as detail."""

    ok: bool
    db: bool | None = None
    pool: PoolSnapshotResponse
    detail: str | None = None
    minio: MinioPingResponse
    circuits: list[CircuitSnapshotResponse]


class PlatformSwitchResponse(BaseModel):
    """`platform_switches.get_all` — every known switch, flipped or not."""

    key: str
    description: str
    enabled: bool
    updatedAt: str | None = None
    updatedByUserId: str | None = None
    note: str | None = None


class PlatformSwitchesResponse(BaseModel):
    switches: list[PlatformSwitchResponse]


class PlatformSwitchPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    note: str | None = None


class PlatformSwitchFlipResponse(BaseModel):
    key: str
    enabled: bool
