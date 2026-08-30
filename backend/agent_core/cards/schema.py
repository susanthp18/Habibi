"""Agent Card — the compile-time contract for one mouth.

Mouth columns (prompt, persona, voice, guardrails, flow) stay on
``prompt_versions``. The card names the bot, the tools it may call, the
handoffs it may make, and the engines it cannot unbind.
"""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1"

Channel = Literal["voice", "whatsapp", "sms", "internal", "mcp", "a2a"]
DataClass = Literal["pii", "money", "marketing", "internal"]
MemoryScope = Literal["turn", "call", "case", "customer"]
PinMode = Literal["exact", "caret"]
PolicyBinding = Literal["required"]
EvalRequire = Literal["regression", "redteam", "capability", "twin", "outbound"]
#: What may pull a canary automatically.
#:
#: The first three describe a canary that is *slow*; the last three describe one
#: that is *harmful*, and outbound needed its own because it fails differently.
#: An inbound bug annoys one caller who rang us. An outbound bug rings ten
#: thousand phones, and by the time a latency percentile has moved, the calls
#: have been made.
#:
#: This list carried only the first three while ``agent_core.canary`` evaluated
#: all six. Since the card is the only authoring path — publish reads
#: ``card.experiment.auto_rollback`` — the outbound three could not be requested
#: by any published version, so the watchdog branches that check them were
#: unreachable. G12 compounded it: ``compile._ROLLBACK_TRIGGERS`` restated the
#: same short list, so a canary whose only triggers were the outbound three
#: filtered to empty and failed with "canary split requires auto_rollback"
#: against a card that had named three valid ones.
#:
#: Both consumers now import from here so the three lists cannot drift again;
#: ``test_rollback_trigger_vocabulary_is_shared`` fails if one of them stops.
RollbackTrigger = Literal[
    "slo_miss",
    "live_qa_burn",
    "eval_fail",
    "abandon_rate",
    "third_party_leak",
    "optout_spike",
]

#: The same vocabulary as a set, for membership tests. Derived rather than
#: restated — a second literal list is a second thing to forget.
ROLLBACK_TRIGGERS: frozenset[str] = frozenset(get_args(RollbackTrigger))
HumanGateRequire = Literal["identity", "floor", "both"]

# Engines the author cannot unbind. Two of these are catalog tools the mouth
# may call; two are Python engines with no mouth tool (yet). All four must
# appear on ``tools.locked``.
LOCKED_POLICY_ENGINES: tuple[str, ...] = (
    "recommend_next_offer",
    "recommend_treatment",
    "evaluate_authority",
    "evaluate_live_qa",
)

# Subset that actually lives in agent_core.tools.CATALOG today.
LOCKED_MOUTH_TOOLS: frozenset[str] = frozenset(
    {"recommend_next_offer", "evaluate_authority"}
)

REQUIRED_POLICY_KEYS: tuple[str, ...] = (
    "reco",
    "treatment",
    "authority",
    "live_qa",
    "routing",
    "dnd",
)


class CardIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_id: str
    slug: str
    display_name: str
    purpose: str = ""
    owner_user_id: str | None = None
    channels: list[Channel] = Field(default_factory=lambda: ["voice", "whatsapp"])
    data_class: list[DataClass] = Field(default_factory=lambda: ["pii", "money"])
    regulator_tags: list[str] = Field(default_factory=list)


class CardMouthRef(BaseModel):
    """Pointers, not copies — the columns on prompt_versions are canonical."""

    model_config = ConfigDict(extra="forbid")

    flow_ref: str | None = None
    languages: list[str] = Field(default_factory=lambda: ["English", "Hindi"])


class CardSkillRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    version: str = "1"
    pin: PinMode = "exact"


class CardTools(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include: list[str] = Field(default_factory=list)
    locked: list[str] = Field(default_factory=lambda: list(LOCKED_POLICY_ENGINES))
    max_voice_tools: int = 12


class CardHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_bot_id: str
    payload_schema: dict[str, Any] = Field(default_factory=dict)
    when: str = ""


class CardConnector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_id: str
    allow_prefixes: list[str] = Field(default_factory=list)


class PolicyBindings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reco: PolicyBinding = "required"
    treatment: PolicyBinding = "required"
    authority: PolicyBinding = "required"
    live_qa: PolicyBinding = "required"
    routing: PolicyBinding = "required"
    dnd: PolicyBinding = "required"


class Compaction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_last_n: int = 8
    summarize_over_budget: bool = True


class CardMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scopes: list[MemoryScope] = Field(default_factory=lambda: ["turn", "call"])
    compaction: Compaction = Field(default_factory=Compaction)


class HumanGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    require: HumanGateRequire = "identity"


class CardEval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_id: str | None = None
    require: list[EvalRequire] = Field(default_factory=lambda: ["regression", "redteam"])


# ---------------------------------------------------------------------------
# Outbound — direction, missions, cadence and what happens after the audio stops
#
# Why this lives on the card rather than in a campaigns screen: `prompt_versions`
# publishes prompt, persona, voice, guardrails, flow and this card atomically as
# one row, and `bot_deployments` keeps exactly one active version per bot per
# environment. A cadence configured elsewhere could change without a version
# bump, which means the sentence the agent said and the schedule that produced
# the call would have separate audit trails. A regulator asking "why did this
# borrower get four calls in three days in March" must get one answer with one
# version number.
# ---------------------------------------------------------------------------

Direction = Literal["inbound", "outbound", "both"]

#: Mirrors ``flow_graph.OBJECTIVES``. The graph owns the vocabulary because the
#: graph is what has to contain a matching entry node; this restates it as a
#: Literal so a card with a typo fails at parse rather than at dial time.
Objective = Literal[
    "inbound",
    "pre_due_reminder",
    "bounce_cure",
    "dpd_reminder",
    "broken_ptp_chase",
    "hardship_intake",
    "mandate_reregistration",
    "document_chase",
    "callback_honour",
    "welcome_onboarding",
    "retention_save",
    "cross_sell",
    "manual_outbound",
]

VoicemailMode = Literal["always", "never", "first_attempt_only", "engine"]
TimeOfDay = Literal["engine", "fixed", "spread"]
PoolKind = Literal["service_1600", "promotional", "general"]


class VoicemailPolicy(BaseModel):
    """What to do when a machine answers. Silence is a decision too.

    ``include_grievance_contact`` is not a nicety. A voicemail is a recovery
    communication, and RBI para 100AA requires the grievance officer's details
    in all of them — so a message that only says "please call us back" is a
    communication made without a disclosure that was owed.
    """

    model_config = ConfigDict(extra="forbid")

    leave: VoicemailMode = "first_attempt_only"
    max_sec: int = Field(default=25, ge=5, le=60)
    include_grievance_contact: bool = True


class CardObjective(BaseModel):
    """One mission this agent can be sent on."""

    model_config = ConfigDict(extra="forbid")

    key: Objective
    #: Node key in ``prompt_versions.flow`` whose ``entryFor`` claims this
    #: mission. Compile gate G-OB2 checks the two agree.
    entry_node: str = ""
    #: Outcome codes from the Closer's taxonomy that close the case.
    success: list[str] = Field(default_factory=list)
    partial: list[str] = Field(default_factory=list)
    max_duration_sec: int = Field(default=240, ge=30, le=1800)
    #: Empty means no product may be mentioned on this mission at all. That is
    #: the safe default rather than an omission: a servicing call is not a sales
    #: call, and the borrower did not ask to be sold to.
    allowed_offers: list[str] = Field(default_factory=list)
    #: Named cap set in agent_core.authority. A broken-PTP chase may concede
    #: more than a pre-due nudge, and that is an authored difference.
    authority_profile: str | None = None
    voicemail: VoicemailPolicy = Field(default_factory=VoicemailPolicy)
    cadence: str = "default"


class CardCadence(BaseModel):
    """When to try again. Mechanical, and never a decision about the action.

    Cadence may retry the *same* action. Only the treatment engine may change
    the action — that boundary is what stops a dialler quietly inventing an
    escalation ladder of its own.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = "default"
    max_attempts: int = Field(default=3, ge=1, le=10)
    #: Per borrower per day for this mission. Bounded again at runtime by
    #: contact_policy's own cap, which a card can only ever lower.
    per_day: int = Field(default=1, ge=1, le=5)
    #: Hours to wait before attempt 2, 3, ... A shorter list repeats its last
    #: value rather than falling off the end.
    backoff_hours: list[int] = Field(default_factory=lambda: [4, 24, 72])
    retry_on: list[str] = Field(
        default_factory=lambda: [
            "no_answer",
            "busy",
            "voicemail_left",
            "voicemail_skipped",
        ]
    )
    #: Terminal for the case whatever the attempt count says.
    stop_on: list[str] = Field(
        default_factory=lambda: [
            "ptp_captured",
            "ptp_recommitted",
            "paid_in_call",
            "dispute_raised",
            "opt_out_requested",
            "wrong_number",
            "deceased",
        ]
    )
    #: bot_id on the handoff allowlist, or "human". Where the case goes when the
    #: attempts run out.
    escalate_to: str | None = None
    time_of_day: TimeOfDay = "engine"


class PostCallRule(BaseModel):
    """One outcome code and what it triggers, versioned with the agent."""

    model_config = ConfigDict(extra="forbid")

    when: str
    do: list[str] = Field(default_factory=list)


class CardPostCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on_outcome: list[PostCallRule] = Field(default_factory=list)
    #: Send the borrower a written record of what was agreed.
    written_followup: bool = True
    #: Honour promises the agent made on the call.
    obligations: bool = True
    qa: Literal["always", "sampled", "never"] = "always"


class CardOutbound(BaseModel):
    """Everything about being the one who dialled.

    ``direction`` defaults to ``inbound`` so every card that exists today keeps
    exactly the behaviour it has: no objectives, no cadence, no dialling.
    """

    model_config = ConfigDict(extra="forbid")

    direction: Direction = "inbound"
    objectives: list[CardObjective] = Field(default_factory=list)
    cadences: list[CardCadence] = Field(default_factory=list)
    post_call: CardPostCall = Field(default_factory=CardPostCall)
    #: Which caller-ID pool this agent dials from. A service-only pool
    #: (TRAI 1600 series) forbids promotional content — compile gate G-OB4.
    number_pool: str | None = None
    pool_kind: PoolKind = "general"
    #: Slots reserved out of the outbound fleet gate, so a cross-sell campaign
    #: cannot starve the bounce-cure queue. 0 means "share the general pool".
    concurrency_share: int = Field(default=0, ge=0, le=100)
    #: Ask the carrier for an answering-machine verdict as a second signal
    #: alongside Pipecat's in-band detector.
    carrier_amd: bool = False
    #: Drive DTMF through a workplace switchboard to reach a human.
    ivr_traversal: bool = False
    ivr_max_sec: int = Field(default=90, ge=15, le=300)

    def objective(self, key: str) -> CardObjective | None:
        return next((o for o in self.objectives if o.key == key), None)

    def cadence_for(self, key: str) -> CardCadence:
        """The cadence an objective names, or a conservative default.

        Never None: a missing cadence must not read as "retry forever". G-OB8
        stops a card being published that names a cadence it does not define,
        so this fallback only ever covers the un-authored case.
        """
        objective = self.objective(key)
        name = objective.cadence if objective else "default"
        return next((c for c in self.cadences if c.name == name), CardCadence())

    @property
    def dials(self) -> bool:
        return self.direction in ("outbound", "both")


class CardExperiment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    traffic_pct: int = Field(default=100, ge=0, le=100)
    shadow: bool = False
    auto_rollback: list[RollbackTrigger] = Field(default_factory=list)


class CardA2A(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expose: bool = False
    skill_ids: list[str] = Field(default_factory=list)


class AgentCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"] = SCHEMA_VERSION
    identity: CardIdentity
    mouth: CardMouthRef = Field(default_factory=CardMouthRef)
    skills: list[CardSkillRef] = Field(default_factory=list)
    tools: CardTools = Field(default_factory=CardTools)
    handoffs: list[CardHandoff] = Field(default_factory=list)
    connectors: list[CardConnector] = Field(default_factory=list)
    policy_bindings: PolicyBindings = Field(default_factory=PolicyBindings)
    memory: CardMemory = Field(default_factory=CardMemory)
    outbound: CardOutbound = Field(default_factory=CardOutbound)
    human_gates: list[HumanGate] = Field(default_factory=list)
    eval: CardEval = Field(default_factory=CardEval)
    experiment: CardExperiment = Field(default_factory=CardExperiment)
    a2a: CardA2A | None = None

    def effective_include(self) -> list[str]:
        """Union of include + locked mouth tools, de-duplicated, stable order."""
        seen: set[str] = set()
        out: list[str] = []
        for name in [*self.tools.include, *self.tools.locked]:
            if name in seen:
                continue
            seen.add(name)
            out.append(name)
        return out

    def handoff_targets(self) -> frozenset[str]:
        return frozenset(h.to_bot_id for h in self.handoffs)


def parse_card(raw: Any) -> AgentCard:
    """Empty / missing card is not valid — callers that want legacy skip this."""
    if not isinstance(raw, dict) or not raw:
        raise ValueError("agent_card_empty")
    return AgentCard.model_validate(raw)


def is_authored(raw: Any) -> bool:
    """Non-empty JSON that claims to be a card. Invalid JSON still counts as authored
    so the compiler can fail G0 rather than silently shipping it."""
    return isinstance(raw, dict) and bool(raw)
