"""Outbound: campaigns, missions, dials, treatment.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# The authored flow graph is a domain model, not a transport shape — it is
# shared verbatim by the API, the validator and the voice runtime, so it is
# defined once in flow_graph and reused here rather than restated.
from flow_graph import FlowGraph, FlowIssue, FlowValidation  # noqa: F401

from schemas.common import (
    TreatmentSnapshotResponse,
)

class OfferHealthResponse(BaseModel):
    """Part 7 of the upsell engine plan — the numbers that decide whether the
    recommender stays on.

    ``alerts`` carries the breaches with their reasons, computed server-side.
    A threshold that lives in a chart config is a threshold nobody reviews.
    """

    window: str
    includesSimulated: bool
    # What the engine is set to do, not only what it did. Every rate here is
    # null on an engine that has never run, and a panel showing nothing but
    # dashes cannot say whether that is a dead recommender or a quiet week.
    engine: dict[str, Any] = {}
    volume: dict[str, Any]
    funnel: dict[str, Any]
    latency: dict[str, Any]
    suppressionByReason: list[dict[str, Any]]
    exclusionByReason: list[dict[str, Any]]
    byProduct: list[dict[str, Any]]
    byRecommender: list[dict[str, Any]]
    byVariant: list[dict[str, Any]]
    eligibility: dict[str, Any]
    closeProbe: dict[str, Any]
    guardrails: dict[str, Any]
    alerts: list[dict[str, Any]]


class OfferResponseRequest(BaseModel):
    """What the borrower said about an offer that was delivered to them.

    The route this feeds is the one whose absence is the structural reason
    `offer_decisions` recorded **zero** responses in its entire history: the
    decision id was produced, typed and serialised, and every consumer discarded
    it at the call boundary. A self-improving system that never observes its own
    actions is not self-improving.

    `not_reached` is **censoring**, not refusal (§11.5) -- the offer never got
    there, so nobody declined it. Keeping the two apart is what stops an
    undelivered message being scored as a rejection.
    """

    model_config = ConfigDict(extra="forbid")

    response: Literal["interested", "declined", "deferred", "not_reached"]
    #: Free text from whoever recorded it. Never parsed, never scored.
    reason: str | None = None


class OfferResponseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisionId: str
    response: str
    #: False when the decision already carried a response. The first answer
    #: stands: a label that can be overwritten is a label somebody can tune.
    recorded: bool


class TreatmentHoldCreateRequest(BaseModel):
    """Place a collections hold — the veto the treatment engine reads.

    ``kind`` is closed rather than free text because each value carries
    different downstream behaviour: ``legal`` still permits a statutory notice,
    ``dispute`` still permits a specialist call about the dispute itself, and
    the rest stop outreach entirely. A new value with no rule behind it would
    silently mean "no hold at all".
    """

    model_config = ConfigDict(extra="forbid")

    customerId: str
    accountId: str | None = None
    kind: Literal[
        "hardship", "dispute", "complaint", "bereavement", "legal",
        "cease_and_desist", "deceased",
    ]
    reason: str | None = None
    source: Literal["manual", "bot", "system", "regulator"] = "manual"
    interactionId: str | None = None
    specialistUserId: str | None = None
    slaDueAt: str | None = None
    expiresAt: str | None = None


class TreatmentHoldReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


class AuthorityApplyRequest(BaseModel):
    """Post the goodwill the matrix already approved. Live mode only."""

    model_config = ConfigDict(extra="forbid")

    decisionId: str
    amount: float | None = None
    disputeId: str | None = None


class DecisionFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["wrong_number", "stop_contact", "deceased", "other"]
    reasonCode: str | None = None
    noteRedacted: str | None = None
    endpoint: str | None = None
    channel: str | None = None


# ── Outbound: demo dial, reach, campaigns, cadence, pools, obligations ───────


class DemoCustomerResponse(BaseModel):
    id: str
    name: str
    phone: str | None = None
    dnd: bool


class DemoOutboundTargetResponse(BaseModel):
    phone: str
    customer: DemoCustomerResponse | None = None
    objective: str
    offersAllowed: bool
    outboundEnabled: bool
    demoIgnoresWindow: bool
    policyReason: str | None = None
    policyWaived: str | None = None
    twilioConfigured: bool


class DemoOutboundCallResponse(BaseModel):
    placed: bool
    customerId: str | None = None
    phone: str
    attemptId: str | None = None
    callSid: str | None = None


class ReachStatsResponse(BaseModel):
    """outbound.reach_stats coerces every count to float, so the wire says
    ``12.0``; the model keeps that rather than quietly rounding the shape."""

    attempts: float
    suppressed: float
    answered: float
    right_party: float
    voicemail: float
    invalid_number: float
    no_answer: float
    busy: float
    avg_ring_sec: float | None = None
    avg_talk_sec: float | None = None
    talk_sec_total: float | None = None
    answerRate: float | None = None
    rightPartyRate: float | None = None
    attemptsPerConnect: float | None = None
    windowDays: int


class CallAttemptResponse(BaseModel):
    id: str
    customer_id: str
    customer_name: str
    objective: str
    attempt_no: int
    state: str
    suppressed_reason: str | None = None
    to_phone_last4: str | None = None
    answered_by: str | None = None
    right_party: bool | None = None
    ring_sec: int | None = None
    talk_sec: int | None = None
    provider_call_id: str | None = None
    provider_status: str | None = None
    provider_error: str | None = None
    interaction_id: str | None = None
    decision_id: str | None = None
    reserved_at: datetime
    placed_at: datetime | None = None
    answered_at: datetime | None = None
    ended_at: datetime | None = None
    connection: str | None = None
    business: str | None = None
    objective_met: bool | None = None
    nonpayment_reason: str | None = None
    summary: str | None = None
    summary_source: str | None = None


class NonpaymentReasonResponse(BaseModel):
    reason: str
    calls: int
    resolved: int


class CampaignSelectorRequest(BaseModel):
    """campaigns.SELECTOR_FIELDS — a closed set; the resolver rejects any other key."""

    model_config = ConfigDict(extra="forbid")

    buckets: list[str] | None = None
    dpdMin: int | None = None
    dpdMax: int | None = None
    minOutstandingInr: float | None = None
    maxOutstandingInr: float | None = None
    risk: list[str] | None = None
    language: list[str] | None = None
    excludeOpenPromise: bool | None = None
    excludeOnHold: bool | None = None
    excludeContactedWithinDays: int | None = None
    limit: int | None = None


class CampaignRunCreateRequest(BaseModel):
    """Defaults stay in campaigns.create (``int(x or 10)``); the model only
    names the keys the console sends and the ones db_outbound reads."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    objective: str | None = None
    botId: str | None = None
    cadence: str | None = None
    source: str | None = None
    selector: CampaignSelectorRequest | None = None
    windowStartHour: int | None = None
    windowEndHour: int | None = None
    maxConcurrent: int | None = None
    customerIds: list[str] | None = None


class CampaignCohortPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selector: CampaignSelectorRequest | None = None
    sample: int | None = None


class CampaignTargetsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customerIds: list[str] | None = None
    selector: CampaignSelectorRequest | None = None


class CampaignStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None


class CampaignProgressResponse(BaseModel):
    total: int
    pending: int
    dialing: int
    done: int
    skipped: int
    failed: int


class CampaignRunResponse(BaseModel):
    """campaign_runs row-star. The list adds pending/done/skipped, the detail
    adds ``progress``; create and status return the bare row."""

    id: str
    tenant_id: str
    bot_id: str | None = None
    deployment_id: str | None = None
    name: str
    objective: str
    cadence: str
    source: str
    selector: dict[str, Any] = {}
    status: str
    window_start_hour: int
    window_end_hour: int
    max_concurrent: int
    max_attempts_total: int | None = None
    targets_total: int
    targets_done: int
    created_by_user_id: str | None = None
    started_at: datetime | None = None
    paused_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    pending: int | None = None
    done: int | None = None
    skipped: int | None = None
    progress: CampaignProgressResponse | None = None


class CohortMemberResponse(BaseModel):
    customer_id: str
    name: str
    risk: str
    account_id: str
    dpd: int
    bucket: str | None = None
    outstanding: float


class CampaignCohortPreviewResponse(BaseModel):
    matched: int
    capped: bool
    sample: list[CohortMemberResponse]


class CampaignTargetsAddedResponse(BaseModel):
    runId: str
    added: int
    requested: int


class CadenceCaseResponse(BaseModel):
    id: str
    tenant_id: str
    customer_id: str
    objective: str
    case_ref: str
    cadence: str
    attempts: int
    max_attempts: int
    next_attempt_at: datetime | None = None
    last_attempt_id: str | None = None
    last_outcome: str | None = None
    state: str
    stopped_reason: str | None = None
    campaign_run_id: str | None = None
    bot_id: str | None = None
    escalate_to: str | None = None
    created_at: datetime
    updated_at: datetime
    customer_name: str


class PoolNumberResponse(BaseModel):
    id: str
    pool_id: str
    e164: str
    state: str
    last_used_at: datetime | None = None
    attempts_7d: int
    answer_rate_7d: float | None = None
    state_changed_at: datetime
    health_checked_at: datetime | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime


class NumberPoolResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    kind: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    numbers: list[PoolNumberResponse]


class AgentObligationResponse(BaseModel):
    id: str
    tenant_id: str
    customer_id: str
    interaction_id: str | None = None
    attempt_id: str | None = None
    kind: str
    due_at: datetime
    detail: dict[str, Any] = {}
    verbatim: str | None = None
    state: str
    honoured_at: datetime | None = None
    honoured_ref: str | None = None
    created_at: datetime
    updated_at: datetime
    customer_name: str


class OutboundAuthorityProfileResponse(BaseModel):
    name: str
    ceilingInr: float | None = None


class OutboundEnabledPoolResponse(BaseModel):
    name: str
    kind: str


class OutboundCardVocabularyResponse(BaseModel):
    objectives: list[str]
    objectiveBriefs: dict[str, str]
    directions: list[str]
    voicemailModes: list[str]
    poolKinds: list[str]
    qaModes: list[str]
    outcomeCodes: list[str]
    postCallActions: list[str]
    retryStates: list[str]
    authorityProfiles: list[OutboundAuthorityProfileResponse]
    numberPools: list[OutboundEnabledPoolResponse]
    dailyCap: int


class MissionObjectiveResponse(BaseModel):
    """One declared objective on the card, beside what the graph claims."""

    key: str
    entryNode: str
    graphEntryNode: str | None = None
    agrees: bool
    maxDurationSec: int
    allowedOffers: list[str]
    authorityProfile: str | None = None
    cadence: str
    success: list[str]
    brief: str


class MissionsResponse(BaseModel):
    botId: str
    direction: str
    poolKind: str
    numberPool: str | None = None
    objectives: list[MissionObjectiveResponse]
    graphEntries: dict[str, str]
    available: list[str]


class DecisionFeedbackResponse(BaseModel):
    id: str | None = None
    customerId: str
    verdict: str


# ── Treatment: holds, cases, next (with contract), scoreboards, registry ─────


class TreatmentHoldResponse(BaseModel):
    """_treatment_hold; the list view adds customerName/placedBy/specialist."""

    id: str
    customerId: str
    customerName: str | None = None
    accountId: str | None = None
    kind: str
    reason: str | None = None
    source: str
    interactionId: str | None = None
    slaDueAt: datetime | None = None
    startsAt: datetime | None = None
    expiresAt: datetime | None = None
    releasedAt: datetime | None = None
    releasedReason: str | None = None
    placedBy: str | None = None
    specialist: str | None = None
    active: bool
    createdAt: datetime | None = None


class TreatmentCaseResponse(BaseModel):
    id: str
    customerId: str
    customerName: str | None = None
    accountId: str | None = None
    trigger: str
    triggerRef: str
    decisions: int
    attempts: int
    ladder: list[str]
    lastAction: str | None = None
    lastOutcome: str | None = None
    lastSuppression: str | None = None
    rationale: str | None = None
    lastDecidedAt: datetime | None = None
    lastAttemptAt: datetime | None = None


class TreatmentActionContractResponse(BaseModel):
    """agent_core.treatment.contract.build — snake_case is the bank-boundary
    envelope, the camelCase twins are the operator payload. Both ship."""

    version: str
    decision_id: str | None = None
    tenant_id: str | None = None
    portfolio_id: str
    policy_binding: list[Any]
    policy_binding_hash: str | None = None
    engine_image_digest: str
    config_version: str
    veto_stack_version: str
    arm_propensity: float | None = None
    action_propensity: float | None = None
    propensity: float | None = None
    action: str
    channel: str | None = None
    endpoint: str | None = None
    scheduled_at: str | None = None
    expected_value_paise: int
    ev_lcb_paise: int
    expected_value_inr: float
    variant: str | None = None
    objective: str
    strategy: str
    prohibitions: list[str]
    required_assertions: list[str]
    retention_class: str
    policy_version: int | None = None
    allowed_offers: list[str]
    decisionId: str | None = None
    policyVersion: int | None = None
    scheduledAt: str | None = None
    expectedValueInr: float
    prohibited: list[str]
    allowedOffers: list[str]
    maxDurationSec: int | None = None
    max_duration_sec: int | None = None
    maxWaiverInr: float | None = None
    waiverRequiresIdentityCheck: bool | None = None


class TreatmentNextResponse(TreatmentSnapshotResponse):
    """to_payload() plus the Action Contract, present only when actionable."""

    contract: TreatmentActionContractResponse | None = None


class TreatmentReasonCountResponse(BaseModel):
    reason: str | None = None
    count: int


class TreatmentActionMixResponse(BaseModel):
    action: str
    count: int
    avgExpectedValue: float


class TreatmentModeCountResponse(BaseModel):
    mode: str | None = None
    count: int


class TreatmentOutcomeCountResponse(BaseModel):
    outcome: str
    count: int


class TreatmentInsightsResponse(BaseModel):
    windowDays: int
    decisions: int
    actionable: int
    coverage: float
    enacted: int
    customers: int
    expectedValueInr: float
    avgLatencyMs: int
    suppression: list[TreatmentReasonCountResponse]
    byAction: list[TreatmentActionMixResponse]
    byMode: list[TreatmentModeCountResponse]
    outcomes: list[TreatmentOutcomeCountResponse]


class TreatmentIntervalResponse(BaseModel):
    value: float
    low: float
    high: float
    clusters: int
    observations: int
    method: str
    replications: int
    excludesZero: bool


class TreatmentCausalResponse(BaseModel):
    """Three shapes: schema missing (available/reason), design floor missed
    (adds the panel figures), measured (adds the causal figures)."""

    available: bool
    reason: str | None = None
    controlClusters: int | None = None
    treatedClusters: int | None = None
    controlN: int | None = None
    treatedN: int | None = None
    panelWeeks: float | None = None
    casesPerCustomer: float | None = None
    icc: float | None = None
    designEffect: float | None = None
    panelCases: int | None = None
    panelClusters: int | None = None
    analysableCases: int | None = None
    analysableFraction: float | None = None
    controlCureRate: float | None = None
    treatedCureRate: float | None = None
    incrementalCureRate: float | None = None
    incrementalCureRateInterval: TreatmentIntervalResponse | None = None
    recoveredInr: float | None = None
    attributableRecoveryInr: float | None = None
    spendInr: float | None = None
    incrementalRecoveryPerRupee: float | None = None
    note: str | None = None


class TreatmentEfficiencyResponse(BaseModel):
    resolutions: int
    contacts: int
    voiceMinutes: float
    voiceCalls: int
    contactsPerResolution: float | None = None
    voiceMinutesPerResolution: float | None = None
    voiceMinutesPerLakhRecovered: float | None = None
    recoveredInr: float


class TreatmentComplaintsResponse(BaseModel):
    available: bool
    reason: str | None = None


class TreatmentComplianceResponse(BaseModel):
    attempts: int
    allowed: int
    denied: int
    denialRate: float | None = None
    denialsByReason: list[TreatmentReasonCountResponse]
    windowBreaches: int
    capBreaches: int
    worstDayTouches: int
    dailyCap: int
    breaches: int
    breachTarget: int
    breachNote: str
    optOuts: int
    complaints: TreatmentComplaintsResponse


class TreatmentBorrowerExperienceResponse(BaseModel):
    cases: int
    contactsPerCase: float
    worstCaseContacts: int
    casesOverFiveContacts: int
    heavyCaseShare: float | None = None


class TreatmentCapacityResourceResponse(BaseModel):
    resource: str
    daysSolved: int
    avgDualPriceInr: float
    priceSpreadInr: float
    stability: str
    undampedSpreadInr: float
    undampedStability: str
    utilisation: float
    unconfiguredDays: int
    daysFromFeed: int
    nonConvergedDays: int
    infeasibleDays: int


class TreatmentWithheldCasesResponse(BaseModel):
    evaluable: bool
    reason: str | None = None
    cases: int | None = None
    controlCases: int | None = None
    controlCustomers: int | None = None
    matureControlCases: int | None = None
    controlShare: float | None = None


class TreatmentCapacityResponse(BaseModel):
    resources: list[TreatmentCapacityResourceResponse]
    solved: bool
    reason: str | None = None
    withheldCases: TreatmentWithheldCasesResponse


class TreatmentCalibrationBinResponse(BaseModel):
    range: str
    n: int
    predicted: float
    observed: float
    gap: float


class TreatmentReachCalibrationResponse(BaseModel):
    n: int
    ece: float | None = None
    level: str | None = None
    bins: list[TreatmentCalibrationBinResponse]
    quantity: str


class TreatmentUpliftCalibrationResponse(BaseModel):
    available: bool
    reason: str | None = None
    treatedN: int
    controlN: int
    quantity: str | None = None
    fittedUplift: bool | None = None
    predictedMeanTau: float | None = None
    measuredAte: float | None = None
    gap: float | None = None
    level: str | None = None
    note: str | None = None


class TreatmentFeatureDriftItemResponse(BaseModel):
    feature: str
    trainedMean: float
    recentMean: float
    shiftSigma: float
    n: int
    level: str


class TreatmentFeatureDriftResponse(BaseModel):
    available: bool
    reason: str | None = None
    features: list[TreatmentFeatureDriftItemResponse]
    modelVersion: str | None = None
    unmeasurable: list[str] | None = None
    drifted: list[str] | None = None
    worst: TreatmentFeatureDriftItemResponse | None = None


class TreatmentModelVersionsResponse(BaseModel):
    reach: str | None = None
    uplift: str | None = None
    upliftSegments: int


class TreatmentAlertResponse(BaseModel):
    level: str
    check: str
    detail: str


class TreatmentModelHealthResponse(BaseModel):
    windowDays: int
    decisions: int
    sampleLimit: int
    truncated: bool
    driftSampled: int
    driftSampleLimit: int
    reachCalibration: TreatmentReachCalibrationResponse
    upliftCalibration: TreatmentUpliftCalibrationResponse
    featureDrift: TreatmentFeatureDriftResponse
    models: TreatmentModelVersionsResponse
    alerts: list[TreatmentAlertResponse]


class TreatmentMetricsResponse(BaseModel):
    windowDays: int
    causal: TreatmentCausalResponse
    efficiency: TreatmentEfficiencyResponse
    modelHealth: TreatmentModelHealthResponse
    compliance: TreatmentComplianceResponse
    borrowerExperience: TreatmentBorrowerExperienceResponse
    capacity: TreatmentCapacityResponse


class TreatmentModelRecordResponse(BaseModel):
    """treatment_model_registry row-star; metrics/evaluation are jsonb."""

    id: str
    target: str
    version: str
    status: str
    corpus: str
    n_samples: int
    control_n: int
    segments_promoted: int
    registered_at: datetime
    promoted_at: datetime | None = None
    promoted_by: str | None = None
    retired_at: datetime | None = None
    reason: str | None = None
    metrics: dict[str, Any] = {}
    evaluation: dict[str, Any] | None = None


class TreatmentServingCheckResponse(BaseModel):
    target: str
    state: str
    detail: str
    version: str | None = None
    promotedAt: datetime | None = None
    promotedBy: str | None = None


class TreatmentModelsResponse(BaseModel):
    history: list[TreatmentModelRecordResponse]
    serving: list[TreatmentServingCheckResponse]


# ── Authority: the matrix's answer, and the goodwill it posted ───────────────


class AuthorityPacketResponse(BaseModel):
    feeType: str
    askedAmount: float | None = None
    verdict: str
    approvedAmount: float | None = None
    capAmount: float | None = None
    reason: str | None = None
    reasonCodes: list[str]
    talkTrack: str
    customerId: str | None = None


class AuthorityNextResponse(BaseModel):
    verdict: str
    approvedAmount: float | None = None
    capAmount: float | None = None
    reason: str | None = None
    reasonCodes: list[str]
    talkTrack: str
    feeType: str
    askedAmount: float | None = None
    decisionId: str | None = None
    mode: str
    suppressed: bool
    actionable: bool
    packet: AuthorityPacketResponse | None = None
    latencyMs: int


class AuthorityApplyResponse(BaseModel):
    ledgerId: str
    disputeId: str | None = None
    amount: float
    accountId: str
    decisionId: str | None = None
