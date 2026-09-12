"""The interaction event log: transcript turns, commercial events and the record_* writers.

Carved from capture.py. Sync DB only; safe from CrmSink threads and bot_worker jobs.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import text
from sqlalchemy.engine import Connection
from capture import PRODUCT_INTENTS, mark_upsell_presented, touch_primary_intent

logger = logging.getLogger(__name__)


COMMERCIAL_KINDS = frozenset(
    {
        "product_interest",
        "offer_presented",
        "offer_declined",
        "eligibility_checked",
        "lead_captured",
        # The close probe is its own funnel stage. Without it the analytics
        # cannot tell "asked and declined" from "never asked" — which is the
        # only number that says whether asking is worth the handle time.
        "close_probe_presented",
        "identity_verified",
        "identity_partial",
        "identity_failed",
    }
)


def _sid(prefix: str) -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def emit_commercial_event(
    conn: Connection,
    *,
    entity_type: str,
    entity_id: str,
    kind: str,
    label: str,
    note: str | None = None,
    payload: dict[str, Any] | None = None,
    actor_kind: str = "bot",
    actor_bot_id: str | None = None,
    actor_user_id: str | None = None,
    tone: str | None = None,
) -> str:
    """Append a commercial/capture event with payload jsonb (bot/system actor)."""
    # Validate before truncation: activity_events.kind drives the analytics
    # rollups and the Inbox timeline icons, so an unrecognised (or silently
    # 80-char-clipped) kind becomes an invisible event nobody reports on.
    if kind not in COMMERCIAL_KINDS:
        raise ValueError(f"unsupported_commercial_event_kind: {kind!r}")
    event_id = _sid("ACT")
    import db as _db  # lazy: capture is imported by db, avoid a circular import at load

    bot_id = actor_bot_id if actor_kind == "bot" else None
    user_id = actor_user_id if actor_kind == "human" else None
    if actor_kind == "bot" and not bot_id:
        bot_id = getattr(_db, "DEFAULT_BOT_ID", None)

    # No SELECT probe: it cost a round trip per event and raced anyway (a bot
    # deleted between probe and insert still blew up on the FK). Resolve the id
    # inside the INSERT — the subselect yields NULL for an unknown bot and the
    # actor_kind degrades to 'system' in the same statement.
    resolve_bot = bot_id is not None and actor_kind == "bot"
    actor_bot_expr = (
        "(SELECT b.id FROM bots b WHERE b.id = :actor_bot_id)" if resolve_bot else ":actor_bot_id"
    )
    actor_kind_expr = (
        "(CASE WHEN EXISTS (SELECT 1 FROM bots b WHERE b.id = :actor_bot_id)"
        " THEN :actor_kind ELSE 'system' END)"
        if resolve_bot
        else ":actor_kind"
    )
    conn.execute(
        text(
            f"""
            INSERT INTO activity_events (
              id, tenant_id, entity_type, entity_id, at,
              actor_kind, actor_user_id, actor_bot_id,
              kind, label, note, tone, payload, created_at
            ) VALUES (
              :id, :tenant, :entity_type, :entity_id, now(),
              {actor_kind_expr}, :actor_user_id, {actor_bot_expr},
              :kind, :label, :note, :tone, CAST(:payload AS jsonb), now()
            )
            """
        ),
        {
            "id": event_id,
            "tenant": _db.current_tenant(),
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_kind": actor_kind if actor_kind in {"human", "bot", "system", "customer"} else "system",
            "actor_user_id": user_id,
            "actor_bot_id": bot_id,
            "kind": kind,
            "label": (label or kind)[:200],
            "note": note,
            "tone": tone,
            "payload": json.dumps(payload or {}),
        },
    )
    return event_id


# Retries for the auto-allocated turn_index. Contention is between the two
# writers on one interaction (the pipeline and a CRM sink flush), so a handful
# of attempts is far more than the observed depth.
_TURN_ALLOC_ATTEMPTS = 5


def _insert_next_transcript_turn(
    conn: Connection,
    *,
    interaction_id: str,
    speaker: str,
    at_sec: float,
    content: str,
    sentiment_delta: float | None,
    intent: str | None,
    intent_score: float | None,
    ttfb_ms: int | None,
    ttfa_ms: int | None,
    tokens: int | None,
) -> Any:
    """One attempt at MAX(turn_index)+1. Returns the row, or None on conflict."""
    return (
        conn.execute(
            text(
                """
                INSERT INTO interaction_transcript (
                  id, interaction_id, turn_index, speaker, at_sec, text,
                  sentiment_delta, intent, intent_score,
                  ttfb_ms, ttfa_ms, tokens, created_at
                )
                SELECT
                  :id, :interaction_id,
                  COALESCE(
                    (SELECT MAX(turn_index) FROM interaction_transcript WHERE interaction_id = :interaction_id),
                    -1
                  ) + 1,
                  :speaker, :at_sec, :text,
                  :sentiment_delta, :intent, :intent_score,
                  :ttfb_ms, :ttfa_ms, :tokens, now()
                ON CONFLICT (interaction_id, turn_index) DO NOTHING
                RETURNING turn_index
                """
            ),
            {
                # Unique temp id, not a shared "-T-next" sentinel: if a previous
                # auto-allocate hit ON CONFLICT DO NOTHING its rename never ran,
                # leaving "-T-next" in the table — the next insert then failed on
                # the *primary key*, which the (interaction_id, turn_index)
                # conflict target does not cover.
                "id": f"{interaction_id}-T-next-{uuid.uuid4().hex[:12]}",
                "interaction_id": interaction_id,
                "speaker": speaker,
                "at_sec": int(max(0, round(at_sec))),
                "text": content,
                "sentiment_delta": sentiment_delta,
                "intent": intent,
                "intent_score": intent_score,
                "ttfb_ms": ttfb_ms,
                "ttfa_ms": ttfa_ms,
                "tokens": tokens,
            },
        )
        .mappings()
        .first()
    )


def elapsed_seconds(started_at: datetime | None, at: datetime | None) -> int:
    """Whole seconds from an interaction's start to `at`, floored at zero.

    `interaction_transcript.at_sec` is the offset every timing view is keyed
    on. Voice computes it from the call clock; the WhatsApp bridge passed a
    literal 0 for both turns of every exchange, so the whole channel looked
    like it happened in one instant.

    Degrades rather than guesses: a missing start (or a missing instant) is 0,
    which is what the column held before, and a back-dated seed row or a
    skewed clock clamps to 0 rather than storing a negative offset.
    """
    if started_at is None or at is None:
        return 0
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    delta = (at - started_at).total_seconds()
    return int(delta) if delta > 0 else 0


def interaction_started_at(conn: Connection, interaction_id: str) -> datetime | None:
    """When this interaction began, or None if it was never stamped."""
    row = conn.execute(
        text("SELECT started_at FROM interactions WHERE id = :id"),
        {"id": interaction_id},
    ).first()
    return row[0] if row else None


def insert_transcript_turn(
    conn: Connection,
    *,
    interaction_id: str,
    speaker: str,
    text_content: str,
    at_sec: float = 0,
    turn_index: int | None = None,
    sentiment_delta: float | None = None,
    intent: str | None = None,
    intent_score: float | None = None,
    ttfb_ms: int | None = None,
    ttfa_ms: int | None = None,
    tokens: int | None = None,
) -> int:
    """Insert one transcript turn; allocate turn_index atomically when omitted."""
    content = (text_content or "").strip()
    if not content:
        raise ValueError("text_content must not be empty")

    if turn_index is None:
        # ON CONFLICT DO NOTHING means a concurrent writer took the index this
        # statement computed. Retry with a freshly computed index — returning
        # next_transcript_turn_index() here reported a turn as persisted that
        # was never inserted, silently losing a turn of a recorded call.
        row = None
        for _ in range(_TURN_ALLOC_ATTEMPTS):
            row = _insert_next_transcript_turn(
                conn,
                interaction_id=interaction_id,
                speaker=speaker,
                at_sec=at_sec,
                content=content,
                sentiment_delta=sentiment_delta,
                intent=intent,
                intent_score=intent_score,
                ttfb_ms=ttfb_ms,
                ttfa_ms=ttfa_ms,
                tokens=tokens,
            )
            if row is not None:
                break
        if row is None:
            raise RuntimeError(
                f"transcript_turn_allocation_failed: interaction={interaction_id}"
            )
        idx = int(row["turn_index"])
        # Stable id after we know the allocated index. Savepoint-guarded: the
        # canonical id could already be taken by an older row for the same
        # (interaction, index) pair, and the turn itself is more valuable than
        # the cosmetic id.
        nested = conn.begin_nested()
        try:
            conn.execute(
                text(
                    "UPDATE interaction_transcript SET id = :id "
                    "WHERE interaction_id = :ix AND turn_index = :ti"
                ),
                {"id": f"{interaction_id}-T{idx}", "ix": interaction_id, "ti": idx},
            )
            nested.commit()
        except Exception:
            nested.rollback()
            logger.warning(
                "transcript turn id normalisation skipped interaction=%s turn=%s",
                interaction_id,
                idx,
                exc_info=True,
            )
        return idx

    conn.execute(
        text(
            """
            INSERT INTO interaction_transcript (
              id, interaction_id, turn_index, speaker, at_sec, text,
              sentiment_delta, intent, intent_score,
              ttfb_ms, ttfa_ms, tokens, created_at
            ) VALUES (
              :id, :interaction_id, :turn_index, :speaker, :at_sec, :text,
              :sentiment_delta, :intent, :intent_score,
              :ttfb_ms, :ttfa_ms, :tokens, now()
            )
            ON CONFLICT (interaction_id, turn_index) DO NOTHING
            """
        ),
        {
            "id": f"{interaction_id}-T{turn_index}",
            "interaction_id": interaction_id,
            "turn_index": turn_index,
            "speaker": speaker,
            "at_sec": int(max(0, round(at_sec))),
            "text": content,
            "sentiment_delta": sentiment_delta,
            "intent": intent,
            "intent_score": intent_score,
            "ttfb_ms": ttfb_ms,
            "ttfa_ms": ttfa_ms,
            "tokens": tokens,
        },
    )
    return turn_index


def record_product_interest(
    conn: Connection,
    *,
    interaction_id: str,
    intent: str,
    snippet: str | None = None,
    actor_bot_id: str | None = None,
    topics: list[str] | None = None,
) -> None:
    if intent not in PRODUCT_INTENTS:
        return
    touch_primary_intent(conn, interaction_id, intent)
    emit_commercial_event(
        conn,
        entity_type="interaction",
        entity_id=interaction_id,
        kind="product_interest",
        label=f"Product interest | {intent}",
        note=(snippet or "")[:240] or None,
        # `topics` is what the offer engine reads back as kb_topics_queried.
        payload={"intent": intent, "topics": list(topics or [])},
        actor_bot_id=actor_bot_id,
    )


def record_offer_presented(
    conn: Connection,
    *,
    interaction_id: str,
    product_id: str | None = None,
    source: str = "kb",
    actor_bot_id: str | None = None,
) -> None:
    mark_upsell_presented(conn, interaction_id)
    emit_commercial_event(
        conn,
        entity_type="interaction",
        entity_id=interaction_id,
        kind="offer_presented",
        label="Offer / product info presented",
        note=product_id,
        payload={"productId": product_id, "source": source},
        actor_bot_id=actor_bot_id,
    )


def record_eligibility_checked(
    conn: Connection,
    *,
    interaction_id: str | None,
    customer_id: str,
    product_id: str,
    flags: list[dict[str, Any]],
    blocked: str | None,
    actor_bot_id: str | None = None,
) -> None:
    entity_type = "interaction" if interaction_id else "customer"
    entity_id = interaction_id or customer_id
    emit_commercial_event(
        conn,
        entity_type=entity_type,
        entity_id=entity_id,
        kind="eligibility_checked",
        label=f"Eligibility checked | {product_id}",
        note=blocked or "eligible_or_unknown_ok",
        payload={
            "productId": product_id,
            "customerId": customer_id,
            "blocked": blocked,
            "flagCount": len(flags),
            "failCount": sum(1 for f in flags if f.get("status") == "fail"),
            "unknownCount": sum(1 for f in flags if f.get("status") == "unknown"),
        },
        actor_bot_id=actor_bot_id,
    )


def record_lead_captured(
    conn: Connection,
    *,
    interaction_id: str | None,
    lead_id: str,
    product_id: str,
    actor_bot_id: str | None = None,
    actor_user_id: str | None = None,
) -> None:
    """The offer funnel's numerator, for every capture path.

    Two rows when the capture happened on a call: one against the interaction,
    so Bot Analytics can join it to that call's ``offer_presented``, and one
    against the lead. Anything counting conversions must count distinct leads
    rather than rows — see agent_core/reco/observability.py.

    Now that human captures come through here too, the actor has to be told
    apart. Defaulting to a bot actor would have credited every lead a rep
    raised in the UI to whichever bot id the process happened to configure.
    """
    actor_kind = "bot" if actor_bot_id else ("human" if actor_user_id else "system")
    attribution: dict[str, Any] = {
        "actor_kind": actor_kind,
        "actor_bot_id": actor_bot_id,
        "actor_user_id": actor_user_id,
    }
    if interaction_id:
        mark_upsell_presented(conn, interaction_id)
        emit_commercial_event(
            conn,
            entity_type="interaction",
            entity_id=interaction_id,
            kind="lead_captured",
            label="Lead captured from conversation",
            note=lead_id,
            payload={"leadId": lead_id, "productId": product_id},
            **attribution,
        )
    emit_commercial_event(
        conn,
        entity_type="lead",
        entity_id=lead_id,
        kind="lead_captured",
        label="Lead captured",
        note=product_id,
        payload={"interactionId": interaction_id, "productId": product_id},
        **attribution,
    )


def record_offer_declined(
    conn: Connection,
    *,
    interaction_id: str | None,
    customer_id: str,
    product_id: str | None,
    reason: str | None = None,
    actor_bot_id: str | None = None,
) -> None:
    """A pitch that was heard and refused.

    Distinct from never pitching: the funnel needs the denominator. Recorded
    against the interaction when there is one so Bot Analytics can join it to
    ``offer_presented`` on the same call.
    """
    emit_commercial_event(
        conn,
        entity_type="interaction" if interaction_id else "customer",
        entity_id=interaction_id or customer_id,
        kind="offer_declined",
        label="Offer declined",
        note=(reason or product_id or "")[:240] or None,
        payload={"productId": product_id, "customerId": customer_id, "reason": reason},
        actor_bot_id=actor_bot_id,
    )


def record_close_probe(
    conn: Connection,
    *,
    interaction_id: str,
    with_offer: bool,
    product_id: str | None = None,
    actor_bot_id: str | None = None,
) -> None:
    """The end-of-call "anything else?" question was actually asked."""
    emit_commercial_event(
        conn,
        entity_type="interaction",
        entity_id=interaction_id,
        kind="close_probe_presented",
        label="Close probe presented" + (" with offer" if with_offer else ""),
        note=product_id,
        payload={"withOffer": with_offer, "productId": product_id},
        actor_bot_id=actor_bot_id,
    )
