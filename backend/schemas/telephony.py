"""Telephony: calls and Twilio.

One module of the ``schemas`` package (was one 6,400-line file); the
router of the same name serves these. ``schemas/__init__`` re-exports every name.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

# The authored flow graph is a domain model, not a transport shape — it is
# shared verbatim by the API, the validator and the voice runtime, so it is
# defined once in flow_graph and reused here rather than restated.
from flow_graph import FlowGraph, FlowIssue, FlowValidation  # noqa: F401

class VoiceSandboxStartRequest(BaseModel):
    """What `voice_sandbox.start_voice_sandbox` reads -- and only that. The
    customer is bound through `persona.customerId`; the bundle is resolved
    from `promptVersionId` or the active sandbox deployment."""

    model_config = ConfigDict(extra="forbid")

    tuning: dict[str, Any] | None = None
    promptVersionId: str | None = None
    # Habibi Live sandbox sends these; voice_sandbox.start_voice_sandbox uses them
    # to create a sandbox_run + session file for the Pipecat runner.
    kbSnapshotId: str | None = None
    scenarioId: str | None = None
    persona: dict[str, Any] | None = None


class VoiceSandboxTuneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tuning: dict[str, Any] | None = None


# ── Telephony ────────────────────────────────────────────────────────────────


class VoiceCapacityResponse(BaseModel):
    enabled: bool
    maxConcurrentCalls: int
    activeCalls: int
    availableSlots: int | None = None
    highWaterMark: int
    admittedTotal: int
    rejectedTotal: int
    longestCallSeconds: float


class VoiceStatusResponse(BaseModel):
    ok: bool
    webrtcUrl: str | None = None
    #: Which browser transport Sandbox Live uses on this deployment.
    transport: Literal["websocket", "webrtc"] = "websocket"
    detail: str
    #: Embedded host only — the counter is process-local.
    capacity: VoiceCapacityResponse | None = None


class VoiceSandboxStartResponse(BaseModel):
    sessionId: str
    webrtcUrl: str
    sandboxRunId: str | None = None
    transport: Literal["websocket", "webrtc"] = "websocket"
    #: ``/ws-sandbox/{sessionId}/{ticket}`` -- a path on the API origin. The
    #: ticket is single-use and expires in two minutes.
    wsUrl: str | None = None


class VoiceSandboxStopResponse(BaseModel):
    ok: bool
    sessionId: str


class VoiceSandboxTuneResponse(BaseModel):
    ok: bool
    tuning: dict[str, Any]
    apply: str


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


class TwilioVoiceStatusResponse(BaseModel):
    configured: bool
    phoneNumber: str | None = None
    handoffMode: str
    wsViaApi: bool
    wsUpstream: str | None = None
    streamUrl: str | None = None
    fallbackUrl: str | None = None
    callStatusCallbackUrl: str | None = None
    streamStatusCallbackUrl: str | None = None
    supervisorPhone: str | None = None
    hint: str
