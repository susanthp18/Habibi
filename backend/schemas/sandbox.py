"""The call sandbox and the simulation twin.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

# The authored flow graph is a domain model, not a transport shape — it is
# shared verbatim by the API, the validator and the voice runtime, so it is
# defined once in flow_graph and reused here rather than restated.
from flow_graph import FlowGraph, FlowIssue, FlowValidation  # noqa: F401

from schemas.agent_studio import (
    PromptVersionResponse,
)

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
    """The scenario persona, as the renderer and the tool loop see it.

    Every field below was display-only until ``customer_id`` was added, which is
    why ``_sandbox_tools_enabled``'s ``ctx.get("customerId")`` branch could never
    be true: under ``extra="forbid"`` there was no field that could carry one, so
    a scenario could describe a borrower the tools had no way to look up.

    A real ``customers`` id makes the tools read that borrower's real rows — the
    honest rehearsal, and the reason this is an explicit per-scenario opt-in
    rather than a default. Leave it unset and the run is prompt-only, exactly as
    before.
    """

    model_config = ConfigDict(extra="forbid")

    customer_id: str | None = None
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
    #: Customer turns the rehearsal will run before stopping for cost. Not
    #: the card's `maxTurns`, which is judged as a guardrail like live.
    turnBudget: int | None = None


class SandboxTurnCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    history: list[SandboxHistoryItem] = []
    context: SandboxContext | None = None
    topK: int = Field(default=4, ge=1, le=20)
    #: Which step of the authored flow this turn continues. Absent means "start
    #: the graph": the first turn of a run, or a card with no authored flow.
    #: Round-tripped rather than stored because a sandbox run is a rehearsal the
    #: operator can rewind by re-posting an earlier node — the server keeps the
    #: transcript authoritative and lets the client own the cursor.
    nodeKey: str | None = None
    # The studio always posts this (Habibi/src/api/sandbox.ts) and
    # sandbox_runtime pins the active skill from it. Omitted here, every
    # customer turn was rejected 422 by extra="forbid" before the handler ran.
    skillSlug: str | None = None


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
    # Tool-loop trace from sandbox_runtime (may be empty).
    toolCalls: list[dict[str, Any]] = Field(default_factory=list)


class SandboxTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runId: str
    promptVersionId: str
    compiledBundleHash: str | None = None
    #: ``walked`` means the authored graph decided which tools this turn offered.
    #: The older ``validated_not_executed_in_text_rehearsal`` is kept for a card
    #: whose flow will not parse — the compiler passed it, this runtime could not
    #: walk it, and saying so is the point of the lozenge.
    flowStatus: Literal[
        "walked", "validated_not_executed_in_text_rehearsal", "not_authored"
    ] | None = None
    #: The step the run is on after this turn, to post back as ``nodeKey``.
    nodeKey: str | None = None
    #: What the graph offered the model on this turn — the node's granted tools
    #: plus its generated transitions. This is the thing "Test in Sandbox" could
    #: not show before: the script's effect on the grant, step by step.
    offeredTools: list[str] | None = None
    customerTurn: SandboxCustomerTurn
    botTurn: SandboxBotTurn


# ── Sandbox: payment events, twins, tuning presets ───────────────────────────


class SandboxPaymentEventRequest(BaseModel):
    """`payment_events.parse_payload` reads both spellings; `source` and
    `sourceRef` are defaulted by the route when absent."""

    model_config = ConfigDict(extra="forbid")

    accountId: str | None = Field(default=None, validation_alias=AliasChoices("accountId", "account_id"))
    customerId: str | None = Field(default=None, validation_alias=AliasChoices("customerId", "customer_id"))
    source: str | None = None
    sourceRef: str | None = Field(default=None, validation_alias=AliasChoices("sourceRef", "source_ref"))
    amount: float | str | None = None
    occurredAt: str | None = Field(default=None, validation_alias=AliasChoices("occurredAt", "occurred_at"))
    reason: str | None = None
    emiId: str | None = Field(default=None, validation_alias=AliasChoices("emiId", "emi_id"))
    bounceFee: float | str | None = Field(default=None, validation_alias=AliasChoices("bounceFee", "bounce_fee"))
    nextCreditAt: str | None = Field(default=None, validation_alias=AliasChoices("nextCreditAt", "next_credit_at"))


class SimulationTwinResponse(BaseModel):
    id: str
    name: str
    state: dict[str, Any]
    createdAt: str | None = None
    updatedAt: str | None = None


class TwinRunRequest(BaseModel):
    """State overrides merged onto the twin's stored state before the replay."""

    model_config = ConfigDict(extra="forbid")

    state: dict[str, Any] | None = None


class TwinQueuesResponse(BaseModel):
    whatsapp: list[dict[str, Any]]
    sms: list[dict[str, Any]]
    voice: list[dict[str, Any]]


class TwinOutcomeResponse(BaseModel):
    queues: TwinQueuesResponse
    ledger: dict[str, Any]
    dialled: bool
    doubleSms: bool


class TwinGraderResponse(BaseModel):
    passed: bool
    bounce_ladder: dict[str, Any]
    no_dial: dict[str, Any]


class TwinRunResponse(BaseModel):
    id: str
    twinId: str
    scenario: str
    status: str
    outcome: TwinOutcomeResponse
    grader: TwinGraderResponse


class TuningPresetResponse(BaseModel):
    id: str
    label: str
    tuning: dict[str, Any]
