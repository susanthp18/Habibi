"""The conversation inbox.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The authored flow graph is a domain model, not a transport shape — it is
# shared verbatim by the API, the validator and the voice runtime, so it is
# defined once in flow_graph and reused here rather than restated.
from flow_graph import FlowGraph, FlowIssue, FlowValidation  # noqa: F401

class HandoffDisclosureRequest(BaseModel):
    itemId: str
    ruleId: str | None = None
    label: str | None = None
    read: bool = True


# ---------------------------------------------------------------------------
# Conversation Inbox (Phase 3B Tier 3)
# ---------------------------------------------------------------------------


class InboxMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    sender: Literal["customer", "bot", "agent"]
    text: str
    time: str
    # "pending" = accepted by the API and queued, not yet handed to the
    # provider. Its own state on purpose — see db._inbox_delivery.
    delivery: Literal["pending", "sent", "delivered", "read", "failed"] | None = None


class InboxSystemEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["system"] = "system"
    text: str
    time: str


class InboxPromiseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: float
    date: str
    status: Literal["Kept", "Broken", "Pending", "Partial"]


class InboxDisputeSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    summary: str


class InboxInteractionSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["call", "chat"]
    summary: str
    when: str
    sentiment: Literal["positive", "neutral", "negative"]


class InboxThreadContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    riskLevel: Literal["High", "Medium", "Low"]  # `critical` on the book reads High here
    contactableNow: bool
    contactWindow: str
    outstanding: float
    outstandingAging: str
    nextEmiDate: str
    nextEmiAmount: float
    lastPromise: InboxPromiseResponse | None = None
    openDisputes: list[InboxDisputeSummaryResponse] = []
    recentInteractions: list[InboxInteractionSummaryResponse] = []


class ConversationListResponse(BaseModel):
    """Conversation Inbox screen Thread shape."""

    model_config = ConfigDict(extra="forbid")

    id: str
    customer: str
    customerId: str
    accountId: str
    # Every value the conversations.channel CHECK constraint permits, and the
    # constraint is the authority — see tests/test_inbox_channel_contract.py.
    #
    # This listed three of the five. `response_model` validates the WHOLE list,
    # so the first voice conversation ever written did not render as an odd row:
    # it raised ResponseValidationError and took the entire inbox down with
    # "Failed to load inbox: Failed to fetch". One sandbox call was enough.
    channel: Literal["whatsapp", "sms", "email", "chat", "voice"]
    status: Literal["bot", "needs_human", "escalated", "assigned"]
    assignedUserId: str | None = None
    isMine: bool
    botTyping: bool = False
    pendingOutbound: bool = False
    updatedAt: str | None = None
    sla: Literal["ok", "warn", "breach"]
    unread: int
    lastTime: str
    lastPreview: str
    lastFrom: Literal["customer", "bot", "agent"]
    sentiment: Literal["positive", "neutral", "negative"]
    ragSuggestions: list[str] = []
    ragDraftAnswer: str | None = None
    handlerBotId: str | None = None
    messages: list[InboxMessageResponse | InboxSystemEventResponse] = []
    context: InboxThreadContextResponse


class CannedResponseItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    text: str


class ConversationMessageCreateRequest(BaseModel):
    text: str = Field(min_length=1)


class ConversationSuggestionsRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topK: int = Field(default=4, ge=1, le=20)
    includeDraftAnswer: bool = False


class ConversationSuggestionsRefreshResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversationId: str
    ragSuggestions: list[str]
    draftAnswer: str | None = None
    chatModel: str | None = None
    latencyMs: int | None = None
    logId: str | None = None
    thread: ConversationListResponse | None = None
