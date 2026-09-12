"""Shapes more than one router serves: the customer and its account, the
interaction, the handoff session, the shared Ok/IdStatus envelopes.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# The authored flow graph is a domain model, not a transport shape — it is
# shared verbatim by the API, the validator and the voice runtime, so it is
# defined once in flow_graph and reused here rather than restated.
import contact_window
from flow_graph import FlowGraph, FlowIssue, FlowValidation  # noqa: F401
from agent_core import clock

RiskLevel = Literal["critical", "high", "medium", "low"]


Channel = Literal["voice", "whatsapp", "chat", "email", "sms"]


Sentiment = Literal["positive", "neutral", "negative"]


class ContactResponse(BaseModel):
    phonePrimary: str = ""
    phoneAlt: str | None = None
    email: str = ""
    address: str = ""
    timezone: str = clock.DEFAULT_TIMEZONE
    language: str = "English"
    #: The window a customer with nothing on file is assumed to allow. One
    #: constant, shared with the contact Gate: this used to read
    #: "10:00-19:00 IST" while contact_window said 09:00-20:00, so the
    #: console showed one window and the veto enforced another.
    preferredWindow: str = contact_window.DEFAULT_WINDOW
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
    #: ck_ledger_entries_type. `reversal` was missing here, so a reversed
    #: payment made the whole Customer 360 a 500.
    type: Literal["charge", "payment", "fee", "adjustment", "waiver", "reversal"]
    amount: float
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


# Disputes carry the work-item tones plus "done": a resolved dispute has no
# countdown left to run, and the board greys the chip rather than colouring it.
DisputeSla = Literal["ok", "warn", "breach", "done"]


class DisputeResponse(BaseModel):
    id: str
    type: str
    amount: float | None = None
    transcriptSnippet: str = ""
    status: Literal["new", "under_review", "awaiting_customer", "resolved", "rejected"]
    sla: DisputeSla = "ok"
    slaLabel: str = "Open"
    # Signed minutes: positive is time remaining, negative is time overdue.
    slaMinutes: int = 0
    filedAt: str
    assignee: str | None = None


class DocumentRequestResponse(BaseModel):
    id: str
    type: str
    requestedVia: Channel
    requestedAt: str
    deliveryChannel: Literal["email", "whatsapp", "sms"]
    status: Literal["requested", "generating", "sent", "failed"]
    source: str | None = None


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


class OfferPolicyResponse(BaseModel):
    """Latest offer-engine snapshot for a customer or a live interaction.

    Floor, Handoff, Customer 360 and Workspace all read this shape. ``status``
    is the only field a chip needs; the rest is for the inspector / NBA card.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "none",
        "suppressed",
        "shadow",
        "ready",
        "presented",
        "interested",
        "declined",
        "open_lead",
    ] = "none"
    decisionId: str | None = None
    customerId: str | None = None
    interactionId: str | None = None
    mode: str | None = None
    channel: str | None = None
    suppressionReason: str | None = None
    suppressionLabel: str | None = None
    productId: str | None = None
    productName: str | None = None
    suggestedAmount: float | None = None
    talkTrack: str | None = None
    reasonCodes: list[str] = []
    score: float | None = None
    presented: bool = False
    response: str | None = None
    leadId: str | None = None
    leadStage: str | None = None
    preferredWindow: str | None = None
    createdAt: str | None = None


class AuthorityPolicyResponse(BaseModel):
    """Latest authority-matrix snapshot for a customer or a live interaction.

    Floor, Handoff and Customer 360 all read this shape. ``status`` is the chip;
    ``approvedAmount`` is the only rupee figure anyone may speak.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "none",
        "escalate",
        "shadow",
        "cap",
        "auto_approve",
        "applied",
    ] = "none"
    decisionId: str | None = None
    customerId: str | None = None
    accountId: str | None = None
    interactionId: str | None = None
    mode: str | None = None
    feeType: str | None = None
    askedAmount: float | None = None
    verdict: str | None = None
    approvedAmount: float | None = None
    capAmount: float | None = None
    reason: str | None = None
    reasonLabel: str | None = None
    reasonCodes: list[str] = []
    talkTrack: str | None = None
    enacted: bool = False
    disputeId: str | None = None
    createdAt: str | None = None


class TreatmentAlternativeResponse(BaseModel):
    """One ranked action the engine considered but did not pick.

    Mirrors agent_core.treatment.scoring.ScoredAction.to_log(). Note the key is
    ``expectedValue`` here and ``expectedValueInr`` on the chosen action - the
    producer spells them differently, so this model does too.
    """

    model_config = ConfigDict(extra="forbid")

    action: str
    channel: str | None = None
    at: str | None = None
    expectedValue: float | None = None
    pReach: float | None = None
    pResolve: float | None = None
    cost: float | None = None
    #: The part of ``cost`` that is today's capacity price rather than the
    #: ledger price. ``expectedValue`` has it subtracted; an allocator reading
    #: these values back to price tomorrow's book must add it again.
    capacityPrice: float | None = None
    #: Which quantity ``expectedValue`` was built from - a response prior or a
    #: fitted uplift. Two rows carrying the same number mean different things
    #: without it (§8.1), so it travels with the number rather than beside it.
    estimand: str | None = None
    reasonCodes: list[str] = []
    #: Scorer-internal term breakdown. Open by construction - the components a
    #: scorer reports are its own business, and pinning them here would make
    #: adding a term to the scorer a schema change.
    components: dict[str, float] = {}


class TreatmentSnapshotResponse(BaseModel):
    """The decision engine's full payload, not just the row rendered as an NBA.

    Mirrors agent_core.treatment.engine.TreatmentResult.to_payload(). The
    excluded reasons and the ranked alternatives are what a supervisor
    overriding the decision needs, and they are already computed.

    test_customer_insights_api asserts field-for-field against to_payload(), so
    a key added there fails loudly here rather than 500ing in production.
    """

    model_config = ConfigDict(extra="forbid")

    action: str
    actionLabel: str | None = None
    channel: str | None = None
    at: str | None = None
    expectedValueInr: float | None = None
    suppressed: bool = False
    reason: str | None = None
    reasonText: str | None = None
    rationale: str = ""
    decisionId: str | None = None
    propensity: float | None = None
    policyVersion: int | None = None
    mode: str | None = None
    variant: str | None = None
    latencyMs: int | None = None
    alternatives: list[TreatmentAlternativeResponse] = []
    #: action -> veto reason, for the actions arbitration ruled out.
    excluded: dict[str, str] = {}


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


class DashboardResponse(BaseModel):
    heroKpis: list[dict[str, Any]]
    kpis: list[dict[str, Any]]
    recoveryTrend: list[dict[str, Any]]
    callVolumeStacked: list[dict[str, Any]]
    sentimentDistribution: dict[str, int]
    botVsHuman: list[dict[str, Any]]
    leaderboard: list[dict[str, Any]]
    atRiskAccounts: list[dict[str, Any]]


class HandoffLastPromise(BaseModel):
    amount: float
    date: str
    status: str


class HandoffNextEmi(BaseModel):
    amount: float
    dueDate: str
    daysOverdue: int = 0


class HandoffDnd(BaseModel):
    allowed: bool
    window: str = ""
    channels: list[str] = []


class HandoffActiveCall(BaseModel):
    interactionId: str
    handoffId: str
    customerId: str
    conversationId: str | None = None
    customerName: str
    accountId: str = ""
    phone: str = ""
    channel: str
    agentName: str = "Unassigned"
    transferredFrom: str = ""
    escalationReason: str
    startedAt: int
    status: Literal["pending_claim", "active", "completed"]
    claimed: bool
    risk: str = "medium"
    handlerUserId: str | None = None


class HandoffCustomerContext(BaseModel):
    risk: str
    outstanding: float = 0
    currency: str = "₹"
    lastPromise: HandoffLastPromise | None = None
    nextEmi: HandoffNextEmi | None = None
    openDisputes: int = 0
    dnd: HandoffDnd
    tenureMonths: int = 0
    product: str = ""
    offerPolicy: OfferPolicyResponse | None = None
    authorityPolicy: AuthorityPolicyResponse | None = None


class HandoffTranscriptTurn(BaseModel):
    id: str
    speaker: str
    text: str
    at: int = 0
    sentimentDelta: float | None = None


class HandoffSuggestion(BaseModel):
    id: str
    title: str
    body: str
    source: str = ""
    showAfter: int = 0
    accepted: bool = False


class HandoffComplianceItem(BaseModel):
    id: str
    label: str
    required: bool = True
    checked: bool = False
    locked: bool = False
    ruleId: str | None = None


class HandoffAlertItem(BaseModel):
    id: str
    kind: str
    severity: str = "medium"
    reason: str | None = None


class HandoffSessionResponse(BaseModel):
    interactionId: str
    handoffId: str
    customerId: str
    conversationId: str | None = None
    status: Literal["pending_claim", "active", "completed"]
    claimed: bool
    monitor: bool = False
    activeCall: HandoffActiveCall
    customerContext: HandoffCustomerContext
    transcriptScript: list[HandoffTranscriptTurn] = []
    sentimentSeries: list[float] = []
    suggestions: list[HandoffSuggestion] = []
    complianceItems: list[HandoffComplianceItem] = []
    alerts: list[HandoffAlertItem] = []
    dispositions: list[str] = []
    speakers: dict[str, str] = {}



class HandoffQueueItem(BaseModel):
    interactionId: str
    handoffId: str
    customerId: str
    customerName: str
    accountId: str = ""
    reason: str
    queue: str | None = None
    risk: str = "medium"
    waitSec: int = 0
    requestedAt: str | None = None


class HandoffQueueResponse(BaseModel):
    items: list[HandoffQueueItem] = []
    activeInteractionId: str | None = None


# ---------------------------------------------------------------------------
# Integrations / Webhooks / Telephony routers (WS7 response_model closure).
# Response models list every key the builder emits — a key missing here is
# silently dropped from the wire. Optional fields mark keys a branch may omit.
# ---------------------------------------------------------------------------


class OkResponse(BaseModel):
    ok: bool


class PaymentAllocationResponse(BaseModel):
    promiseId: str
    applied: float
    paidAmount: float
    status: str


class PaymentWebhookResponse(BaseModel):
    """`payments.record_payment`: the idempotent replay carries only the first
    four keys."""

    ok: bool
    intentId: str
    status: str
    idempotent: bool | None = None
    ledgerEntryId: str | None = None
    allocated: list[PaymentAllocationResponse] | None = None
    curedEvents: list[str] | None = None
    cureFailed: bool | None = None


class PaymentEventWebhookResponse(BaseModel):
    """`payment_events._result` minus `deferred`, which ingest_and_deliver pops."""

    ok: bool
    eventId: str | None = None
    idempotent: bool | None = None
    status: str | None = None
    firstTouch: str | None = None
    intentId: str | None = None
    suppressionReason: str | None = None


class AgentStudioOkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool


class AgentStudioSkillVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    skillId: str
    version: str
    status: str
    frontmatter: dict[str, Any]
    body: str
    allowedTools: list[str]
    contentHash: str
    signature: str | None
    signedBy: str | None
    pack: dict[str, Any]
    description: str
    evalSuite: Any | None
    origin: Any | None


class AgentStudioSkillSummaryResponse(BaseModel):
    """Library row. ``get_skill`` adds the detail fields on the subclass."""

    model_config = ConfigDict(extra="forbid")

    id: str
    slug: str
    origin: str
    signatureStatus: str
    latestVersionId: str | None
    description: str
    allowedTools: list[str]
    version: str
    status: str
    attachedCards: list[str]
    #: Cards that can *rehearse* this skill — `attachedCards` plus draft
    #: versions. Separate because `attachedCards` answers "who is live on this",
    #: which an operator reads before deleting or re-signing, and drafts would
    #: inflate that number.
    rehearsalCards: list[str] = []
    evalSuite: Any | None
    contentHash: str
    signed: bool
    hasSignedVersion: bool
    bodyTokens: int
    referenceFiles: list[str]


class AgentStudioSkillResponse(AgentStudioSkillSummaryResponse):
    """Detail / write return. Optional keys only appear when the mapper set them."""

    versions: list[AgentStudioSkillVersionResponse] | None = None
    frontmatter: dict[str, Any] | None = None
    body: str | None = None
    pack: dict[str, Any] | None = None
    markdown: str | None = None
    lintWarnings: list[dict[str, Any]] | None = None


# --- CRM / Evals / Studio / Platform / Sandbox / Payments / KB / Catalog / Billing / Routing routers (response_model closure) ---
# Response models list every key the builder emits — a key missing here is
# silently dropped from the wire. Sparse builders pair with
# ``response_model_exclude_unset=True`` on the route so the wire stays identical.


# ── CRM: write acknowledgements (db.py) ──────────────────────────────────────


class IdStatusResponse(BaseModel):
    """`{id, status}` — what the callback / follow-up / reminder writes return.
    ``status`` echoes the patch, so it is None when the patch carried none."""

    id: str
    status: str | None = None
