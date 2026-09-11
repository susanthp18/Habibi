"""Agent Card — the compile-time contract for one mouth.

Mouth columns (prompt, persona, voice, guardrails, flow) stay on
``prompt_versions``. The card names the bot, the tools it may call, the
handoffs it may make, and the engines it cannot unbind.
"""

from __future__ import annotations

import copy
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1"

Channel = Literal["voice", "whatsapp", "sms", "internal", "mcp", "a2a"]
PinMode = Literal["exact", "caret"]
HandoffCarry = Literal["brief", "full"]
#: No ``capability``. It was offered as a publish requirement and read by
#: nothing: ``_eval_gate`` matches a requirement against a *gate name*, and no
#: gate is called ``capability`` — so ticking it changed no publish outcome. No
#: stored card carried it (18/18 rows are ``["regression", "redteam"]``), so it
#: needs no tolerated-drop path; an invented value must still fail loudly.
EvalRequire = Literal["regression", "redteam", "twin", "outbound"]
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

#: The engines the mouth cannot unbind. Each is code with a log; the mode it
#: runs in is env-driven and reported live, not authored on a card.
POLICY_ENGINES: tuple[tuple[str, str, str | None], ...] = (
    ("reco", "Recommend next offer", "recommend_next_offer"),
    ("treatment", "Treatment", "recommend_treatment"),
    ("authority", "Authority", "evaluate_authority"),
    ("live_qa", "Live QA", "evaluate_live_qa"),
    ("routing", "Routing", None),
    ("dnd", "DND / calling hours", None),
)


class CardIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_id: str
    slug: str
    display_name: str
    purpose: str = ""
    channels: list[Channel] = Field(default_factory=lambda: ["voice", "whatsapp"])


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
    """One typed edge from this card to another member of the fleet.

    ``to_bot_id`` and ``when`` are what a card has always carried; ``when``
    reaches the model as the ``target_bot_id`` enum description
    (``handoff_allowlist.specialise_handoff_tool``). Everything else here is the
    hop itself, and every field is defaulted so a stored card still parses under
    ``extra='forbid'``.

    ``carry='brief'`` renders the fact-only packet from rows the tools already
    wrote — nothing inferred. There is deliberately no ``carry='everything'``:
    the packet's field list is the boundary, and widening it is an edit to
    ``agent_core.context.handoff_packet_message``, reviewed, not a per-card
    switch an author can flip.
    """

    model_config = ConfigDict(extra="forbid")

    to_bot_id: str
    payload_schema: dict[str, Any] = Field(default_factory=dict)
    when: str = ""
    # No ``mode``, no ``clauses`` and no ``return_to``. A handoff is a
    # ``go_to_*`` transition the model may call — the only kind implemented, and
    # the only kind with a node to hang an edge on. A deterministic hop, or a
    # specialist handing back, is an ordinary edge in the graph, authored there;
    # the hop cap bounds the round trip either way.
    #: How much crosses. ``brief`` is the carry packet; ``full`` additionally
    #: keeps the last turns, which costs prefix tokens and is opt-in per edge.
    carry: HandoffCarry = "brief"
    #: Node in the receiving member's subgraph to enter, local name. Empty means
    #: that member's start node.
    entry_node: str = ""
    #: What to say while the swap happens. A *direction to the model*, not a
    #: script: it rides the tool result's ``say`` key, which the model reads and
    #: renders in the caller's own language — the same convention every other
    #: tool here uses ("acknowledge briefly, then verify them"). Write an
    #: instruction, not a sentence.
    #:
    #: It therefore does **not** hide the receiving brief's first-token latency
    #: today: nothing is spoken during the swap, because the line reaches the
    #: model on the turn *after* it. Covering the hop with audio needs a
    #: ``tts_say`` pre-action on the node the hop lands on, which only becomes
    #: possible once the handler returns that node.
    bridge_line: str = ""
    #: What to say when the hop is refused — over the per-call hop cap, or the
    #: target is not on the allowlist. A direction, like ``bridge_line``. Absent
    #: one the model gets a generic direction rather than this edge's, so the
    #: borrower still hears something in their own language; what is lost is the
    #: author's specific wording.
    refusal_line: str = ""


class CardConnector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_id: str
    allow_prefixes: list[str] = Field(default_factory=list)


class CardMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: No ``scopes`` and no ``compaction``: neither was ever read. Retention is
    #: decided by ``voice/crm_sink.py`` on the voice_memory flag, and the live
    #: ``RAW_LAST_N`` belongs to ``agent_core/compaction.py`` — a card knob that
    #: looked like it controlled compaction and did not.
    #:
    #: Hops one call may make. Two specialists arguing over a borrower is a
    #: ping-pong the caller experiences as being passed around; the cap turns it
    #: into an authored ``refusal_line`` instead.
    max_hops_per_call: int = Field(default=2, ge=0, le=8)


class HumanGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    require: HumanGateRequire = "identity"


class CardEval(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    #: No ``shadow``. There is no non-customer-serving execution path: a shadow
    #: canary served real callers, which is why ``canary.py`` now refuses to
    #: open one and rolls back any that exist. A field whose every value is
    #: rejected is worse than an absent one, because the editor still builds it.
    auto_rollback: list[RollbackTrigger] = Field(default_factory=list)


class CardA2A(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expose: bool = False
    skill_ids: list[str] = Field(default_factory=list)


#: Keys this card used to carry, tolerated on read until every published
#: version has been republished in the new shape.
#:
#: Every model here sets ``extra="forbid"``, and every one of the 18 published
#: cards stores these keys explicitly. So deleting a field is not a schema edit
#: — without this list it makes every published card unparseable, G0 fails, and
#: the fleet stops recompiling. This is that migration, done on read.
#:
#: Deliberately NOT ``extra="ignore"``: an *invented* key must still fail loudly.
#: That is the invariant ``agent-card.ts`` and ``test_agent_card_schema_drift``
#: are both built on, and it is worth more than the convenience.
#:
#: A ``*`` segment means "every element of this list". The list is temporary by
#: construction — ``model_dump`` rewrites a card in the new shape on its next
#: publish — and it only ever shrinks.
_RETIRED: tuple[tuple[str, ...], ...] = (
    ("mouth",),
    ("memory", "scopes"),
    ("memory", "compaction"),
    ("identity", "data_class"),
    ("identity", "regulator_tags"),
    # Nothing read it: not authz, not the fleet index.
    ("identity", "owner_user_id"),
    ("outbound", "concurrency_share"),
    ("outbound", "cadences", "*", "time_of_day"),
    ("experiment", "shadow"),
    # `Literal["required"]` six times over: a binding that could hold one
    # value bound nothing, and G3's "binding half" was unfalsifiable. The
    # engines' actual modes are env-driven and read live
    # (`/agent-studio/policy-engines`); the card no longer claims to set them.
    ("policy_bindings",),
    # Authored on every first-party card and deliberately refused by the
    # runner (`eval/run.py`): the gate reads by kind, never by suite id.
    ("eval", "suite_id"),
)


def _drop_path(node: Any, path: tuple[str, ...]) -> None:
    """Pop ``path`` out of ``node``, walking ``*`` across list elements."""
    head, rest = path[0], path[1:]
    if head == "*":
        if isinstance(node, list):
            for item in node:
                _drop_path(item, rest)
        return
    if not isinstance(node, dict):
        return
    if not rest:
        node.pop(head, None)
        return
    child = node.get(head)
    if child is not None:
        _drop_path(child, rest)


class AgentCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _drop_retired(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        raw = copy.deepcopy(raw)  # a stored card is somebody else's dict
        for path in _RETIRED:
            _drop_path(raw, path)
        return raw

    schema_version: Literal["1"] = SCHEMA_VERSION
    identity: CardIdentity
    skills: list[CardSkillRef] = Field(default_factory=list)
    tools: CardTools = Field(default_factory=CardTools)
    handoffs: list[CardHandoff] = Field(default_factory=list)
    connectors: list[CardConnector] = Field(default_factory=list)
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
