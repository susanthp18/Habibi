"""Persist one turn's facts and the run that produced them.

Three properties, each of which has cost somebody a night in this codebase
before.

**It never raises and never poisons the caller's transaction.** Both call sites
are in the middle of doing something that matters more than this — a live
WhatsApp reply, a voice call's analysis queue — and an exception here must not
lose the turn. The savepoint is W0's rule at every lent-connection boundary:
without it a single failed INSERT aborts the whole enclosing transaction, and
the symptom surfaces three functions later as something unrelated.

**It does nothing at all on a database without 0119.** ``w9_ready`` is checked
first, so the running corpus is unaffected until the migration is applied.

**A correction is a second row.** ``crm_sink`` persists the keyword baseline
and then corrects it when the LLM answers; overwriting would destroy the
baseline, which is exactly the row a model-risk reviewer needs in order to ask
whether the model improved on it. The prior row is superseded, not replaced.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import text

from agent_core.perception import facts as facts_mod

logger = logging.getLogger(__name__)

#: What ``source_model`` says when no model ran — the deterministic lexicon and
#: keyword classifier that §12.6 calls the day-1 baseline. Named rather than
#: left NULL, because "we do not know what produced this fact" and "the keyword
#: baseline produced this fact" are different answers to an audit.
KEYWORD_BASELINE = "keyword"


def record_turn(
    conn: Any,
    *,
    tenant_id: str,
    customer_id: str | None,
    interaction_id: str | None,
    turn_index: int,
    understanding: Any,
    turn_text: str = "",
    model: str | None = None,
    latency_ms: int | None = None,
    cost_inr: float | None = None,
    outcome: str = "ok",
) -> int:
    """Write this turn's facts. Returns how many were written; 0 on any fault."""
    if customer_id is None and interaction_id is None:
        return 0
    savepoint = None
    try:
        # Imported here, not at module scope: ``agent_core.treatment``'s package
        # init eagerly pulls in the whole decision engine, and a WhatsApp reply
        # should not load the allocator to write one row.
        from agent_core.treatment import schema_ready

        if not schema_ready.w9_ready(conn):
            return 0
        savepoint = conn.begin_nested()
        written = _write(
            conn,
            tenant_id=tenant_id,
            customer_id=customer_id,
            interaction_id=interaction_id,
            turn_index=int(turn_index),
            understanding=understanding,
            turn_text=turn_text,
            model=model,
            latency_ms=latency_ms,
            cost_inr=cost_inr,
            outcome=outcome,
        )
        savepoint.commit()
        return written
    except Exception:
        logger.debug("perception facts not recorded", exc_info=True)
        if savepoint is not None:
            try:
                savepoint.rollback()
            except Exception:
                logger.debug("perception savepoint rollback failed", exc_info=True)
        return 0


def record_turn_for_interaction(
    conn: Any,
    *,
    interaction_id: str | None,
    turn_index: int,
    understanding: Any,
    turn_text: str = "",
    model: str | None = None,
    latency_ms: int | None = None,
) -> int:
    """:func:`record_turn` with the tenant and borrower read off the interaction.

    Both call sites — the WhatsApp worker and the voice analysis queue — know
    the interaction and not the tenant, and resolving it in each of them is how
    two spellings of the same lookup drift. The read is inside the caller's
    transaction, so it sees a row the same transaction has just written.
    """
    if not interaction_id:
        return 0
    try:
        row = conn.execute(
            text("SELECT tenant_id, customer_id FROM interactions WHERE id = :id"),
            {"id": interaction_id},
        ).first()
    except Exception:
        logger.debug("perception interaction lookup failed", exc_info=True)
        return 0
    if row is None:
        return 0
    return record_turn(
        conn,
        tenant_id=str(row[0]),
        customer_id=str(row[1]) if row[1] else None,
        interaction_id=interaction_id,
        turn_index=turn_index,
        understanding=understanding,
        turn_text=turn_text,
        model=model,
        latency_ms=latency_ms,
    )


def _write(
    conn: Any,
    *,
    tenant_id: str,
    customer_id: str | None,
    interaction_id: str | None,
    turn_index: int,
    understanding: Any,
    turn_text: str,
    model: str | None,
    latency_ms: int | None,
    cost_inr: float | None,
    outcome: str,
) -> int:
    source_model = model or str(
        getattr(understanding, "source", "") or KEYWORD_BASELINE
    )
    if source_model == "keyword":
        source_model = KEYWORD_BASELINE

    observed = facts_mod.from_understanding(understanding, text=turn_text)

    run_id = f"PR-{uuid.uuid4().hex[:12].upper()}"
    conn.execute(
        text(
            """
            INSERT INTO perception_runs (
              tenant_id, id, customer_id, interaction_id, turn_index,
              model, latency_ms, cost_inr, outcome
            ) VALUES (
              :tenant, :id, :customer, :ix, :turn,
              :model, :latency, :cost, :outcome
            )
            """
        ),
        {
            "tenant": tenant_id,
            "id": run_id,
            "customer": customer_id,
            "ix": interaction_id,
            "turn": turn_index,
            "model": source_model,
            "latency": latency_ms,
            # NULL, not 0.0, on the keyword path: a keyword pass costs nothing
            # and a zero would claim that had been measured.
            "cost": cost_inr,
            "outcome": outcome,
        },
    )

    written = 0
    for fact in observed:
        fact_id = f"PF-{uuid.uuid4().hex[:12].upper()}"
        # Close the standing answer for this key before writing the new one.
        # The partial unique index permits exactly one live row per key per
        # turn, so this is what makes a correction land rather than conflict.
        conn.execute(
            text(
                """
                UPDATE perception_facts
                   SET superseded_at = now(), superseded_by = :new_id
                 WHERE tenant_id = :tenant
                   AND interaction_id IS NOT DISTINCT FROM :ix
                   AND turn_index = :turn
                   AND fact_key = :key
                   AND superseded_at IS NULL
                """
            ),
            {
                "new_id": fact_id,
                "tenant": tenant_id,
                "ix": interaction_id,
                "turn": turn_index,
                "key": fact.key,
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO perception_facts (
                  tenant_id, id, customer_id, interaction_id, turn_index,
                  fact_key, fact_value, provenance, input_provenance,
                  confidence, abstained, source_model, schema_version
                ) VALUES (
                  :tenant, :id, :customer, :ix, :turn,
                  :key, CAST(:value AS jsonb), :provenance, :inputs,
                  :confidence, :abstained, :model, :schema
                )
                """
            ),
            {
                "tenant": tenant_id,
                "id": fact_id,
                "customer": customer_id,
                "ix": interaction_id,
                "turn": turn_index,
                "key": fact.key,
                "value": json.dumps(fact.value),
                "provenance": fact.provenance,
                "inputs": list(fact.input_provenance),
                "confidence": fact.confidence,
                "abstained": fact.abstained,
                "model": source_model,
                "schema": facts_mod.SCHEMA_VERSION,
            },
        )
        written += 1
    return written
