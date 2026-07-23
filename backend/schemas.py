from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, model_validator


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


class PresenceResponse(BaseModel):
    """Agent availability from agent_presence (My Workspace toggle)."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["available", "on_break", "wrap_up", "offline"]
    sinceAt: str


class PresencePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["available", "on_break", "wrap_up", "offline"]


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


class ScorecardEntryPatchRequest(BaseModel):
    criterionId: str
    aiSuggested: float | None = None
    score: float | None = None
    note: str | None = None
    accepted: bool | None = None


class ScorecardCreateRequest(BaseModel):
    interactionId: str
    rubricId: str = "rubric-v1"
    subjectUserId: str | None = None
    subjectBotId: str | None = None
    reviewerUserId: str | None = None
    status: Literal["unscored", "ai_draft", "final"] | None = None
    entries: list[ScorecardEntryPatchRequest] = []
    totalScore: float | None = None
    band: str | None = None


class ScorecardPatchRequest(BaseModel):
    """QA scorecard PATCH. Sent with exclude_unset so present keys are intentional.

    entries[] upserts qa_scorecard_entries; server recomputes total_score/band from
    the rubric. Finalize writes activity_events and sets scored_at.
    """

    status: Literal["unscored", "ai_draft", "final"] | None = None
    entries: list[ScorecardEntryPatchRequest] | None = None
    reviewerUserId: str | None = None
    subjectUserId: str | None = None
    subjectBotId: str | None = None
    totalScore: float | None = None
    band: str | None = None


class ScorecardHandledByResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["bot", "human", "handoff"]
    label: str


class ScorecardEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterionId: str
    aiSuggested: float
    score: float
    note: str | None = None
    accepted: bool | None = None


class ScorecardListResponse(BaseModel):
    """QA Scoring Queue row — mirrors Habibi Scorecard (qa-seed.ts)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    callId: str
    customerName: str
    disposition: str
    handledBy: ScorecardHandledByResponse
    agentId: str
    reviewer: str | None = None
    status: Literal["unscored", "ai_draft", "final"]
    entries: list[ScorecardEntryResponse]
    scoredAt: str | None = None
    createdAt: str


class RubricCriterionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    description: str
    weight: float
    critical: bool | None = None


class RubricSectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    weight: float
    criteria: list[RubricCriterionResponse]


class RubricResponse(BaseModel):
    """Active QA rubric — mirrors Habibi defaultRubric."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    version: str
    sections: list[RubricSectionResponse]


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


# ---------------------------------------------------------------------------
# Conversation Inbox (Phase 3B Tier 3)
# ---------------------------------------------------------------------------


class InboxMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    sender: Literal["customer", "bot", "agent"]
    text: str
    time: str
    delivery: Literal["sent", "delivered", "read"] | None = None


class InboxSystemEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["system"] = "system"
    text: str
    time: str


class InboxPromiseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: float
    date: str
    status: Literal["Kept", "Broken", "Pending", "Partial"]


class InboxDisputeSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    summary: str


class InboxInteractionSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["call", "chat"]
    summary: str
    when: str
    sentiment: Literal["positive", "neutral", "negative"]


class InboxThreadContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    riskLevel: Literal["High", "Medium", "Low"]
    contactableNow: bool
    contactWindow: str
    outstanding: float
    outstandingAging: str
    nextEmiDate: str
    nextEmiAmount: float
    lastPromise: InboxPromiseResponse | None = None
    openDisputes: list[InboxDisputeSummaryResponse] = []
    recentInteractions: list[InboxInteractionSummaryResponse] = []


class ConversationListResponse(BaseModel):
    """Conversation Inbox screen Thread shape."""

    model_config = ConfigDict(extra="forbid")

    id: str
    customer: str
    customerId: str
    accountId: str
    channel: Literal["whatsapp", "sms", "email"]
    status: Literal["bot", "needs_human", "escalated", "assigned"]
    assignedUserId: str | None = None
    isMine: bool
    botTyping: bool = False
    sla: Literal["ok", "warn", "breach"]
    unread: int
    lastTime: str
    lastPreview: str
    lastFrom: Literal["customer", "bot", "agent"]
    sentiment: Literal["positive", "neutral", "negative"]
    ragSuggestions: list[str] = []
    ragDraftAnswer: str | None = None
    messages: list[InboxMessageResponse | InboxSystemEventResponse] = []
    context: InboxThreadContextResponse


class CannedResponseItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    text: str


class ConversationMessageCreateRequest(BaseModel):
    text: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Redaction & Export Hub (Phase 3B — reads first)
# ---------------------------------------------------------------------------

PiiEntityType = Literal[
    "card", "pan", "phone", "email", "address", "dob", "account", "ifsc", "aadhaar", "custom"
]


class PiiFindingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    turnId: str
    type: PiiEntityType
    start: int
    end: int
    text: str
    masked: str
    confidence: float
    source: Literal["auto", "manual"]
    accepted: bool


class RedactionTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    t: int
    speaker: Literal["bot", "agent", "customer", "system"]
    text: str


class RedactionAudioSegmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atSec: int
    durSec: float
    type: PiiEntityType
    findingId: str
    muted: bool


class RedactionRecordListResponse(BaseModel):
    """Redaction queue row — mirrors Habibi RedactionRecord (redaction-seed.ts)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    callId: str
    customer: str
    customerId: str
    channel: Literal["voice", "whatsapp", "sms"]
    handler: str
    occurredAt: str
    durationSec: int
    transcript: list[RedactionTurnResponse]
    findings: list[PiiFindingResponse]
    audioSegments: list[RedactionAudioSegmentResponse]
    reviewed: bool


class RedactionRuleResponse(BaseModel):
    """Tenant redaction rule — maps to one entry in Habibi RedactionRules."""

    model_config = ConfigDict(extra="forbid")

    piiType: PiiEntityType
    enabled: bool
    replacement: str
    label: str


# ---------------------------------------------------------------------------
# Routing & Logic Builder (Phase 3B — reads first)
# ---------------------------------------------------------------------------

RoutingRuleCategory = Literal["Escalation", "Handoff", "Throttle", "Compliance", "Routing"]

RoutingActionKey = Literal[
    "route_tier2",
    "route_specialist",
    "handoff_human",
    "play_disclosure",
    "send_sms",
    "log_flag",
    "stop_upsell",
    "slow_tts",
    "escalate_supervisor",
]


class RoutingActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: RoutingActionKey
    params: dict[str, str] | None = None


class RoutingRuleListResponse(BaseModel):
    """Priority-ordered routing rule — mirrors Habibi Rule (routing-seed.ts)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    category: RoutingRuleCategory
    enabled: bool
    priority: int
    when: list[Any]  # ConditionNode[] — validated loosely; screen owns the shape
    then: RoutingActionResponse
    executionCount: int
    lastFiredAt: str | None
    triggersLast24h: int


class RoutingRuleExecutionResponse(BaseModel):
    """Single rule evaluation row — optional firing log for the builder."""

    model_config = ConfigDict(extra="forbid")

    id: str
    ruleId: str
    interactionId: str | None
    result: str | None
    actionTaken: str | None
    evaluatedAt: str
    context: dict[str, Any]


# ---------------------------------------------------------------------------
# Knowledge Base / RAG (Phase KB-1 — retrieve spine)
# ---------------------------------------------------------------------------


class KbRetrievalResultItem(BaseModel):
    """Mirrors Habibi RetrievalResult in kb-seed.ts."""

    model_config = ConfigDict(extra="forbid")

    chunkId: str
    docId: str
    docTitle: str
    heading: str
    snippet: str
    score: float
    matchedTerms: list[str]


class KbRetrieveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    topK: int = 4
    includeDraftAnswer: bool = True
    source: str = "test"


class KbRetrieveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[KbRetrievalResultItem]
    draftAnswer: str | None = None
    latencyMs: int
    embeddingModel: str
    chatModel: str | None = None
    logId: str


KbDocType = Literal["policy", "sop", "product", "compliance", "faq", "benefits"]
KbDocStatus = Literal["draft", "indexing", "indexed", "stale", "failed"]


class KbDocumentResponse(BaseModel):
    """Mirrors Habibi KbDocument in kb-seed.ts."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    filename: str
    type: KbDocType
    version: str
    status: KbDocStatus
    enabled: bool
    chunks: int
    chunkSize: int
    overlap: int
    embeddingModel: str
    updatedBy: str
    lastIndexed: str
    tags: list[str]


class KbChunkResponse(BaseModel):
    """Mirrors Habibi KbChunk."""

    model_config = ConfigDict(extra="forbid")

    id: str
    docId: str
    index: int
    heading: str
    tokens: int
    text: str
    hits: int


class KbStatsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    docs: int
    activeDocs: int
    faqs: int
    chunks: int
    gaps: int
    lastIndexed: str
    avgScore: float


class KbDocumentPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    title: str | None = None
    tags: list[str] | None = None
    chunkSize: int | None = None
    overlap: int | None = None


class KbReindexResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobId: str
    documentId: str
    status: str = "queued"


class KbIndexJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    documentId: str
    status: str
    chunkSize: int | None = None
    chunkOverlap: int | None = None
    embeddingModel: str | None = None
    startedAt: str | None = None
    completedAt: str | None = None
    error: str | None = None
    createdAt: str
    updatedAt: str


class KbUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: KbDocumentResponse
    jobId: str | None = None


class KbFaqResponse(BaseModel):
    """Mirrors Habibi FaqPair in kb-seed.ts."""

    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    answer: str
    intent: str
    enabled: bool
    updatedAt: str
    linkedDocId: str | None = None


class KbFaqCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str
    intent: str = "other"
    enabled: bool = True
    linkedDocId: str | None = None
    gapId: str | None = None  # optional: link analytics gap on create


class KbFaqPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str | None = None
    answer: str | None = None
    intent: str | None = None
    enabled: bool | None = None
    linkedDocId: str | None = None


KbGapSuggestedFix = Literal["kb", "prompt", "both"]


class KbGapResponse(BaseModel):
    """Coverage gap row — mirrors Habibi UnansweredQuestion (+ link state)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    hits: int
    lastSeen: str
    topIntent: str
    hasKbDoc: bool
    hasFaq: bool
    resolved: bool
    suggestedFix: KbGapSuggestedFix
    linkedDocumentId: str | None = None
    linkedFaqId: str | None = None
    linkedPromptVersionId: str | None = None


class KbGapLinkRequest(BaseModel):
    """Exactly one of faqPairId | kbDocumentId | promptVersionId."""

    model_config = ConfigDict(extra="forbid")

    faqPairId: str | None = None
    kbDocumentId: str | None = None
    promptVersionId: str | None = None


class ConversationSuggestionsRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topK: int = 4
    includeDraftAnswer: bool = False


class ConversationSuggestionsRefreshResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversationId: str
    ragSuggestions: list[str]
    draftAnswer: str | None = None
    chatModel: str | None = None
    latencyMs: int | None = None
    logId: str | None = None
    thread: ConversationListResponse | None = None


class KbSnapshotCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = None


class KbSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    documentIds: list[str] = []
    faqIds: list[str] = []
    documentCount: int = 0
    faqCount: int = 0
    createdAt: str | None = None


KbPurgeScope = Literal["all", "uploads", "corpus"]


class KbPurgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: KbPurgeScope = "uploads"
    confirm: bool = False


class KbPurgeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: KbPurgeScope
    documentsDeleted: int
    faqsDeleted: int
    minioObjectsRemoved: int = 0
    documentIds: list[str] = []


class KbDeleteDocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted: bool
    documentId: str
    faqsDeleted: int = 0
    minioObjectsRemoved: int = 0


class KbIngestSourceDbResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    products: list[str]
    jobsDrained: int
    faqsUpserted: int
    docs: int
    chunks: int
    faqs: int


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


# ---------------------------------------------------------------------------
# Persona & Prompt Studio (PS-1 reads — Habibi prompt-studio-seed.ts shapes)
# ---------------------------------------------------------------------------

PromptVersionStatus = Literal["draft", "published", "archived"]
BotDeploymentEnvironment = Literal["sandbox", "production"]
BotDeploymentStatus = Literal["active", "rolled_back", "retired"]
TtsGender = Literal["Female", "Male"]


class PersonaTraits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    empathy: int
    firmness: int
    formality: int
    verbosity: int
    upsell: int


class PersonaState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    traits: PersonaTraits
    language: str
    fallbackLanguages: list[str]


class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voiceId: str
    speed: float
    pitch: int
    warmth: int
    pauseMs: int
    sampleText: str


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


class PromptVersionResponse(BaseModel):
    """Mirrors Habibi PromptVersion."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    author: str
    status: PromptVersionStatus
    createdAt: str
    summary: str
    prompt: str
    persona: PersonaState
    voice: VoiceConfig
    guardrails: Guardrails
    tuning: dict[str, Any] = Field(default_factory=dict)


class PersonaPresetResponse(BaseModel):
    """Mirrors Habibi PersonaPreset."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    description: str
    traits: PersonaTraits
    promptTemplate: str


class TtsVoiceResponse(BaseModel):
    """Mirrors Habibi TtsVoice (+ azureVoiceName for PS-4)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    gender: TtsGender
    accent: str
    duration: str
    azureVoiceName: str | None = None


class BotDeploymentResponse(BaseModel):
    """Runtime release unit — authoritative for what runs (see PROMPT_STUDIO_plan §6.4)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    botId: str
    promptVersionId: str
    kbSnapshotId: str | None
    ttsVoiceId: str | None
    environment: BotDeploymentEnvironment
    status: BotDeploymentStatus
    publishedBy: str | None
    publishedAt: str | None
    rollbackDeploymentId: str | None
    voiceConfig: dict[str, Any]
    tuning: dict[str, Any] = Field(default_factory=dict)


class PromptVersionCreateRequest(BaseModel):
    """Create a draft prompt version (PS-2)."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    prompt: str
    persona: PersonaState
    voice: VoiceConfig
    guardrails: Guardrails
    summary: str = ""


class PromptVersionPatchRequest(BaseModel):
    """Update a draft only — 409 if not draft (PS-2)."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    prompt: str | None = None
    persona: PersonaState | None = None
    voice: VoiceConfig | None = None
    guardrails: Guardrails | None = None
    summary: str | None = None


class PromptVersionPublishRequest(BaseModel):
    """Promote a draft + create active prod deployment in one transaction."""

    model_config = ConfigDict(extra="forbid")

    summary: str = ""
    kbSnapshotId: str | None = None
    tuning: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Sandbox (PS-3) — scenarios + run transcript reads
# ---------------------------------------------------------------------------

SandboxDifficulty = Literal["easy", "medium", "hard"]


class SandboxPersonaResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    phoneLast4: str
    product: str
    dpd: int
    overdue: float
    mood: str
    language: str


class SandboxScenarioTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer: str
    expectedIntent: str | None = None
    expectedSentiment: float | None = None


class SandboxScenarioResponse(BaseModel):
    """Mirrors Habibi Scenario (sandbox-seed.ts) for the scenario picker."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    summary: str
    difficulty: SandboxDifficulty
    intents: list[str]
    persona: SandboxPersonaResponse
    openingBot: str
    turns: list[SandboxScenarioTurnResponse]


class SandboxGroundedChunkResponse(BaseModel):
    """Visible RAG proof — doc title chips on bot turns."""

    model_config = ConfigDict(extra="forbid")

    chunkId: str
    docTitle: str
    heading: str = ""
    snippet: str = ""


# ---------------------------------------------------------------------------
# Call Sandbox (PS-3 — Azure chat + KB retrieve)
# ---------------------------------------------------------------------------

SandboxRunStatus = Literal["running", "completed", "failed"]
SandboxSpeaker = Literal["bot", "customer", "system"]
SentimentLabel = Literal["positive", "neutral", "negative"]


class SandboxRunTurnResponse(BaseModel):
    """Persisted turn row for GET /sandbox/runs/{id}."""

    model_config = ConfigDict(extra="forbid")

    id: str
    turnIndex: int
    role: SandboxSpeaker
    text: str
    detectedIntent: str | None = None
    intent: str | None = None
    sentiment: float | None = None
    sentimentLabel: str | None = None
    chunkIds: list[str] = []
    retrievedChunkIds: list[str] = []
    groundedIn: list[SandboxGroundedChunkResponse] = []
    guardrailFlags: list[str] = []
    latencyMs: int | None = None
    tokens: int | None = None
    tokenCount: int | None = None
    ts: int = 0
    createdAt: str | None = None
    systemKind: Literal["info", "warn", "success"] | None = None

    @model_validator(mode="before")
    @classmethod
    def _speaker_alias_to_role(cls, data: Any) -> Any:
        """Accept legacy `speaker` from older mappers; schema field is `role`."""
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if "role" not in out and out.get("speaker") is not None:
            out["role"] = out["speaker"]
        out.pop("speaker", None)
        return out


class SandboxRunDetailResponse(BaseModel):
    """Full run + turns (newest-ready order is ascending by turnIndex)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    scenarioId: str | None = None
    deploymentId: str | None = None
    promptVersionId: str | None = None
    kbSnapshotId: str | None = None
    startedByUserId: str | None = None
    status: SandboxRunStatus
    aggregateLatencyMs: int | None = None
    aggregateTokens: int | None = None
    createdAt: str | None = None
    updatedAt: str | None = None
    turns: list[SandboxRunTurnResponse] = []


class SandboxContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_name: str | None = None
    account_no: str | None = None
    overdue_amount: str | None = None
    due_date: str | None = None
    last_payment: str | None = None
    agent_name: str | None = None
    bank_name: str | None = None
    language: str | None = None
    time_of_day: str | None = None


class SandboxHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["bot", "customer"]
    text: str


class SandboxRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    promptVersionId: str | None = None
    scenarioId: str | None = None
    scenarioTitle: str | None = None
    kbSnapshotId: str | None = None
    openingTemplate: str | None = None
    persona: dict[str, Any] | None = None
    context: SandboxContext | None = None


class SandboxRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    scenarioId: str | None = None
    deploymentId: str | None = None
    promptVersionId: str
    kbSnapshotId: str | None = None
    status: SandboxRunStatus
    openingMessage: str | None = None
    promptVersion: PromptVersionResponse
    context: dict[str, str]


class SandboxTurnCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    history: list[SandboxHistoryItem] = []
    context: SandboxContext | None = None
    topK: int = 4


class SandboxChunkHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunkId: str
    docId: str | None = None
    docTitle: str | None = None
    heading: str | None = None
    snippet: str | None = None
    score: float | None = None


class SandboxCustomerTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    role: Literal["customer"] = "customer"
    text: str
    intent: str
    intentScores: dict[str, float]
    sentiment: float
    sentimentLabel: SentimentLabel


class SandboxBotTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    role: Literal["bot"] = "bot"
    text: str
    chunkIds: list[str]
    chunks: list[SandboxChunkHit] = []
    latencyMs: int
    tokens: int
    guardrailFlags: list[str]
    intent: str
    sentiment: float
    sentimentLabel: SentimentLabel
    retrievalLogId: str | None = None
    retrieveLatencyMs: int | None = None
    chatLatencyMs: int | None = None
    halted: bool = False


class SandboxTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runId: str
    promptVersionId: str
    customerTurn: SandboxCustomerTurn
    botTurn: SandboxBotTurn


# ---------------------------------------------------------------------------
# Azure Speech TTS preview (PS-4)
# ---------------------------------------------------------------------------


class TtsPreviewRequest(BaseModel):
    """Synthesize sample text for the Prompt Studio Voice tab."""

    model_config = ConfigDict(extra="forbid")

    text: str
    voiceId: str
    speed: float = 1.0
    pitch: int = 0
    warmth: int = 60
    pauseMs: int = 300


class SttTranscribeResponse(BaseModel):
    """Azure Speech STT result — raw audio is not persisted."""

    model_config = ConfigDict(extra="forbid")

    text: str
    latencyMs: int
    language: str
    recognitionStatus: str | None = None


class PromptLintFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["error", "warn", "info"]
    code: str
    message: str
    span: dict[str, int] | None = None


class PromptLintRequest(BaseModel):
    """Deterministic prompt checks (+ optional Azure LLM pass)."""

    model_config = ConfigDict(extra="forbid")

    prompt: str
    guardrails: Guardrails
    includeLlm: bool = False


class PromptLintResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[PromptLintFinding]


class PromptTokenEstimateRequest(BaseModel):
    """Count prompt tokens with the same tiktoken encoding as chat/KB."""

    model_config = ConfigDict(extra="forbid")

    prompt: str


class PromptTokenEstimateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tokens: int
    encoding: str
    usdPer1M: float
    costUsd: float
    source: Literal["tiktoken", "heuristic"] = "tiktoken"


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


class BudgetRuleUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: float = Field(ge=1, le=200)
    channels: list[str] = Field(min_length=1)
    action: str = Field(min_length=1)
    severity: BillingRuleSeverity = "warn"


# ---------------------------------------------------------------------------
# QA Coaching / Calibration (Phase 3B fast-follow)
# ---------------------------------------------------------------------------

CoachingStatus = Literal["assigned", "in_progress", "done"]
CalibrationStatus = Literal["active", "closed"]


class CoachingNoteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: str
    author: str
    text: str


class CoachingActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    agentId: str
    title: str
    category: str
    scorecardId: str | None = None
    callId: str | None = None
    dueAt: str
    status: CoachingStatus
    notes: list[CoachingNoteResponse]
    createdAt: str


class CoachingActionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str
    title: str
    category: str = "General"
    scorecardId: str | None = None
    callId: str | None = None
    dueAt: str | None = None


class CoachingActionPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CoachingStatus | None = None
    title: str | None = None
    category: str | None = None
    dueAt: str | None = None


class CalibrationReviewerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer: str
    entries: list[ScorecardEntryResponse]


class CalibrationSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    callId: str
    customerName: str
    target: list[ScorecardEntryResponse]
    reviewers: list[CalibrationReviewerResponse]
    status: CalibrationStatus
    createdAt: str


class CalibrationSessionPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CalibrationStatus | None = None


# ---------------------------------------------------------------------------
# Redaction writes + export jobs
# ---------------------------------------------------------------------------


class PiiFindingPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool


class PiiFindingPatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    accepted: bool
    redactionId: str


class RedactionAudioMuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findingId: str
    muted: bool


class RedactionRecordPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed: bool | None = None


class RedactionRulePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    replacement: str | None = None


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


# ---------------------------------------------------------------------------
# Routing writes + audit
# ---------------------------------------------------------------------------


class RoutingActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: RoutingActionKey
    params: dict[str, str] | None = None


class RoutingRuleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str = "Untitled rule"
    description: str = ""
    category: RoutingRuleCategory = "Routing"
    enabled: bool = True
    priority: int | None = None
    when: list[Any] = Field(default_factory=list)
    then: RoutingActionRequest


class RoutingRulePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    category: RoutingRuleCategory | None = None
    enabled: bool | None = None
    priority: int | None = None
    when: list[Any] | None = None
    then: RoutingActionRequest | None = None


class RoutingReorderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orderedIds: list[str] = Field(min_length=1)


RoutingAuditAction = Literal[
    "created", "edited", "reordered", "toggled", "deleted", "duplicated"
]


class RoutingAuditEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    at: str
    author: str
    ruleId: str | None = None
    ruleName: str
    action: RoutingAuditAction
    summary: str


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


class WorkspaceSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stats: WorkspaceStatsResponse
    nextCallback: WorkspaceNextCallbackResponse | None = None
    slaCountdowns: list[WorkspaceSlaCountdownResponse]
    outsideWindowCount: int

