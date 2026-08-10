"""The append-only decision log.

Written on every invocation — including the ones that recommended nothing, and
including shadow runs that were never spoken. Those are not noise: a log that
only contains offers we actually made has no negative class in it and cannot
train anything, and it cannot answer "why did the engine go quiet on Tuesday?".

Nothing here is allowed to fail loudly. A logging error must never cost a
customer their offer, so every function swallows and logs. The cost of that
choice is that gaps in the log are possible; the alternative is dropping a
call because an INSERT timed out.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Mapping, Sequence

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _id() -> str:
    return f"OD-{uuid.uuid4().hex[:12].upper()}"


def record(
    *,
    customer_id: str,
    interaction_id: str | None,
    channel: str,
    mode: str,
    variant: str | None,
    recommender: str,
    recommender_version: str,
    feature_schema_version: str,
    features: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    excluded: Mapping[str, str],
    chosen_product_id: str | None,
    suggested_amount: float | None,
    score: float | None,
    suppression_reason: str | None,
    latency_ms: int | None,
) -> str | None:
    """Persist one decision. Returns the id, or None if logging failed."""
    import db

    decision_id = _id()
    try:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO offer_decisions (
                      id, tenant_id, customer_id, interaction_id, channel, mode,
                      variant, recommender, recommender_version,
                      feature_schema_version,
                      features, candidates, excluded,
                      chosen_product_id, suggested_amount, score,
                      suppression_reason, latency_ms, created_at
                    ) VALUES (
                      :id, :tenant, :customer_id, :interaction_id, :channel, :mode,
                      :variant, :recommender, :recommender_version,
                      :feature_schema_version,
                      CAST(:features AS jsonb), CAST(:candidates AS jsonb),
                      CAST(:excluded AS jsonb),
                      -- Resolve inside the INSERT: a product deleted between
                      -- scoring and logging must null the column, not raise a
                      -- foreign-key error that loses the whole row.
                      (SELECT p.id FROM products p WHERE p.id = :chosen_product_id),
                      :suggested_amount, :score,
                      :suppression_reason, :latency_ms, now()
                    )
                    """
                ),
                {
                    "id": decision_id,
                    "tenant": db.TENANT_ID,
                    "customer_id": customer_id,
                    "interaction_id": interaction_id,
                    "channel": channel,
                    "mode": mode,
                    "variant": variant,
                    "recommender": recommender,
                    "recommender_version": recommender_version,
                    "feature_schema_version": feature_schema_version,
                    "features": json.dumps(features, default=str),
                    "candidates": json.dumps(list(candidates), default=str),
                    "excluded": json.dumps(dict(excluded), default=str),
                    "chosen_product_id": chosen_product_id,
                    "suggested_amount": suggested_amount,
                    "score": score,
                    "suppression_reason": suppression_reason,
                    "latency_ms": latency_ms,
                },
            )
        return decision_id
    except Exception:
        logger.exception("offer decision log failed for customer=%s", customer_id)
        return None


def mark_presented(decision_id: str | None) -> None:
    """The offer was actually spoken. Distinct from having been chosen."""
    if not decision_id:
        return
    import db

    try:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE offer_decisions SET presented = true, presented_at = now()"
                    " WHERE id = :id AND presented IS FALSE"
                ),
                {"id": decision_id},
            )
    except Exception:
        logger.exception("mark_presented failed for %s", decision_id)


def record_response(decision_id: str | None, response: str) -> None:
    """Label the outcome: interested / declined / deferred / not_reached."""
    if not decision_id:
        return
    if response not in {"interested", "declined", "deferred", "not_reached"}:
        logger.warning("ignoring unknown offer response %r", response)
        return
    import db

    try:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE offer_decisions SET response = :response, responded_at = now()"
                    " WHERE id = :id AND response IS NULL"
                ),
                {"id": decision_id, "response": response},
            )
    except Exception:
        logger.exception("record_response failed for %s", decision_id)


def attach_lead(decision_id: str | None, *, lead_id: str, response: str = "interested") -> None:
    """Join the decision to the lead it produced — the training label."""
    if not decision_id:
        return
    import db

    try:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE offer_decisions
                    SET lead_id = :lead_id,
                        response = COALESCE(response, :response),
                        responded_at = COALESCE(responded_at, now()),
                        presented = true,
                        presented_at = COALESCE(presented_at, now())
                    WHERE id = :id
                    """
                ),
                {"id": decision_id, "lead_id": lead_id, "response": response},
            )
    except Exception:
        logger.exception("attach_lead failed for %s", decision_id)
