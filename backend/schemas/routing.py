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
    when: list[Any] = Field(default_factory=list)
    then: RoutingActionRequest


class RoutingRulePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    category: RoutingRuleCategory | None = None
    enabled: bool | None = None
    priority: int | None = None
    when: list[Any] | None = None
    then: RoutingActionRequest | None = None


class RoutingReorderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orderedIds: list[str] = Field(min_length=1)


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
