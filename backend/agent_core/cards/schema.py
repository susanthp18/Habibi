"""Agent Card — the compile-time contract for one mouth.

Mouth columns (prompt, persona, voice, guardrails, flow) stay on
``prompt_versions``. The card names the bot, the tools it may call, the
handoffs it may make, and the engines it cannot unbind.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1"

Channel = Literal["voice", "whatsapp", "sms", "internal", "mcp", "a2a"]
DataClass = Literal["pii", "money", "marketing", "internal"]
MemoryScope = Literal["turn", "call", "case", "customer"]
PinMode = Literal["exact", "caret"]
PolicyBinding = Literal["required"]
EvalRequire = Literal["regression", "redteam", "capability", "twin"]
RollbackTrigger = Literal["slo_miss", "live_qa_burn", "eval_fail"]
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
