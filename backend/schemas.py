from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


RiskLevel = Literal["critical", "high", "medium", "low"]
Channel = Literal["voice", "whatsapp", "chat", "email", "sms"]
Sentiment = Literal["positive", "neutral", "negative"]


class ContactResponse(BaseModel):
    phonePrimary: str = ""
    phoneAlt: str | None = None
    email: str = ""
    address: str = ""
    timezone: str = "Asia/Kolkata"
    language: str = "English"
    preferredWindow: str = "10:00-19:00 IST"
    dnd: bool = False


class AccountResponse(BaseModel):
    product: str = "Credit Card"
    openedOn: str | None = None
    apr: float | None = None
    sanctionedAmount: float | None = None
    bucket: str | None = None
    dpd: int = 0
    riskScore: int | None = None


class ConsentResponse(BaseModel):
    channel: Literal["call", "whatsapp", "sms", "email"]
    optedIn: bool
    source: str = "seed"
    capturedAt: str | None = None


class LedgerEntryResponse(BaseModel):
    id: str
    date: str
    description: str = ""
    type: Literal["charge", "payment", "fee", "adjustment", "waiver"]
    amount: float
    balance: float | None = None
    invoiceId: str | None = None


class EmiRowResponse(BaseModel):
    id: str
    index: int
    dueDate: str
    amount: float
    paidOn: str | None = None
    paidAmount: float | None = None
    status: Literal["paid", "upcoming", "overdue", "partial"]
    balanceCarried: float | None = None


class InteractionHandlerResponse(BaseModel):
    kind: Literal["bot", "human"]
    name: str


class InteractionResponse(BaseModel):
    id: str
    channel: Channel
    handler: InteractionHandlerResponse
    startedAt: str | None = None
    duration: str = ""
    disposition: str | None = None
    sentiment: Sentiment = "neutral"
    sentimentDelta: Literal["up", "down", "flat"] = "flat"
    summary: str | None = None
    intents: dict[str, bool] = {}
    transcript: list[str] = []


class PromiseResponse(BaseModel):
    id: str
    amount: float
    promisedDate: str
    createdAt: str
    channel: Channel
    handler: str
    status: Literal["upcoming", "kept", "broken", "partial"]
    reminderStatus: Literal["queued", "sent", "acknowledged", "off"]


class DisputeResponse(BaseModel):
    id: str
    type: str
    amount: float | None = None
    transcriptSnippet: str = ""
    status: Literal["new", "under_review", "awaiting_customer", "resolved", "rejected"]
    slaLabel: str = "Open"
    filedAt: str
    assignee: str | None = None


class DocumentRequestResponse(BaseModel):
    id: str
    type: str
    requestedVia: Channel
    requestedAt: str
    deliveryChannel: Literal["email", "whatsapp", "sms"]
    status: Literal["requested", "generating", "sent", "failed"]


class CustomerNoteResponse(BaseModel):
    id: str
    author: str
    at: str
    text: str
    pinned: bool = False


class CustomerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    accountId: str
    risk: RiskLevel
    outstanding: float
    minimumDue: float | None = None
    lastContact: str | None = None
    assignedTo: str = "Unassigned"
    contact: ContactResponse
    account: AccountResponse
    consent: list[ConsentResponse] = []
    ledger: list[LedgerEntryResponse] = []
    emi: list[EmiRowResponse] = []
    interactions: list[InteractionResponse] = []
    promises: list[PromiseResponse] = []
    disputes: list[DisputeResponse] = []
    documents: list[DocumentRequestResponse] = []
    notes: list[CustomerNoteResponse] = []


class CallResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    startedAt: str | None = None
    duration: int = 0
    channel: Channel
    direction: str | None = None
    handledBy: dict[str, str]
    customerId: str
    customerName: str
    accountId: str | None = None
    disposition: str | None = None
    summary: str | None = None
    avgSentiment: float | None = None
    sentiment: Sentiment = "neutral"
    redactionApplied: bool = False
    hash: str | None = None
    ragHits: int = 0
    latencyMs: int | None = None
    transcript: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    phoneMasked: str = ""
    tags: list[str] = []
    sentimentSeries: list[dict[str, Any]] = []
    disclosures: list[dict[str, Any]] = []
    routing: list[str] = []


class LeadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    customerId: str
    customerName: str
    accountId: str | None = None
    accountTail: str | None = None
    offer: dict[str, Any]
    stage: str
    capturedAt: str | None = None
    sourceCallId: str | None = None
    source: str | None = None
    sentimentAtCapture: str | None = None
    sentimentScore: float | None = None
    transcriptSnippet: str | None = None
    eligibilityFlags: list[dict[str, Any]] = []
    owner: str | None = None
    team: str | None = None
    priority: str = "normal"
    estimatedValue: float | None = None
    nextFollowUpAt: str | None = None
    followUps: list[dict[str, Any]] = []
    closedAt: str | None = None
    lossReason: str | None = None
    wonAmount: float | None = None
    events: list[dict[str, Any]] = []


class StaffResponse(BaseModel):
    """Assignable actors (humans + bots). Frontend pickers resolve names → ids
    from this instead of hardcoded maps that silently drift from the DB."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    kind: Literal["human", "bot"]
    team: str | None = None
    status: str | None = None


class MeResponse(BaseModel):
    """The acting user. One identity for the UI chrome and the actor recorded on
    writes — hardcoding a different name in the shell makes the audit trail lie."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    kind: Literal["human", "bot"] = "human"
    team: str | None = None
    status: str | None = None
    tenantId: str


class TeamResponse(BaseModel):
    """Queue / team roster for pickers (callbacks, routing)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str


class PtpEventResponse(BaseModel):
    at: str
    label: str
    tone: Literal["info", "success", "warn", "danger"] | None = None


class PromiseListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    customerId: str
    customerName: str
    accountTail: str
    amount: float
    promisedDate: str
    createdAt: str
    channel: Channel
    source: Literal["bot", "agent", "self"]
    owner: str
    reminderStatus: Literal["off", "scheduled", "sent"]
    status: Literal["upcoming", "due_today", "kept", "broken", "partial"]
    paidAmount: float | None = None
    notes: str | None = None
    planId: str | None = None
    events: list[PtpEventResponse] = []


class InstallmentResponse(BaseModel):
    index: int
    dueDate: str
    amount: float
    paid: bool
    paidOn: str | None = None


class PaymentPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    customerId: str
    customerName: str
    accountTail: str
    total: float
    cadence: Literal["weekly", "biweekly", "monthly"]
    startDate: str
    installments: list[InstallmentResponse] = []
    owner: str
    status: Literal["on_track", "slipped", "completed"]
    createdAt: str


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


class DashboardResponse(BaseModel):
    heroKpis: list[dict[str, Any]]
    kpis: list[dict[str, Any]]
    recoveryTrend: list[dict[str, Any]]
    callVolumeStacked: list[dict[str, Any]]
    sentimentDistribution: dict[str, int]
    botVsHuman: list[dict[str, Any]]
    leaderboard: list[dict[str, Any]]
    atRiskAccounts: list[dict[str, Any]]


class HandoffResponse(BaseModel):
    activeCall: dict[str, Any]
    customerContext: dict[str, Any]
    transcriptScript: list[dict[str, Any]]
    suggestions: list[dict[str, Any]] = []
    complianceItems: list[dict[str, Any]] = []
    dispositions: list[str] = []


class PromiseCreateRequest(BaseModel):
    customerId: str
    accountId: str | None = None
    interactionId: str | None = None
    amount: float = Field(gt=0)
    promisedDate: str
    channel: Channel = "voice"
    handler: str | None = None
    # Owner triplet: exactly one of ownerUserId / ownerBotId (defaults to the
    # acting user when neither is supplied).
    ownerUserId: str | None = None
    ownerBotId: str | None = None
    reminderStatus: Literal["off", "queued", "scheduled", "sent", "acknowledged", "failed"] = "queued"


class PromisePatchRequest(BaseModel):
    status: Literal["upcoming", "kept", "broken", "partial"] | None = None
    promisedDate: str | None = None
    paidAmount: float | None = Field(default=None, ge=0)


class PaymentPlanCreateRequest(BaseModel):
    customerId: str
    accountId: str | None = None
    totalAmount: float = Field(gt=0)
    installments: list[dict[str, Any]]


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
    source: Literal["bot_voice", "bot_chat", "agent"] = "agent"
    sentimentAtCapture: Sentiment = "neutral"
    sentimentScore: float | None = None
    transcriptSnippet: str | None = None
    ownerUserId: str | None = None
    teamId: str | None = None
    offerAmount: float | None = None
    offerRoi: str | None = None
    priority: Literal["low", "normal", "high"] = "normal"
    estimatedValue: float | None = None


class LeadPatchRequest(BaseModel):
    stage: Literal["interested", "contacted", "qualified", "won", "lost"] | None = None
    productId: str | None = None
    ownerUserId: str | None = None
    teamId: str | None = None
    offerAmount: float | None = None
    offerRoi: str | None = None
    wonAmount: float | None = None
    lossReason: str | None = None


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
    requestedVia: Literal["bot_voice", "bot_chat", "agent"]
    requestedAt: str
    deliveryChannel: Literal["whatsapp", "email", "sms"]
    deliveryTarget: str
    status: Literal["requested", "generating", "sent", "failed"]
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


class ConsentChannelPatch(BaseModel):
    """Per-channel write. Screen sends `status`; Customer 360 may send `optedIn`."""

    channel: Literal["call", "whatsapp", "sms", "email"]
    status: Literal["opted_in", "opted_out", "dnd", "expired"] | None = None
    optedIn: bool | None = None
    frequencyCapPerWeek: int | None = None
    usedThisWeek: int | None = None
    source: str | None = None


class AllowedWindowPatch(BaseModel):
    days: list[int]
    startHour: int
    endHour: int


class ConsentPatchRequest(BaseModel):
    """Consent screen + Customer 360 PATCH. Use exclude_unset so explicit nulls clear."""

    dnd: bool | None = None
    onDndRegistry: bool | None = None
    channels: list[ConsentChannelPatch] | None = None
    allowedWindow: AllowedWindowPatch | None = None
    consentExpiresAt: str | None = None
    note: str | None = None


class OptOutCreateRequest(BaseModel):
    channel: Literal["call", "whatsapp", "sms", "email", "all"]
    source: str = "Agent"
    note: str | None = None


class ConsentChannelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Literal["call", "whatsapp", "sms", "email"]
    status: Literal["opted_in", "opted_out", "dnd", "expired"]
    capturedAt: str
    source: Literal["IVR", "Agent", "Web", "Regulator", "Bulk Import", "WhatsApp Reply", "Onboarding"]
    frequencyCapPerWeek: int
    usedThisWeek: int


class AllowedWindowResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: list[int]
    startHour: int
    endHour: int


class OptOutEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    at: str
    channel: Literal["call", "whatsapp", "sms", "email", "all"]
    source: Literal["IVR", "Agent", "Web", "Regulator", "Bulk Import", "WhatsApp Reply"]
    actor: str
    note: str


class ConsentAuditEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    at: str
    actor: str
    action: str


class ConsentListResponse(BaseModel):
    """Consent & Communication Preferences screen shape — richer than Customer 360."""

    model_config = ConfigDict(extra="forbid")

    id: str
    customerId: str
    customerName: str
    accountId: str
    phone: str
    email: str
    timezone: str
    segment: Literal["Retail", "SME", "Priority"]
    channels: list[ConsentChannelResponse]
    allowedWindow: AllowedWindowResponse
    consentExpiresAt: str
    onDndRegistry: bool
    optOutLog: list[OptOutEventResponse] = []
    audit: list[ConsentAuditEntryResponse] = []


class ViolationTranscriptTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    t: int
    speaker: Literal["bot", "agent", "customer", "system"]
    text: str


class ViolationNoteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: str
    author: str
    text: str


class ViolationEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snippet: str
    preceding: ViolationTranscriptTurnResponse | None = None
    offending: ViolationTranscriptTurnResponse
    following: ViolationTranscriptTurnResponse | None = None


class ViolationActorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["bot", "human"]
    name: str


class ViolationListResponse(BaseModel):
    """Compliance Risk screen shape — richer than the thin PATCH stub."""

    model_config = ConfigDict(extra="forbid")

    id: str
    callId: str
    customerName: str
    ruleId: str
    severity: Literal["critical", "high", "medium", "low"]
    occurredAt: str
    atSec: int
    actor: ViolationActorResponse
    evidence: ViolationEvidenceResponse
    status: Literal["open", "in_review", "acknowledged", "resolved"]
    assignee: str | None = None
    notes: list[ViolationNoteResponse] = []


class ViolationPatchRequest(BaseModel):
    """Compliance Risk PATCH. Sent with exclude_unset so explicit null clears assignee.

    Free-text notes go through POST /violations/{id}/notes → activity_events,
    not the description column.
    """

    status: Literal["open", "in_review", "acknowledged", "resolved"] | None = None
    assigneeUserId: str | None = None


class ViolationNoteCreateRequest(BaseModel):
    text: str = Field(min_length=1)


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


class ScorecardCreateRequest(BaseModel):
    interactionId: str
    rubricId: str = "qa-rubric-v1"
    subjectUserId: str | None = None
    subjectBotId: str | None = None
    reviewerUserId: str | None = None
    totalScore: float | None = None
    band: str | None = None


class ScorecardPatchRequest(BaseModel):
    status: str | None = None
    totalScore: float | None = None
    band: str | None = None


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
    transcript: list[dict[str, Any]] = []


class InteractionWrapUpRequest(BaseModel):
    disposition: str
    notes: str | None = None
    flags: list[str] = []
    promise: PromiseCreateRequest | None = None
    dispute: DisputeCreateRequest | None = None
    callback: CallbackCreateRequest | None = None
