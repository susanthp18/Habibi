"""Per-call session state — identity is bound here, never from the LLM."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


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
    outstanding: float = 0.0
    call_started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    turn_index: int = 0
    rag_hits: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def at_sec(self, when: datetime | None = None) -> float:
        ts = when or datetime.now(timezone.utc)
        return max(0.0, (ts - self.call_started_at).total_seconds())

    def next_turn_index(self) -> int:
        self.turn_index += 1
        return self.turn_index
