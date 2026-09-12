"""Payments: intents, plans, webhooks.

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

from schemas.common import (
    Channel,
    PromiseResponse,
)

class PtpEventResponse(BaseModel):
    at: str
    label: str
    tone: Literal["info", "success", "warn", "danger"] | None = None


class PromiseListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    customerId: str
    customerName: str
    accountTail: str
    amount: float
    promisedDate: str
    createdAt: str
    channel: Channel
    source: Literal["bot", "agent", "self"]
    owner: str
    reminderStatus: Literal["off", "scheduled", "sent"]
    status: Literal["upcoming", "due_today", "kept", "broken", "partial"]
    paidAmount: float | None = None
    notes: str | None = None
    planId: str | None = None
    events: list[PtpEventResponse] = []
    confirmChannel: Literal["whatsapp", "sms"] | None = None
    confirmStatus: str | None = None
    paymentIntentStatus: str | None = None
    paymentIntentId: str | None = None
    payLinkSent: bool = False
    phoneLast4: str | None = None


class InstallmentResponse(BaseModel):
    index: int
    dueDate: str
    amount: float
    paid: bool
    paidOn: str | None = None


class PaymentPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    customerId: str
    customerName: str
    accountTail: str
    total: float
    cadence: Literal["weekly", "biweekly", "monthly"]
    startDate: str
    installments: list[InstallmentResponse] = []
    owner: str
    status: Literal["on_track", "slipped", "completed"]
    createdAt: str


class PromiseCreateRequest(BaseModel):
    customerId: str
    accountId: str | None = None
    interactionId: str | None = None
    amount: float = Field(gt=0)
    promisedDate: str
    channel: Channel = "voice"
    handler: str | None = None
    # Owner triplet: exactly one of ownerUserId / ownerBotId (defaults to the
    # acting user when neither is supplied).
    ownerUserId: str | None = None
    ownerBotId: str | None = None
    reminderStatus: Literal["off", "queued", "scheduled", "sent", "acknowledged", "failed"] = "queued"


class PromisePatchRequest(BaseModel):
    status: Literal["upcoming", "kept", "broken", "partial"] | None = None
    promisedDate: str | None = None
    paidAmount: float | None = Field(default=None, ge=0)


class PaymentPlanCreateRequest(BaseModel):
    customerId: str
    accountId: str | None = None
    totalAmount: float = Field(gt=0)
    installments: list[dict[str, Any]]


# ── Payments ─────────────────────────────────────────────────────────────────


class PromiseFulfillmentResponse(BaseModel):
    """`promise_fulfillment.FulfillmentResult.as_dict`."""

    promiseId: str
    intentId: str | None = None
    confirmChannel: str | None = None
    phoneLast4: str | None = None
    payLinkSent: bool
    suppressed: bool
    suppressionReason: str | None = None


class PromiseResendConfirmResponse(PromiseResponse):
    """The promise row plus what the resend did, under the underscore keys the
    builder has always emitted."""

    fulfillment: PromiseFulfillmentResponse = Field(
        validation_alias="_fulfillment", serialization_alias="_fulfillment"
    )
    spoken: str | None = Field(default=None, validation_alias="_spoken", serialization_alias="_spoken")


class PaymentPlanCreateResponse(BaseModel):
    id: str
    promise: PromiseResponse
