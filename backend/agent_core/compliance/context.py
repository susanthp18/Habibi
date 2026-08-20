"""Everything a detector is allowed to look at, loaded once per interaction.

Detectors are pure functions over this object. They do no I/O, which is what
lets the whole catalog run in one pass over one set of reads instead of
sixteen round trips per call, and what makes them testable without a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text

# Speakers that represent *us*. A rule about what the lender said must never
# fire on the borrower's own words — the borrower is allowed to swear at us.
OUR_SPEAKERS = frozenset({"agent", "bot"})


@dataclass(frozen=True)
class Turn:
    index: int
    speaker: str
    at_sec: int
    text: str
    sentiment_delta: float | None
    intent: str | None

    @property
    def ours(self) -> bool:
        return self.speaker in OUR_SPEAKERS

    @property
    def lower(self) -> str:
        return self.text.lower()


@dataclass(frozen=True)
class ScanContext:
    """One interaction, plus the facts the catalog needs to judge it."""

    interaction_id: str
    tenant_id: str
    customer_id: str
    channel: str
    direction: str | None
    status: str
    disposition: str | None
    handler_kind: str
    handler_user_id: str | None
    handler_bot_id: str | None
    started_at: datetime | None
    duration_sec: int | None
    avg_sentiment: float | None
    turns: tuple[Turn, ...] = ()
    #: interaction_disclosures rows that were actually marked read, by rule id.
    disclosures_read: frozenset[str] = frozenset()
    #: Customer's timezone name, for the calling-window rule.
    timezone: str | None = None
    #: True when the customer had an active DND / opt-out at contact time.
    on_dnd: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def our_turns(self) -> tuple[Turn, ...]:
        return tuple(t for t in self.turns if t.ours)

    @property
    def customer_turns(self) -> tuple[Turn, ...]:
        return tuple(t for t in self.turns if not t.ours)

    @property
    def is_outbound(self) -> bool:
        return (self.direction or "").lower() == "outbound"

    @property
    def substantive(self) -> bool:
        """Did a conversation actually happen?

        Disclosure rules must not fire on a ring-out, a voicemail or a
        wrong-number hangup: nobody was there to be disclosed to, and filing
        those would bury the real breaches under noise. The floor matches the
        one the reachability features use.
        """
        if (self.disposition or "").lower() in {
            "no_answer",
            "busy",
            "voicemail",
            "failed",
            "wrong_number",
            "dnd",
        }:
            return False
        return len(self.customer_turns) > 0

    def said(self, *phrases: str) -> Turn | None:
        """First of *our* turns containing any phrase. Case-insensitive."""
        for turn in self.turns:
            if not turn.ours:
                continue
            low = turn.lower
            if any(p in low for p in phrases):
                return turn
        return None


_INTERACTION_SQL = """
    SELECT i.id, i.tenant_id, i.customer_id, i.channel, i.direction, i.status,
           i.disposition, i.handler_kind, i.handler_user_id, i.handler_bot_id,
           i.started_at, i.duration_sec, i.avg_sentiment,
           c.timezone,
           COALESCE(c.dnd, FALSE) AS on_dnd
    FROM interactions i
    JOIN customers c ON c.id = i.customer_id
    WHERE i.id = :id
"""


def load_context(conn: Any, interaction_id: str) -> ScanContext | None:
    """Three reads. Returns None when the interaction is gone."""
    row = conn.execute(text(_INTERACTION_SQL), {"id": interaction_id}).mappings().first()
    if row is None:
        return None

    turns = tuple(
        Turn(
            index=int(r["turn_index"]),
            speaker=(r["speaker"] or "").strip().lower(),
            at_sec=int(r["at_sec"] or 0),
            text=r["text"] or "",
            sentiment_delta=float(r["sentiment_delta"]) if r["sentiment_delta"] is not None else None,
            intent=r["intent"],
        )
        for r in conn.execute(
            text(
                "SELECT turn_index, speaker, at_sec, text, sentiment_delta, intent"
                " FROM interaction_transcript WHERE interaction_id = :id"
                " ORDER BY turn_index"
            ),
            {"id": interaction_id},
        ).mappings()
    )

    disclosures = frozenset(
        r["rule_id"]
        for r in conn.execute(
            text(
                "SELECT rule_id FROM interaction_disclosures"
                " WHERE interaction_id = :id AND read IS TRUE AND rule_id IS NOT NULL"
            ),
            {"id": interaction_id},
        ).mappings()
    )

    return ScanContext(
        interaction_id=row["id"],
        tenant_id=row["tenant_id"],
        customer_id=row["customer_id"],
        channel=(row["channel"] or "").strip().lower(),
        direction=row["direction"],
        status=row["status"],
        disposition=row["disposition"],
        handler_kind=row["handler_kind"],
        handler_user_id=row["handler_user_id"],
        handler_bot_id=row["handler_bot_id"],
        started_at=row["started_at"],
        duration_sec=row["duration_sec"],
        avg_sentiment=float(row["avg_sentiment"]) if row["avg_sentiment"] is not None else None,
        turns=turns,
        disclosures_read=disclosures,
        timezone=row["timezone"],
        on_dnd=bool(row["on_dnd"]),
    )
