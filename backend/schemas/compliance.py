"""Compliance: consent, contact policy, violations, redaction, exports, policy export.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# The authored flow graph is a domain model, not a transport shape — it is
# shared verbatim by the API, the validator and the voice runtime, so it is
# defined once in flow_graph and reused here rather than restated.
from flow_graph import FlowGraph, FlowIssue, FlowValidation  # noqa: F401

class ConsentChannelPatch(BaseModel):
    """Per-channel write. Screen sends `status`; Customer 360 may send `optedIn`."""

    channel: Literal["call", "whatsapp", "sms", "email"]
    status: Literal["opted_in", "opted_out", "dnd", "expired"] | None = None
    optedIn: bool | None = None
    frequencyCapPerWeek: int | None = None
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


class ContactableSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["green", "amber", "red"]
    reasons: list[str]


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
    outreachToday: int = 0
    dailyCap: int = 3
    lastDecisionReason: str | None = None
    #: The row's own reading across the four channels (the Gate answers per
    #: customer through /contact-policy).
    contactable: ContactableSummaryResponse


class ViolationTranscriptTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    t: int
    speaker: Literal["bot", "agent", "customer", "system"]
    text: str


class ViolationNoteItemResponse(BaseModel):
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
    ruleCode: str
    ruleLabel: str
    severity: Literal["critical", "high", "medium", "low"]
    occurredAt: str
    atSec: int
    actor: ViolationActorResponse
    evidence: ViolationEvidenceResponse
    status: Literal["open", "in_review", "acknowledged", "resolved"]
    assignee: str | None = None
    notes: list[ViolationNoteItemResponse] = []


class ViolationPatchRequest(BaseModel):
    """Compliance Risk PATCH. Sent with exclude_unset so explicit null clears assignee.

    Free-text notes go through POST /violations/{id}/notes → activity_events,
    not the description column.
    """

    status: Literal["open", "in_review", "acknowledged", "resolved"] | None = None
    assigneeUserId: str | None = None


class ViolationNoteCreateRequest(BaseModel):
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
    text: str | None = None
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


class PolicyRuleDraftItemRequest(BaseModel):
    """One rule in a draft set. ``params`` is shaped by ``kind`` and validated
    by ``policy_rules.validate_params``; the other fields are what
    ``policy_rules.create_draft`` reads."""

    kind: str
    params: dict[str, Any] = Field(default_factory=dict)
    channel: str | None = None
    citation: str | None = None
    rule_id: str | None = None
    rule_version: int | None = None


class PolicyRuleDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["statutory", "client", "product"]
    version: int
    label: str
    effectiveFrom: datetime
    effectiveTo: datetime | None = None
    notes: str | None = None
    tenantId: str | None = None
    productId: str | None = None
    rules: list[PolicyRuleDraftItemRequest]


class SubjectRequestCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customerId: str
    kind: Literal["access", "correction", "erasure", "grievance"]
    note: str | None = None


class SubjectRequestTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["received", "verified", "in_progress", "fulfilled", "refused", "escalated"]
    note: str | None = None
    evidenceRef: str | None = None


class SecurityIncidentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["low", "medium", "high", "critical"]
    summary: str
    evidenceRef: str | None = None


# ── Compliance: detector coverage, policy rule sets, replay, export ──────────


class RuleCoverageRowResponse(BaseModel):
    ruleId: str
    code: str
    label: str | None = None
    severity: str | None = None
    enabled: bool
    hasDetector: bool
    state: Literal["clean", "breached", "unverified", "disabled"]
    total: int
    open: int
    lastSeen: str | None = None


class RuleCoverageResponse(BaseModel):
    rules: list[RuleCoverageRowResponse]
    interactionsEvaluated: int
    rulesVersion: int
    detectorsRegistered: int


class ComplianceRescanResponse(BaseModel):
    scanned: int
    filed: int
    rulesVersion: int


class ViolationNoteResponse(BaseModel):
    id: str
    text: str


class RedactionAudioMuteResponse(BaseModel):
    redactionId: str
    findingId: str
    muted: bool


class PolicyExportCallingHoursResponse(BaseModel):
    startHour: int
    endHour: int
    tz: str


class PolicyExportAuthorityResponse(BaseModel):
    lateFeeCapInr: float
    lateFeeMidCapInr: float
    maxOutstandingInr: float
    maxDpd: int
    minTenureMonths: int


class PolicyExportDndResponse(BaseModel):
    contactWhenDnd: bool


class PolicyExportFactsResponse(BaseModel):
    callingHours: PolicyExportCallingHoursResponse
    authority: PolicyExportAuthorityResponse
    dnd: PolicyExportDndResponse
    source: str
    note: str


class PolicyExportResponse(BaseModel):
    format: Literal["opa", "cedar"]
    facts: PolicyExportFactsResponse
    text: str


class PolicyRuleSetResponse(BaseModel):
    """policy_rules.list_rule_sets: raw row; the W4 publication columns are
    selected only once that migration is in (exclude_unset keeps the wire)."""

    id: str
    scope: str
    tenant_id: str | None = None
    product_id: str | None = None
    version: int
    label: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    publication_state: str | None = None
    published_by_user_id: str | None = None
    approved_by_user_id: str | None = None
    changed_rules: list[str] | None = None


class PolicyRuleSetCreatedResponse(BaseModel):
    id: str


class PolicyRuleSetStateResponse(BaseModel):
    id: str
    state: Literal["pending_approval", "published", "rejected"]


class PolicyReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    windowStart: datetime | None = None
    windowEnd: datetime | None = None
    expectedDigest: str | None = None


class PolicyReplayResponse(BaseModel):
    id: str
    status: Literal["completed", "partial", "refused"]
    refusalReason: str | None = None
    compared: int
    mismatched: int
    evaluatorDigest: str
    vetoStackVersion: str


class ComplaintPackIdentityResponse(BaseModel):
    customerId: str
    tenantId: str
    timezone: str | None = None
    language: str | None = None


class ComplaintPackResponse(BaseModel):
    """complaint_pack.compose: every section is raw SQL rows, and ``digest``
    is computed over exactly those rows, so the sections stay open dicts."""

    identity: ComplaintPackIdentityResponse
    complaintEvents: list[dict[str, Any]]
    subjectRequests: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    policyBindings: list[dict[str, Any]]
    consentHistory: list[dict[str, Any]]
    endpointOwnership: list[dict[str, Any]]
    contactLedger: list[dict[str, Any]]
    receipts: list[dict[str, Any]]
    suppressions: list[dict[str, Any]]
    enactmentAttempts: list[dict[str, Any]]
    incidents: list[dict[str, Any]]
    externalLedger: list[dict[str, Any]]
    reconciliation: list[dict[str, Any]]
    mappings: list[dict[str, Any]]
    actionContracts: list[dict[str, Any]]
    acknowledgements: list[dict[str, Any]]
    generatedAt: str
    recordingRetentionMonths: int | None = None
    digest: str


class SubjectRequestResponse(BaseModel):
    id: str
    tenantId: str
    customerId: str
    kind: str
    state: str
    receivedAt: datetime | None = None
    verifiedAt: datetime | None = None
    dueAt: datetime | None = None
    fulfilledAt: datetime | None = None
    evidenceRef: str | None = None
    ownerUserId: str | None = None
    escalatedToUserId: str | None = None
    note: str | None = None


class SecurityIncidentCreatedResponse(BaseModel):
    id: str
    state: Literal["open"]


class SecurityIncidentResponse(BaseModel):
    id: str
    severity: str
    state: str
    summary: str | None = None
    detected_at: datetime | None = None


# ── Policy export bundle (regulator artefact) ────────────────────────────────
# Extends the PolicyExport* models above with the tenant's real DND rule, the
# window per channel and the published card's gates.


class PolicyExportDndRulesResponse(PolicyExportDndResponse):
    scrubLists: list[str]
    suppressionKinds: list[str]
    ruleSetVersion: int | None


class PolicyExportWindowResponse(BaseModel):
    startHour: int
    endHour: int


class PolicyExportCardResponse(BaseModel):
    botId: str
    versionId: str
    humanGates: list[dict[str, Any]]
    guardrails: dict[str, Any]


class PolicyExportBundleFactsResponse(PolicyExportFactsResponse):
    dnd: PolicyExportDndRulesResponse
    callingWindows: dict[str, PolicyExportWindowResponse]
    #: None when the bot has no published version — absent, not an empty card.
    card: PolicyExportCardResponse | None


class PolicyExportBundleResponse(PolicyExportResponse):
    facts: PolicyExportBundleFactsResponse
