"""Evals: suites, runs, reports, twins, QA packs.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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
    # Who decided it: evidence (rules on the call's facts), model (small
    # model signals), llm (the judge), or human.
    tier: Literal["evidence", "model", "llm", "human"] | None = None
    confidence: float | None = None
    # Turn indexes, flags or timings the decision rests on.
    evidence: dict[str, Any] | None = None
    modelVersion: str | None = None


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
    rubricId: str | None = None


class RubricCriterionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    description: str
    weight: float
    critical: bool | None = None
    # Same lineage = the same question across rubric versions (sql/72).
    lineageId: str | None = None


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


_Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RubricCriterionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The predecessor's criterion id; with an unchanged label and description
    # the criterion keeps its lineage across versions.
    id: str | None = None
    label: _Label
    description: str = ""
    weight: float = Field(gt=0, le=100)
    critical: bool = False


class RubricSectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    label: _Label
    weight: float = Field(gt=0, le=100)
    criteria: list[RubricCriterionInput] = Field(min_length=1)


class RubricVersionCreateRequest(BaseModel):
    """POST /qa/rubrics/{rubric_id}/versions -- the edited rubric, saved as a new version.

    Weights are percentages: sections sum to 100, and so do each section's
    criteria (as in the seeded rubric), which is what the total computes from.
    """

    model_config = ConfigDict(extra="forbid")

    sections: list[RubricSectionInput] = Field(min_length=1)

    @model_validator(mode="after")
    def _weights_sum_to_100(self) -> "RubricVersionCreateRequest":
        total = sum(s.weight for s in self.sections)
        if abs(total - 100) > 0.01:
            raise ValueError(f"section weights must sum to 100 (got {total:g})")
        for s in self.sections:
            within = sum(c.weight for c in s.criteria)
            if abs(within - 100) > 0.01:
                raise ValueError(
                    f"criterion weights in section '{s.label}' must sum to 100 (got {within:g})"
                )
        return self


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
    # False until the reviewer has scored the call; their entries are padding.
    submitted: bool | None = None


class CalibrationSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    callId: str
    rubricId: str | None = None
    customerName: str
    target: list[ScorecardEntryResponse]
    reviewers: list[CalibrationReviewerResponse]
    status: CalibrationStatus
    createdAt: str


class CalibrationSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interactionId: str
    reviewerUserIds: list[str] = Field(min_length=1)


class CalibrationScoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterionId: str
    score: float = Field(ge=0, le=5)


class CalibrationScoresSubmitRequest(BaseModel):
    """An invited reviewer's score for every criterion of the session's rubric."""

    model_config = ConfigDict(extra="forbid")

    entries: list[CalibrationScoreInput] = Field(min_length=1)
    notes: str | None = None


class CalibrationSessionPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CalibrationStatus | None = None


# ── Evals / QA ───────────────────────────────────────────────────────────────


class QaCoverageResponse(BaseModel):
    windowDays: int
    completed: int
    scored: int
    coverage: float | None = None
    pendingReview: int
    criticalFails: int


class QaPackFlagResponse(BaseModel):
    flag: str
    severity: str | None = None
    createdAt: str | None = None


class QaPackDisclosureResponse(BaseModel):
    ruleId: str | None = None
    label: str | None = None
    read: bool
    readAtSec: int | None = None
    createdAt: str | None = None


class QaPackViolationResponse(BaseModel):
    id: str
    ruleId: str
    code: str | None = None
    label: str | None = None
    status: str | None = None
    description: str | None = None
    atSec: int | None = None


class QaPackAlertResponse(BaseModel):
    id: str
    kind: str | None = None
    severity: str | None = None
    reason: str | None = None
    createdAt: str | None = None
    acknowledgedAt: str | None = None


class QaPackSupervisorActionResponse(BaseModel):
    id: str
    action: str | None = None
    note: str | None = None
    audioJoined: bool
    createdAt: str | None = None


class QaPackLiveQaResponse(BaseModel):
    id: str
    verdict: str | None = None
    recommendedAction: str | None = None
    reason: str | None = None
    reasonCodes: list[Any]
    mode: str | None = None
    enacted: bool
    createdAt: str | None = None


class QaPackMediaResponse(BaseModel):
    id: str
    kind: str | None = None
    storageRef: str | None = None
    durationSec: int | None = None
    mimeType: str | None = None
    hash: str | None = None


class QaPackScorecardEntryResponse(BaseModel):
    criterionId: str
    aiSuggested: float
    score: float
    note: str | None = None


class QaPackScorecardResponse(BaseModel):
    id: str
    status: str | None = None
    totalScore: float | None = None
    band: str | None = None
    scoredAt: str | None = None
    entries: list[QaPackScorecardEntryResponse]


class QaInteractionPackResponse(BaseModel):
    """`agent_core.live_qa.pack.build_pack` — the tenant-scoped evidence pack."""

    interactionId: str
    customerId: str | None = None
    customerName: str | None = None
    accountId: str | None = None
    channel: str | None = None
    direction: str | None = None
    handlerKind: str | None = None
    status: str | None = None
    disposition: str | None = None
    startedAt: str | None = None
    endedAt: str | None = None
    durationSec: int | None = None
    summary: str | None = None
    redactionApplied: bool
    hash: str | None = None
    transcript: str
    flags: list[QaPackFlagResponse]
    disclosures: list[QaPackDisclosureResponse]
    violations: list[QaPackViolationResponse]
    alerts: list[QaPackAlertResponse]
    supervisorActions: list[QaPackSupervisorActionResponse]
    liveQa: list[QaPackLiveQaResponse]
    media: list[QaPackMediaResponse]
    scorecard: QaPackScorecardResponse | None = None


class QaDisagreementResponse(BaseModel):
    interactionId: str | None = None
    liveVerdict: str
    humanBand: str
    humanScore: float | None = None
    suggestedRubricTweak: str
    applied: bool


class QaDisagreementsResponse(BaseModel):
    applied: bool
    count: int
    items: list[QaDisagreementResponse]
