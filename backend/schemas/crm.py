"""CRM: customers, promises, plans, disputes, callbacks, leads, documents, scorecards.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# The authored flow graph is a domain model, not a transport shape — it is
# shared verbatim by the API, the validator and the voice runtime, so it is
# defined once in flow_graph and reused here rather than restated.
from flow_graph import FlowGraph, FlowIssue, FlowValidation  # noqa: F401

from schemas.common import (
    AuthorityPolicyResponse,
    Channel,
    DisputeResponse,
    DisputeSla,
    IdStatusResponse,
    OfferPolicyResponse,
    PromiseResponse,
    Sentiment,
    TreatmentSnapshotResponse,
)
from schemas.payments import (
    PromiseCreateRequest,
)

# Matches the leads.priority CHECK constraint. The tool catalog previously
# stopped at "high", so the 'urgent' the database allowed was unreachable.
LeadPriority = Literal["low", "normal", "high", "urgent"]


class InsightBulletResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    source: str
    confidence: Literal["high", "medium", "low"]


class NbaItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    rank: int
    title: str
    reason: str
    # Mirrors NbaActionKind in Habibi/src/lib/customerInsights.ts. The six after
    # "offer" are the decision engine's own vocabulary, mapped from A.ALL by
    # customer_insights._TREATMENT_ACTION_KIND; "wait" is a held decision, which
    # an operator has to see rather than an empty card. This Literal used to stop
    # at "offer", so every customer with a treatment snapshot — which is every
    # customer, since recommend_treatment never raises — 500'd on the way out.
    action: Literal[
        "ptp",
        "dispute",
        "statement",
        "call",
        "callback",
        "review",
        "offer",
        "message",
        "mandate",
        "schedule",
        "plan",
        "field",
        "legal",
        "wait",
    ]
    priority: Literal["high", "medium", "low"]
    leadId: str | None = None
    # Only on the engine's row (customer_insights._treatment_nba). Absent on the
    # case-handling items, hence every one of them optional.
    source: str | None = None
    decisionId: str | None = None
    expectedValueInr: float | None = None
    scheduledAt: str | None = None
    treatmentAction: str | None = None
    #: The engine decided but is not acting - shadow mode. Labelled, not hidden.
    advisory: bool | None = None


class BehaviorMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ptpKeepRate: int | None = None
    daysSinceContact: int | None = None
    openDisputeAmount: float = 0
    nextEmiAmount: float | None = None
    nextEmiDate: str | None = None
    paymentStreak: int = 0
    brokenPromiseCount: int = 0
    activePromiseAmount: float = 0


class ActivityPreviewItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    label: str
    note: str | None = None
    # customer_insights.synthesize_activity reads this off startedAt / createdAt /
    # filedAt / requestedAt, any of which can be null. Required-and-non-null here
    # was a second ResponseValidationError waiting for an empty activity preview.
    at: str | None = None
    tone: str | None = None


class CustomerInsightsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customerId: str
    summary: list[InsightBulletResponse] = []
    nba: list[NbaItemResponse] = []
    metrics: BehaviorMetricsResponse
    activity: list[ActivityPreviewItemResponse] = []
    generatedAt: str
    offerPolicy: OfferPolicyResponse | None = None
    authorityPolicy: AuthorityPolicyResponse | None = None
    treatment: TreatmentSnapshotResponse | None = None


class ProductResponse(BaseModel):
    """The offer catalog, served from the DB.

    The UI used to carry its own hardcoded copy of this list — six products
    with ticket bands and ROI strings that nothing reconciled against the
    `products` table the eligibility check actually reads. An agent could pick a
    product id that did not exist server-side.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    category: str | None = None
    family: str | None = None
    description: str | None = None
    minTicket: float | None = None
    maxTicket: float | None = None
    indicativeROI: str | None = None
    roiNumeric: float | None = None
    tenorMonthsMin: int | None = None
    tenorMonthsMax: int | None = None
    marginScore: float = 0.5
    isActive: bool = True
    channels: list[str] = []


class LeadStageTotals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = 0
    amount: float = 0.0


class LeadMetricsResponse(BaseModel):
    """Pipeline KPIs computed server-side over every matching lead.

    ``conversionRate`` and ``avgDaysToClose`` are nullable because a zero
    denominator is not a zero rate — a book with nothing captured this month
    and a book that converted none of what it captured need opposite responses.
    """

    model_config = ConfigDict(extra="forbid")

    total: int = 0
    openLeads: int = 0
    pipelineValue: float = 0.0
    wonWeek: int = 0
    wonWeekAmount: float = 0.0
    conversionRate: int | None = None
    captured30d: int = 0
    won30d: int = 0
    avgDaysToClose: int | None = None
    perStage: dict[str, LeadStageTotals] = {}


class DisputeEventResponse(BaseModel):
    at: str
    label: str
    actor: str | None = None
    tone: Literal["info", "success", "warn", "danger"] | None = None


class DisputeEvidenceResponse(BaseModel):
    id: str
    name: str
    kind: Literal["screenshot", "receipt", "statement", "audio", "other"]
    uploadedAt: str
    uploadedBy: str


class DisputeListResponse(BaseModel):
    """Disputes queue screen shape — richer than Customer 360 DisputeResponse."""

    model_config = ConfigDict(extra="forbid")

    id: str
    customerId: str
    customerName: str
    accountId: str
    accountTail: str
    type: Literal["paid_already", "wrong_amount", "not_my_account", "fee_waiver", "duplicate_charge", "fraud"]
    disputedAmount: float
    source: Literal["bot_voice", "bot_chat", "agent"]
    transcriptSnippet: str
    originConversationId: str | None = None
    capturedAt: str
    slaDueAt: str
    sla: DisputeSla
    slaLabel: str
    # Signed minutes: positive is time remaining, negative is time overdue.
    slaMinutes: int
    status: Literal["new", "under_review", "awaiting_customer", "resolved", "rejected"]
    assignee: str
    priority: Literal["low", "normal", "high", "urgent"]
    evidence: list[DisputeEvidenceResponse] = []
    events: list[DisputeEventResponse] = []
    resolutionCode: Literal[
        "valid_waive_fee",
        "valid_reverse_charge",
        "invalid_no_action",
        "duplicate",
        "needs_more_info",
    ] | None = None
    resolutionNotes: str | None = None


class TurnTraceResponse(BaseModel):
    """One turn of a conversation with everything that happened during it.

    ``turnId``/``turnIndex`` are null on the single synthetic "unattributed"
    entry that carries events whose turn could not be resolved — a tool call
    recorded before its transcript row existed. Surfaced rather than dropped:
    losing an audit record to a race is worse than showing it out of place.
    """

    turnId: str | None
    turnIndex: int | None
    speaker: str
    atSec: float | None = None
    text: str | None = None
    intent: str | None = None
    intentScore: float | None = None
    sentimentDelta: float | None = None
    latency: dict[str, Any] = {}
    toolCalls: list[dict[str, Any]] = []
    retrievals: list[dict[str, Any]] = []


class DisputeCreateRequest(BaseModel):
    customerId: str
    accountId: str | None = None
    interactionId: str | None = None
    type: str
    amount: float | None = None
    transcriptSnippet: str | None = None
    assigneeUserId: str | None = None
    priority: Literal["low", "normal", "high", "urgent"] = "normal"


class DisputePatchRequest(BaseModel):
    # Sent with exclude_unset, so an explicitly-null assigneeUserId means "unassign"
    # while an omitted field means "leave unchanged".
    status: Literal["new", "under_review", "awaiting_customer", "resolved", "rejected"] | None = None
    assigneeUserId: str | None = None
    resolutionCode: str | None = None
    resolutionNotes: str | None = None


class DisputeNoteCreateRequest(BaseModel):
    text: str = Field(min_length=1)


class EvidenceCreateRequest(BaseModel):
    # Server derives the storage path when the client doesn't supply one.
    storageRef: str | None = None
    filename: str
    mimeType: str
    sizeBytes: int | None = None
    hash: str | None = None


class CallbackEventResponse(BaseModel):
    at: str
    label: str
    actor: str | None = None
    tone: Literal["info", "success", "warn", "danger"] | None = None


class CallbackReminderResponse(BaseModel):
    at: str
    channel: Literal["whatsapp", "sms", "email"]
    status: Literal["queued", "sent", "acknowledged"]


class CallbackListResponse(BaseModel):
    """Callback & Scheduling Manager screen shape — richer than the 360 write contract."""

    model_config = ConfigDict(extra="forbid")

    id: str
    customerId: str
    customerName: str
    accountId: str
    accountTail: str
    reason: Literal[
        "payment_discussion",
        "dispute_followup",
        "document_query",
        "hardship_review",
        "upsell_interest",
        "general",
    ]
    scheduledAt: str
    windowMins: Literal[30, 60, 120]
    customerTimezone: str
    preferredWindow: str
    customerDnd: bool
    dndActive: bool
    source: Literal["bot_voice", "bot_chat", "agent"]
    assignee: str
    queue: str
    priority: Literal["low", "normal", "high", "urgent"]
    status: Literal["scheduled", "reminded", "in_progress", "completed", "missed", "rescheduled", "cancelled"]
    reminders: list[CallbackReminderResponse] = []
    transcriptSnippet: str
    originConversationId: str | None = None
    events: list[CallbackEventResponse] = []
    createdAt: str
    disposition: Literal["reached", "no_answer", "ptp_captured", "not_interested", "callback_again"] | None = None
    outcomeNotes: str | None = None


class CallbackCreateRequest(BaseModel):
    customerId: str
    accountId: str | None = None
    interactionId: str | None = None
    # Omitted / null → Unassigned (do not silently force the acting user).
    assigneeUserId: str | None = None
    teamId: str | None = None
    reason: Literal[
        "payment_discussion",
        "dispute_followup",
        "document_query",
        "hardship_review",
        "upsell_interest",
        "general",
    ]
    scheduledAt: str
    windowMins: Literal[30, 60, 120] = 30
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    transcriptSnippet: str | None = None


class CallbackPatchRequest(BaseModel):
    # Sent with exclude_unset, so an explicitly-null assigneeUserId means "unassign"
    # while an omitted field means "leave unchanged".
    scheduledAt: str | None = None
    assigneeUserId: str | None = None
    teamId: str | None = None
    status: Literal["scheduled", "reminded", "in_progress", "completed", "missed", "rescheduled", "cancelled"] | None = None
    disposition: Literal["reached", "no_answer", "ptp_captured", "not_interested", "callback_again"] | None = None
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    outcomeNotes: str | None = None
    windowMins: Literal[30, 60, 120] | None = None


class ReminderCreateRequest(BaseModel):
    channel: Channel
    scheduledAt: str | None = None
    note: str | None = None
    # queued = schedule for later; sent = agent just fired it from the sheet.
    status: Literal["queued", "scheduled", "sent", "acknowledged"] | None = None


class FollowupPatchRequest(BaseModel):
    status: Literal["open", "done", "cancelled"] | None = None


class LeadCreateRequest(BaseModel):
    customerId: str
    accountId: str | None = None
    interactionId: str | None = None
    productId: str
    stage: Literal["interested", "contacted", "qualified", "won", "lost"] = "interested"
    # voice_mesh is the insurance specialist worker. It was writing this column
    # already; leaving it out of the literal meant the UI could not label or
    # filter those leads at all.
    source: Literal["bot_voice", "bot_chat", "voice_mesh", "agent"] = "agent"
    sentimentAtCapture: Sentiment = "neutral"
    sentimentScore: float | None = None
    transcriptSnippet: str | None = None
    ownerUserId: str | None = None
    teamId: str | None = None
    offerAmount: float | None = None
    offerRoi: str | None = None
    priority: LeadPriority = "normal"
    estimatedValue: float | None = None
    # Channel the offer would be made on — makes the consent gate channel-exact
    # instead of blocking a voice pitch because email was opted out.
    channel: Literal["voice", "whatsapp", "sms", "email", "chat"] | None = None
    # Closes the loop on the offer_decisions row that approved this pitch.
    decisionId: str | None = None
    # Supervisor override for the duplicate-open-lead guard.
    allowDuplicate: bool = False


class LeadPatchRequest(BaseModel):
    # No `= None` defaults that mean "absent": the endpoint uses exclude_unset
    # so an explicit null clears the column and an omitted key leaves it alone.
    stage: Literal["interested", "contacted", "qualified", "won", "lost"] | None = None
    productId: str | None = None
    ownerUserId: str | None = None
    teamId: str | None = None
    offerAmount: float | None = None
    offerRoi: str | None = None
    wonAmount: float | None = None
    lossReason: str | None = None
    channel: Literal["voice", "whatsapp", "sms", "email", "chat"] | None = None


class DocumentRequestCreateRequest(BaseModel):
    customerId: str
    accountId: str | None = None
    interactionId: str | None = None
    docType: Literal[
        "account_statement",
        "no_dues_certificate",
        "interest_certificate",
        "foreclosure_letter",
        "loan_schedule",
        "payment_receipt",
        "kyc_letter",
    ] | str
    deliveryChannel: Literal["whatsapp", "email", "sms"]
    deliveryTarget: str | None = None
    templateId: str | None = None
    period: str | None = None
    requestedVia: Literal["bot_voice", "bot_chat", "agent"] | None = None
    # Omitted → assign acting user. Explicit null → Unassigned.
    assigneeUserId: str | None = None
    # Optional file metadata for generation; server owns storage_ref.
    filename: str | None = None
    mimeType: str | None = None


class DocumentPatchRequest(BaseModel):
    """Document Fulfilment Desk PATCH. Sent with exclude_unset so explicit nulls clear."""

    status: Literal["requested", "generating", "sent", "failed"] | None = None
    assigneeUserId: str | None = None
    deliveryChannel: Literal["whatsapp", "email", "sms"] | None = None
    deliveryTarget: str | None = None
    templateId: str | None = None
    period: str | None = None
    generatedAt: str | None = None
    sentAt: str | None = None
    failedReason: str | None = None
    sizeKb: int | None = None
    attempts: int | None = None
    note: str | None = None


class DocumentEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: str
    label: str
    actor: str | None = None
    tone: Literal["info", "success", "warn", "danger"] | None = None


class DocumentListResponse(BaseModel):
    """Document Fulfilment Desk screen shape — richer than Customer 360 DocumentRequestResponse."""

    model_config = ConfigDict(extra="forbid")

    id: str
    customerId: str
    customerName: str
    accountId: str
    accountTail: str
    docType: Literal[
        "account_statement",
        "no_dues_certificate",
        "interest_certificate",
        "foreclosure_letter",
        "loan_schedule",
        "payment_receipt",
        "kyc_letter",
    ]
    period: str | None = None
    requestedVia: Literal["bot_voice", "bot_chat", "agent", "mcp", "clerk", "vision", "inbox"]
    requestedAt: str
    deliveryChannel: Literal["whatsapp", "email", "sms"]
    deliveryTarget: str
    status: Literal["requested", "generating", "sent", "failed"]
    source: Literal["crm", "vision", "clerk", "mcp"] = "crm"
    templateId: str
    generatedAt: str | None = None
    sentAt: str | None = None
    failedReason: str | None = None
    sizeKb: int | None = None
    attempts: int
    assignee: str
    events: list[DocumentEventResponse] = []


class CustomerNoteCreateRequest(BaseModel):
    text: str = Field(min_length=1)
    pinned: bool = False


class ContactPolicyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason: str | None = None
    touchCounted: bool = False
    outreachToday: int = 0
    dailyCap: int = 3
    coalesced: bool = False
    channel: str
    purpose: str


class TranscriptTurnCreateRequest(BaseModel):
    """One turn of a manually logged interaction: who spoke, when, and what."""

    speaker: str = "human"
    atSec: int = Field(default=0, ge=0)
    text: str = ""


class InteractionCreateRequest(BaseModel):
    customerId: str
    accountId: str | None = None
    channel: Channel = "voice"
    direction: Literal["inbound", "outbound"] = "outbound"
    handlerKind: Literal["human", "bot"] = "human"
    handlerUserId: str | None = None
    handlerBotId: str | None = None
    disposition: str | None = None
    summary: str | None = None
    transcript: list[TranscriptTurnCreateRequest] = []


class InteractionWrapUpRequest(BaseModel):
    disposition: str
    notes: str | None = None
    flags: list[str] = []
    promise: PromiseCreateRequest | None = None
    dispute: DisputeCreateRequest | None = None
    callback: CallbackCreateRequest | None = None


class InteractionCostLineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    serviceId: str
    serviceName: str
    unit: str
    category: str
    color: str
    model: str | None
    units: float
    costInr: float
    events: int


class InteractionCostResponse(BaseModel):
    """Per-call cost breakdown, assembled from attributed usage events."""

    model_config = ConfigDict(extra="forbid")

    interactionId: str
    # False when the call carries no usage events at all — it predates metering.
    # The UI must not render that as a real zero.
    attributed: bool
    totalInr: float
    lines: list[InteractionCostLineResponse]
    durationSec: int
    channel: str | None
    status: str | None
    totalTokens: int


class DisputeNoteWriteResponse(BaseModel):
    id: str
    text: str


class DisputeEvidenceWriteResponse(BaseModel):
    """`{id, **payload}` — the optional keys ride only when the client sent them."""

    id: str
    filename: str
    mimeType: str
    storageRef: str | None = None
    sizeBytes: int | None = None
    hash: str | None = None


class WrapUpSpawnedResponse(BaseModel):
    """Only the children the wrap-up actually created are present."""

    promise: PromiseResponse | None = None
    dispute: DisputeResponse | None = None
    callback: IdStatusResponse | None = None


class WrapUpResponse(BaseModel):
    id: str
    spawned: WrapUpSpawnedResponse


class EligibilityFlagResponse(BaseModel):
    """One row of `capture.evaluate_product_eligibility`; `status` is set on
    the profile checks only."""

    ruleId: str | None = None
    code: str
    blocking: bool
    label: str
    passed: bool
    reason: str | None = None
    status: str | None = None


class LeadRevalidateResponse(BaseModel):
    leadId: str
    eligible: bool
    blockReason: str | None = None
    flags: list[EligibilityFlagResponse]


class DocumentIngestResponse(BaseModel):
    """`agent_core.vision.ingest_customer_document` ToolResult.data."""

    documentRequestId: str | None = None
    documentType: str | None = None
    source: str
    filename: str | None = None


class DocumentDeliveryAttemptCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    provider: str | None = None
    error: str | None = None
    failedReason: str | None = None


class DocumentDeliveryAttemptResponse(BaseModel):
    id: str
    status: str
    attemptNumber: int


class OutboundHourResponse(BaseModel):
    """`outbound.hourly_reach` — one row per local hour with a denominator."""

    hour: int
    attempts: int
    answered: int
    answerRate: float | None = None
