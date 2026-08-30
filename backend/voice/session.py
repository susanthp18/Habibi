"""Per-call session state — identity is bound here, never from the LLM."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


def to_money(value: Any) -> Decimal:
    """Coerce a CRM/DB amount to an exact 2dp Decimal.

    Account balances are ``numeric`` in Postgres and arrive as ``Decimal``.
    Round-tripping them through ``float`` makes over-balance comparisons and
    anything handed to CRM/billing subtly inexact, so the session keeps the
    exact value and only narrows to float at the JSON boundary.
    """
    if value is None or value == "":
        return Decimal("0.00")
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, ArithmeticError):
        return Decimal("0.00")


@dataclass
class VoiceSession:
    """Server-side session binding for CRM tool closures (plan §4.4).

    The model may supply business args only (amount, date, reason).
    customer_id / account_id / interaction_id come from this object.
    """

    session_id: str
    interaction_id: str | None = None
    deployment_id: str | None = None
    customer_id: str | None = None
    account_id: str | None = None
    transport: str = "smallwebrtc"
    provider_call_id: str | None = None
    identity_verified: bool = False
    # True when the CRM bind at connect failed and this call is running without
    # an interaction row. Set once, on the connect path; read at teardown, where
    # it makes the sink file a minimal row (start, end,
    # disposition=crm_degraded) instead of letting the call end unrecorded.
    #
    # A collections call nobody can produce a record of is the worst outcome
    # available here — worse than a thin record, and far worse than the
    # alternative of hanging up on the borrower mid-disclosure, which this flag
    # exists to avoid. Anything that discards CRM work because
    # ``interaction_id`` is unset should say so rather than degrade quietly.
    crm_degraded: bool = False
    outstanding: Decimal = Decimal("0.00")
    call_started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    turn_index: int = 0
    rag_hits: int = 0

    # Latest classified customer turn (agent_core.understanding.TurnUnderstanding).
    # Written by the CrmSink's analysis queue, read by the offer engine, lead
    # capture and the guardrail evaluator so none of them re-derive it from the
    # raw text — which on a Hindi turn returns out_of_scope / 0.00 regardless of
    # what was said.
    #
    # Typed Any to keep voice.session import-light: agent_core.understanding
    # pulls in the intent and sentiment modules, and this dataclass is imported
    # by the Pipecat bot at process start.
    understanding: Any | None = None
    # The turn_index `understanding` describes. The LLM refinement lands one or
    # more turns late; a consumer that cares whether it is looking at *this*
    # turn or the previous one compares this against turn_index.
    understanding_turn_index: int = 0

    # Why the caller says they called, captured at the discover_intent node
    # before verification. The graph used to run greet → verify → recite the
    # balance, which is an outbound collections script wearing an inbound
    # greeting: the caller was never asked what they wanted, and the hub stated
    # the outstanding amount whether or not it had anything to do with their
    # reason for calling.
    #
    # `call_goal` is the caller's own words (the model's one-line summary of
    # them); `call_goal_intent` is the classified intent, taken from the LLM
    # understanding layer rather than a keyword table. Both are session-only —
    # the per-turn intent already persists to interaction_transcript, so this
    # needs no schema change.
    call_goal: str | None = None
    call_goal_intent: str | None = None
    # Which turn stated the goal, so the analysis queue can upgrade
    # `call_goal_intent` from the keyword baseline to the LLM classification
    # when the refinement for *that* turn lands (it arrives a turn or two late,
    # by which point `understanding` already describes a later turn).
    call_goal_turn_index: int | None = None

    # Who spoke most recently. Read when a node transition lands on a step
    # configured to listen first: if the CALLER spoke last they have already
    # taken their turn and are waiting, so listening again is not patience, it
    # is dead air — VS-92CDE3F088 sat silent for 24 seconds after
    # begin_negotiate for exactly this reason. Set by the CRM sink, which sees
    # both halves of every exchange. Session-only; nothing persists it.
    last_speaker: str | None = None

    extra: dict[str, Any] = field(default_factory=dict)

    def at_sec(self, when: datetime | None = None) -> float:
        ts = when or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            # call_started_at is always aware; subtracting a naive timestamp
            # would raise TypeError mid-call. Callers that read a naive
            # timestamp off a DB row mean UTC.
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (ts - self.call_started_at).total_seconds())

    def next_turn_index(self) -> int:
        self.turn_index += 1
        return self.turn_index
