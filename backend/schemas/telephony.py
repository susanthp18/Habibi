"""Telephony: calls and Twilio.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

# ── Telephony ────────────────────────────────────────────────────────────────


class TwilioOutboundCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: str = Field(validation_alias=AliasChoices("to", "phone"))
    customerId: str | None = Field(default=None, validation_alias=AliasChoices("customerId", "customer_id"))
    objective: str = "manual_outbound"
    accountId: str | None = Field(default=None, validation_alias=AliasChoices("accountId", "account_id"))
    botId: str | None = None
    custom: dict[str, Any] | None = None


class TwilioOutboundCallResponse(BaseModel):
    """Three branches: idempotent replay (placed/attemptId/state/idempotent),
    an ad-hoc dial with no customer (callSid/to/status/from), or the dial
    owner's result (placed/state/attemptId/to/callSid/status)."""

    placed: bool | None = None
    attemptId: str | None = None
    state: str | None = None
    idempotent: bool | None = None
    to: str | None = None
    callSid: str | None = None
    status: str | None = None
    from_: str | None = Field(default=None, alias="from")
