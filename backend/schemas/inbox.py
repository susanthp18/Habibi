"""The conversation inbox.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.common import Sender

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
    #: When it was sent, ISO 8601: the date a clock-only ``time`` cannot carry.
    at: str | None = None
    # "pending" = accepted by the API and queued, not yet handed to the
    # provider. Its own state on purpose — see db._inbox_delivery.
    delivery: Literal["pending", "sent", "delivered", "read", "failed"] | None = None
    #: Why a failed or held message did not go out, in words; never the
    #: provider's raw text.
    deliveryNote: str | None = None


class InboxSystemEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["system"] = "system"
    text: str
    time: str
    at: str | None = None


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
    """The borrower beside a thread. ``outstanding``, aging and the next EMI
    are the thread's own loan; promises, disputes and interactions span all of
    the customer's loans."""

    model_config = ConfigDict(extra="forbid")

    riskLevel: Literal["High", "Medium", "Low"]  # `critical` on the book reads High here
    #: Whether an agent's reply on this thread would be admitted now: its own
    #: channel, under the purpose the send uses (in-session inside WhatsApp's
    #: service window). Not general outreach eligibility.
    canReply: bool
    #: Why not, when not: a gate reason, ``whatsapp_window_closed``,
    #: ``whatsapp_endpoint_changed`` (the number that opened the window is no
    #: longer on the customer's record), ``channel_not_supported``, or
    #: ``policy_unavailable`` when the gate could not be read.
    replyBlockedReason: str | None = None
    #: When WhatsApp's 24-hour service window closes, ISO 8601.
    replyWindowEndsAt: str | None = None
    #: The last four digits of the number a reply goes to -- the one the
    #: customer wrote from -- and which of theirs it is. Null when no reply
    #: can go.
    replyToLast4: str | None = None
    replyToSlot: Literal["primary", "alt"] | None = None
    contactWindow: str
    outstanding: float | None = None
    outstandingAging: str
    nextEmiDate: str | None = None
    nextEmiAmount: float | None = None
    nextEmiOverdue: bool = False
    lastPromise: InboxPromiseResponse | None = None
    openDisputes: list[InboxDisputeSummaryResponse] = []
    #: All open disputes; ``openDisputes`` lists the newest five.
    openDisputesTotal: int = 0
    recentInteractions: list[InboxInteractionSummaryResponse] = []


class ConversationSummaryResponse(BaseModel):
    """One row of the inbox list. No transcript: the open thread reads it."""

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
    #: Change watermark for delta polls (`?updatedAfter=`).
    updatedAt: str | None = None
    #: The last message, ISO 8601: what the list is ordered by.
    lastAt: str | None = None
    #: The customer's messages since the last reply that reached them. Not a
    #: read receipt -- nothing records what an agent has read.
    awaitingReply: int
    #: How long the oldest of those has waited.
    sla: Literal["ok", "warn", "breach"]
    lastTime: str
    lastPreview: str
    lastFrom: Sender
    sentiment: Literal["positive", "neutral", "negative"]
    handlerBotId: str | None = None


#: The list's views (``GET /conversations?view=``): who holds a thread, or
#: where it stands. ``others`` is assigned to someone other than the caller.
InboxView = Literal["mine", "others", "needs_human", "escalated", "bot", "assigned"]


class ConversationCountsResponse(BaseModel):
    """Threads in each view, across the whole inbox."""

    model_config = ConfigDict(extra="forbid")

    all: int
    mine: int
    others: int
    needs_human: int
    escalated: int
    bot: int
    assigned: int


class ConversationResponse(ConversationSummaryResponse):
    """The open thread, and every write's answer."""

    messages: list[InboxMessageResponse | InboxSystemEventResponse] = []
    ragSuggestions: list[str] = []
    context: InboxThreadContextResponse


class CannedResponseItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    text: str


class ConversationMessageCreateRequest(BaseModel):
    text: str = Field(min_length=1)


class ConversationTakeoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Who the caller saw holding the thread (null: nobody). When set and the
    #: holder has changed since, the takeover is refused, not applied.
    expectedAssigneeId: str | None = None


class ConversationSuggestionsRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topK: int = Field(default=4, ge=1, le=20)
    includeDraftAnswer: bool = False


class ConversationSuggestionsRefreshResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversationId: str
    #: The customer message these answer. Once they have written again, the
    #: passages and the draft answer a question they are no longer asking.
    answersMessageId: str | None = None
    ragSuggestions: list[str]
    #: A reply to the customer, in their language; null when the passages do
    #: not answer them or none was asked for.
    draftAnswer: str | None = None
    #: A draft was asked for and the model could not be reached.
    draftFailed: bool = False
    #: True when the knowledge base could not be searched and these are the
    #: passages found last time.
    stale: bool = False
    #: The customer wrote again while this searched: nothing was kept, and
    #: there is nothing to show -- the newer message gets its own search.
    superseded: bool = False
