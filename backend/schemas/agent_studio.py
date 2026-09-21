"""Agent Studio: cards, skills, connectors, roles, experiments.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

# The authored flow graph is a domain model, not a transport shape — it is
# shared verbatim by the API, the validator and the voice runtime, so it is
# defined once in flow_graph and reused here rather than restated.
from agent_core.fleet.schema import CompiledBundle
from agent_core.cards.defaults import COLLECTIONS_BOT_ID
from flow_graph import FlowGraph, FlowIssue, FlowValidation  # noqa: F401

class FlowToolResponse(BaseModel):
    """One entry in the tool palette the Studio offers.

    Serves three pickers — flow node tools, the card's Tool Grant, and a skill
    pack's ``allowed-tools`` — so it carries every channel and each consumer
    filters. See ``flow_graph.tool_catalog``.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    description: str
    #: True when the tool moves the conversation on its own. Pairing one with
    #: graph edges on the same node gives the model two ways out of it.
    transitions: bool
    #: True when the tool is a locked policy engine the author cannot unbind.
    locked: bool = False
    #: True when the runtime keeps this tool regardless of what the card
    #: granted. Adding one to ``tools.include`` changes nothing at best, and for
    #: the flow-control verbs — which are not catalog specs — fails G4 at
    #: Publish after the tab showed no error.
    alwaysOn: bool = False
    #: Channels this tool renders on, from its ``ToolSpec``. Flow-control verbs
    #: exist only inside ``voice.tools`` and report ``["voice"]``.
    channels: list[str] = Field(default_factory=lambda: ["voice"])
    #: ``catalog`` is grantable from the Tools tab. ``flow_control`` is a
    #: zero-argument voice transition and must not be added as a catalog grant.
    kind: Literal["catalog", "flow_control"] = "catalog"


# ---------------------------------------------------------------------------
# Persona & Prompt Studio (PS-1 reads — Habibi prompt-studio-seed.ts shapes)
# ---------------------------------------------------------------------------

PromptVersionStatus = Literal["draft", "published", "archived"]


BotDeploymentEnvironment = Literal["sandbox", "production"]


BotDeploymentStatus = Literal["active", "rolled_back", "retired"]


class PersonaTraits(BaseModel):
    """Slider positions, 0..100. The sliders are bounded in the browser; the
    wire was not, so a hand-written PATCH could store 900 and the prompt
    renderer's "warm" / "direct" thresholds read nonsense."""

    model_config = ConfigDict(extra="forbid")

    empathy: int = Field(ge=0, le=100)
    firmness: int = Field(ge=0, le=100)
    formality: int = Field(ge=0, le=100)
    verbosity: int = Field(ge=0, le=100)
    upsell: int = Field(ge=0, le=100)


class PersonaState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    traits: PersonaTraits
    language: str
    fallbackLanguages: list[str]

    @field_validator("language")
    @classmethod
    def _known_language(cls, value: str) -> str:
        # The traits are bounded; the language was any string, and an unknown
        # one reached the recogniser as a locale nothing could bind.
        from agent_core.languages import tag_for

        if tag_for(value) is None:
            raise ValueError(f"unknown language: {value!r}")
        return value


class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voiceId: str
    speed: float
    pitch: int
    warmth: int
    pauseMs: int
    sampleText: str
    # Prompt Studio / Sandbox persist these alongside the studio voiceId.
    azureVoiceName: str | None = None
    style: str | None = None
    #: The selected model's own controls, keyed by ``provider_models.params_schema``.
    #:
    #: The five prosody fields above are Azure/SSML-shaped, because Azure was
    #: the only provider when this model was written. They are not a superset of
    #: anything — Fish S2.1 Pro has a temperature and no pitch, Deepgram Aura-2
    #: has almost no prosody — so every other vendor's controls need a slot, and
    #: this is it. ``db._prompt_voice`` sanitises it and
    #: ``agent_core.tuning.apply_voice_config_overlay`` folds it into
    #: ``AgentTuning.tts.params``, which is what reaches the bound provider.
    #:
    #: Untyped by key on purpose: the authority on which keys a model accepts is
    #: that model's own Pipecat ``Settings`` class, and
    #: ``providers.factory.build`` filters against it. A second opinion here
    #: would go stale the moment a vendor adds a knob.
    params: dict[str, Any] = Field(default_factory=dict)


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
    # Authored conversation graph (backend/flow_graph.py). Empty on every
    # version created before flow authoring existed.
    flow: FlowGraph = Field(default_factory=FlowGraph)
    #: True when the stored graph could not be parsed and `flow` above is the
    #: empty sentinel standing in for it.
    #:
    #: Without this, "this version never authored a flow" and "this version's
    #: graph is corrupt and we are hiding it" are the same response. The row
    #: mapper degrades rather than raising because the alternative is a 500 for
    #: every version of the bot; this is what stops that degradation from being
    #: silent.
    flowUnreadable: bool = False
    botId: str = COLLECTIONS_BOT_ID
    agentCard: dict[str, Any] = Field(default_factory=dict)
    compiled: CompiledBundle | None = None
    #: Present on a publish response: what every door that merges this card
    #: did with the news (a new deployment, or a named reason it kept the old).
    fleetRebuilds: list[FleetRebuildResponse] | None = None


class FleetRebuildResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doorBotId: str
    rebuilt: bool
    reason: str | None = None
    deploymentId: str | None = None
    previousDeploymentId: str | None = None
    bundleHash: str | None = None


class EffectiveContractResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["published", "preview"]
    botId: str
    promptVersionId: str | None = None
    compiled: CompiledBundle
    gates: list[dict[str, Any]] = Field(default_factory=list)


class PersonaPresetResponse(BaseModel):
    """Mirrors Habibi PersonaPreset."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    description: str
    traits: PersonaTraits
    promptTemplate: str


class BotDeploymentResponse(BaseModel):
    """Runtime release unit — authoritative for what runs (see PROMPT_STUDIO_plan §6.4)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    botId: str
    promptVersionId: str
    kbSnapshotId: str | None
    ttsVoiceId: str | None  # Azure Speech ShortName (not a legacy studio alias id)
    environment: BotDeploymentEnvironment
    status: BotDeploymentStatus
    publishedBy: str | None
    publishedAt: str | None
    rollbackDeploymentId: str | None
    voiceConfig: dict[str, Any]
    tuning: dict[str, Any] = Field(default_factory=dict)
    trafficPct: int = 100
    shadow: bool = False
    evalReportId: str | None = None
    #: The grant frozen at publish (`agent_core.tools.grant`) and the compiled
    #: bundle it came from. The row carried both; the model forbade them, so
    #: every `/bot-deployments/active` read was a 500.
    frozenTools: list[str] | None = None
    bundleHash: str | None = None


class PromptVersionCreateRequest(BaseModel):
    """Create a draft prompt version (PS-2)."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    prompt: str
    persona: PersonaState
    voice: VoiceConfig
    guardrails: Guardrails
    summary: str = ""
    flow: FlowGraph | None = None
    botId: str | None = None
    agentCard: dict[str, Any] | None = None


class PromptVersionPatchRequest(BaseModel):
    """Update a draft only — 409 if not draft (PS-2)."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    prompt: str | None = None
    persona: PersonaState | None = None
    voice: VoiceConfig | None = None
    guardrails: Guardrails | None = None
    summary: str | None = None
    flow: FlowGraph | None = None
    #: Deliberately replace a stored graph that does not parse.
    #:
    #: An unreadable row is served as the empty sentinel plus ``flowUnreadable``
    #: so the rest of the bot stays reachable. Without this flag the first
    #: autosave triggered by any edit — a keystroke in the prompt — wrote that
    #: sentinel back over the column, and the red panel telling the operator
    #: their graph is corrupt was replaced by "No authored flow" before they
    #: could act. Replacing it is a decision; "I typed in another tab" is not.
    replaceUnreadable: bool = False
    agentCard: dict[str, Any] | None = None


class PromptVersionPublishRequest(BaseModel):
    """Promote a draft + create active prod deployment in one transaction."""

    model_config = ConfigDict(extra="forbid")

    #: Which draft to publish, for the by-bot endpoint that does not name one in
    #: its path. Ignored by ``POST /prompt-versions/{id}/publish``, which has the
    #: id already.
    #:
    #: The by-bot endpoint used to pick "the first draft in the newest twenty
    #: versions" with no way for the caller to say which one it meant — so a bot
    #: with two open drafts published whichever one sorted first, and the studio,
    #: which tracks a specific draftId, had no way to express its choice.
    versionId: str | None = None
    summary: str = ""
    kbSnapshotId: str | None = None
    #: 1..100. It used to be an unbounded int -- 0 opened an experiment that
    #: served nobody, 250 a canary at "250%" -- and `shadow` rode beside it
    #: for a runtime path that does not exist (the card retired it first).
    trafficPct: int | None = Field(default=None, ge=1, le=100)
    autoRollback: list[str] | None = None


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
    """Count prompt tokens with the same tiktoken encoding as chat/KB.

    ``guardrails`` and ``persona`` are optional, and supplying them is what
    makes the answer describe the call rather than the textarea: the system
    message the model receives is the authored prompt *plus* the generated
    guardrail rules, persona directions, local time and the voice naturalness
    overlay. Counting only ``prompt`` understated a live card by about 7x.
    """

    model_config = ConfigDict(extra="forbid")

    prompt: str
    guardrails: Guardrails | None = None
    persona: PersonaState | None = None
    channel: Literal["voice", "text"] = "voice"
    #: The card whose skills ride on the system message: both runtimes append
    #: the skill catalog prefix, so an assembled count without it understated
    #: every card that attaches a pack.
    botId: str | None = None


class PromptTokenEstimateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The authored text alone — what the editor holds.
    tokens: int
    encoding: str
    usdPer1M: float
    #: Input cost of ``tokens`` alone. Kept as the authored figure so the two
    #: numbers on screen are comparable; ``assembledCostUsd`` is the one to
    #: budget with.
    costUsd: float
    source: Literal["tiktoken", "heuristic"] = "tiktoken"
    #: The whole system message as assembled for ``channel``. ``None`` when the
    #: caller supplied no guardrails, because the assembly would then be a
    #: guess presented as a measurement.
    assembledTokens: int | None = None
    assembledCostUsd: float | None = None


# ---------------------------------------------------------------------------
# Agent Studio — WP-042. Field names match the dicts already on the wire.
# extra="forbid" so an undeclared key 500s rather than silently disappearing.
# ---------------------------------------------------------------------------

AgentStudioReachability = Literal["entry", "handoff", "direct", "unreachable", "archived"]


AgentStudioDeploymentStatus = Literal["live", "published", "draft", "empty"]


AgentStudioCardSource = Literal["draft", "published", "default", "scaffold"]


class AgentStudioCardResponse(BaseModel):
    """Fleet index / single-card row. Mirrors Habibi AgentCardSummary."""

    model_config = ConfigDict(extra="forbid")

    botId: str
    name: str
    version: str
    slug: str
    purpose: str
    channels: list[str]
    skills: list[str]
    toolCount: int
    evalStatus: str
    trafficPct: int | None
    deploymentStatus: AgentStudioDeploymentStatus
    lastPublish: str | None
    promptVersionId: str | None
    draftVersionId: str | None
    hasDraft: bool
    cardSource: AgentStudioCardSource
    entryBotId: str
    #: The enabled entry bindings that land on this card -- "answers +1937…"
    #: -- read from the table, not the env.
    entryBindings: list["EntryBindingResponse"] = []
    #: Whether archiving is refused because inbound traffic lands here -- the
    #: env default or any enabled binding (``routing.entry_card_ids``). Sent,
    #: not derived: ``entryBotId`` is a different card once the door routes
    #: voice elsewhere.
    takesInbound: bool
    #: The reachable cards whose handoff allowlist names this one, sorted.
    #: Empty unless ``reachability`` is ``handoff``.
    handoffFrom: list[str]
    reachability: AgentStudioReachability
    archivedAt: str | None
    isFirstParty: bool
    agentCard: dict[str, Any]
    publishedCard: dict[str, Any]


class EntryBindingResponse(BaseModel):
    """One row of `entry_bindings`: which card answers `channel` at `address`
    (`None` = the channel default)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    channel: str
    address: str | None = None
    bot_id: str
    enabled: bool = True
    note: str = ""
    updated_at: str | None = None


class PolicyEngineResponse(BaseModel):
    """One policy engine and the mode it runs in on this stack."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    tool: str | None = None
    #: off | shadow | live, or "always" for an engine with no mode knob.
    mode: str
    #: The env var that sets it, for the operator who wants to change it.
    source: str | None = None


class EntryBindingUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    channel: str
    botId: str = Field(validation_alias=AliasChoices("botId", "bot_id"))
    address: str | None = None
    note: str = ""
    enabled: bool = True
    #: GET-row keys. Ignored on write so a round-trip of EntryBindingResponse
    #: does not 422 extra_forbidden.
    id: str | None = None
    updated_at: str | None = None


class AgentStudioTemplateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    sourceBotId: str
    purpose: str


class AgentStudioArchiveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    botId: str
    archived: bool


class AgentStudioChangeLogRolloutResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trafficPct: int
    #: Retired. Entries written before 2026-09-12 carry it; nothing writes it.
    shadow: bool = False
    autoRollback: list[str]


class AgentStudioChangeLogEntryResponse(BaseModel):
    """One audit_log row plus the payload spread onto it.

    Action-specific keys (hashes, rollout, archivedAt, …) are optional because
    publish / rollback / archive / restore do not share a payload. Routes that
    return this model must set ``response_model_exclude_unset=True`` so those
    absences stay absences rather than becoming null.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    actorUserId: str | None
    action: str
    botId: str | None
    at: str | None
    seq: int | None = None
    entryHash: str | None = None
    prevHash: str | None = None
    versionLabel: str | None = None
    previousVersionLabel: str | None = None
    previousVersionId: str | None = None
    versionId: str | None = None
    deploymentId: str | None = None
    summary: str | None = None
    changed: list[str] | None = None
    rollout: AgentStudioChangeLogRolloutResponse | None = None
    gates: dict[str, str] | None = None
    hashes: dict[str, str] | None = None
    replacedDeploymentId: str | None = None
    retiredDeploymentId: str | None = None
    archivedAt: str | None = None
    # agent.role_grants
    roleId: str | None = None
    permissionIds: list[str] | None = None
    # agent.experiment_rollback
    experimentId: str | None = None
    reason: str | None = None
    baselineRestored: bool | None = None
    trafficPct: int | None = None
    shadow: bool | None = None
    autoRollback: list[str] | None = None
    # agent.entry_binding
    bindingId: str | None = None
    channel: str | None = None
    address: str | None = None
    enabled: bool | None = None
    removed: bool | None = None
    # agent.platform_sync
    promptVersionId: str | None = None
    filled: list[str] | None = None
    moved: list[str] | None = None
    # agent.fleet_rebuild
    previousDeploymentId: str | None = None
    bundleHash: str | None = None
    memberBotId: str | None = None
    memberVersionId: str | None = None
    # agent.connector
    connectorId: str | None = None
    slug: str | None = None
    kind: str | None = None
    url: str | None = None
    status: str | None = None
    allowPrefixes: list[str] | None = None
    dataClass: list[str] | None = None
    allowedEnv: str | None = None
    # agent.mcp_key
    keyId: str | None = None
    name: str | None = None
    scopes: list[str] | None = None
    prefix: str | None = None
    revoked: bool | None = None
    rotatedFrom: str | None = None


class AgentStudioChainVerdictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    checked: int
    brokenAt: str | None
    reason: str | None


class AgentStudioChangeLogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[AgentStudioChangeLogEntryResponse]
    chain: AgentStudioChainVerdictResponse
    #: Entries matching the filter before `limit`, so the window says it is one.
    total: int = 0


class AgentStudioGraphNodeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    reachability: AgentStudioReachability
    deploymentStatus: AgentStudioDeploymentStatus


class AgentStudioGraphEdgeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str | None = None


class AgentStudioGraphResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    botId: str
    nodes: list[AgentStudioGraphNodeResponse]
    edges: list[AgentStudioGraphEdgeResponse]


class AgentStudioSkillDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    id: str
    slug: str


class AgentStudioScriptNameResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


class AgentStudioScriptRunResponse(BaseModel):
    """Union of the allowlisted script returns plus the unknown-script error.

    Sparse by construction: ``emi_remaining`` and ``promise_date_in_window``
    do not share keys. Routes must set ``response_model_exclude_unset=True``.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    error: str | None = None
    name: str | None = None
    allowed: list[str] | None = None
    remaining_emis: int | None = None
    outstanding: float | None = None
    installment_amount: float | None = None
    in_window: bool | None = None
    outside: bool | None = None
    promise_date: str | None = None
    preferred_window: Any | None = None


# ── Agent Studio: request bodies ─────────────────────────────────────────────


class AgentCardCloneRequest(BaseModel):
    """Either a template or a source card; `clone_card` decides which wins."""

    model_config = ConfigDict(extra="forbid")

    templateId: str | None = Field(default=None, validation_alias=AliasChoices("templateId", "template_id"))
    sourceBotId: str | None = Field(default=None, validation_alias=AliasChoices("sourceBotId", "source_bot_id"))
    name: str | None = None


class AgentCardPatchRequest(BaseModel):
    """Studio card autosave. The card is stored as authored — the compiler's G0
    is its validator, so an in-progress card that does not yet parse is still
    saved and reported, not refused (same contract as PromptVersionPatchRequest)."""

    model_config = ConfigDict(extra="forbid")

    agentCard: dict[str, Any] | None = Field(default=None, validation_alias=AliasChoices("agentCard", "agent_card"))
    flow: FlowGraph | None = None


class AgentCardCompileRequest(BaseModel):
    """Compile preview of what Publish will ship. `agentCard` and `flow` are the
    editor's unsaved JSON — the gates (G0 card, G1 flow) are what judge them, so
    they are open documents here rather than the strict domain models; a graph
    that does not parse must reach the compiler to be reported as such."""

    model_config = ConfigDict(extra="forbid")

    agentCard: dict[str, Any] | None = Field(default=None, validation_alias=AliasChoices("agentCard", "agent_card"))
    flow: dict[str, Any] | None = None
    trafficPct: int | float | None = Field(default=None, validation_alias=AliasChoices("trafficPct", "traffic_pct"))
    autoRollback: list[str] | None = Field(default=None, validation_alias=AliasChoices("autoRollback", "auto_rollback"))
    #: The mouth columns the editor holds unsaved between autosaves (G15).
    voice: dict[str, Any] | None = None
    persona: dict[str, Any] | None = None


class SkillCreateRequest(BaseModel):
    """`agent_core.skills.persist.create_draft_skill`. Origin is not a client
    choice: every draft created here is a tenant skill."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(validation_alias=AliasChoices("slug", "name"))
    description: str | None = None
    allowedTools: list[str] | None = Field(default=None, validation_alias=AliasChoices("allowedTools", "allowed_tools"))
    body: str | None = None
    frontmatter: dict[str, Any] | None = None


class SkillPatchRequest(BaseModel):
    """`patch_skill` distinguishes absent from null — routes dump exclude_unset."""

    model_config = ConfigDict(extra="forbid")

    slug: str | None = None
    description: str | None = None
    allowedTools: list[str] | None = Field(default=None, validation_alias=AliasChoices("allowedTools", "allowed_tools"))
    body: str | None = None
    frontmatter: dict[str, Any] | None = None
    version: str | None = None


class SkillRevertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versionId: str | None = Field(default=None, validation_alias=AliasChoices("versionId", "version_id"))


class SkillCloneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str | None = None


class SkillScriptRunRequest(BaseModel):
    """`payload` must be an object: the console says so, and `[1, 2]` used to
    run the script against nothing and return a verdict that read as computed."""

    model_config = ConfigDict(extra="forbid")

    name: str
    payload: dict[str, Any] = Field(default_factory=dict)


class RolePermissionsPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permissionIds: list[str] = Field(default_factory=list, validation_alias=AliasChoices("permissionIds", "permission_ids"))


class ExperimentRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = "manual"


# ── Agent Studio: roles + canary responses ───────────────────────────────────


class RolePermissionResponse(BaseModel):
    id: str
    module: str
    action: str
    description: str


class RoleGrantResponse(BaseModel):
    role_id: str
    role: str
    permission_id: str


class RoleResponse(BaseModel):
    id: str
    name: str
    permissionIds: list[str]


class RolesCatalogResponse(BaseModel):
    """Roles page. `grants` is the resolved set the enforcer will honour."""

    permissions: list[RolePermissionResponse]
    agentPublishRoles: list[str]
    grants: list[RoleGrantResponse]
    roles: list[RoleResponse]


class DeploymentExperimentResponse(BaseModel):
    """`agent_core.canary.list_experiments` — camelCase projection of the row."""

    id: str
    botId: str
    environment: str | None = None
    canaryDeploymentId: str | None = None
    baselineDeploymentId: str | None = None
    trafficPct: int
    shadow: bool
    autoRollback: list[str]
    status: str | None = None
    rollbackReason: str | None = None


class DeploymentExperimentRollbackResponse(DeploymentExperimentResponse):
    """Same camelCase projection as ``list_experiments``, plus which of the two
    rollback outcomes happened. The Ship tab reads ``baselineRestored``."""

    baselineRestored: bool
