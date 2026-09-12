"""Routing rules and audit.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# The authored flow graph is a domain model, not a transport shape — it is
# shared verbatim by the API, the validator and the voice runtime, so it is
# defined once in flow_graph and reused here rather than restated.
from flow_graph import FlowGraph, FlowIssue, FlowValidation  # noqa: F401

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
# Routing writes + audit
# ---------------------------------------------------------------------------


class RoutingConditionRequest(BaseModel):
    """One condition of a rule: ``field op value`` (Habibi ``Condition``)."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    field: str = Field(min_length=1)
    op: Literal["=", "!=", ">", "<", ">=", "<=", "in", "contains"] = "="
    value: str | float | int | bool | list[str] | None = None


class RoutingOrGroupRequest(BaseModel):
    """An OR-group of conditions inside the rule's AND-list (Habibi ``ConditionNode``).

    ``or`` is a keyword, so the field is ``or_`` with the wire name as its alias;
    the router dumps by alias so the evaluator sees ``{"or": [...]}``."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str | None = None
    or_: list[RoutingConditionRequest] = Field(alias="or")


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
    when: list[RoutingConditionRequest | RoutingOrGroupRequest] = Field(default_factory=list)
    then: RoutingActionRequest


class RoutingRulePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    category: RoutingRuleCategory | None = None
    enabled: bool | None = None
    priority: int | None = None
    when: list[RoutingConditionRequest | RoutingOrGroupRequest] | None = None
    then: RoutingActionRequest | None = None


class RoutingReorderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orderedIds: list[str] = Field(min_length=1)


class RoutingSimulateRequest(BaseModel):
    """The simulator's hand-built context: the fields the rule editor offers."""

    model_config = ConfigDict(extra="forbid")

    context: dict[str, Any]


class RoutingSimulateConditionResponse(BaseModel):
    id: str
    matched: bool


class RoutingSimulateNodeResponse(BaseModel):
    nodeId: str
    isOr: bool
    matched: bool
    conditions: list[RoutingSimulateConditionResponse]


class RoutingSimulateRuleResponse(BaseModel):
    ruleId: str
    matched: bool
    nodes: list[RoutingSimulateNodeResponse]


class RoutingSimulateResponse(BaseModel):
    results: list[RoutingSimulateRuleResponse]
    #: The first enabled rule that matched, in priority order.
    firingRuleId: str | None = None


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
