"""The nightly opportunity sweep: fresh buying signals become offer decisions.

For every customer with a recent, positive, unsuperseded signal and no offer
decided for them in the last week, the offer engine runs in promotional
context, citing the signals it was given. What it decides is logged with the
same trace as any offer; what reaches the customer is the promotional
sender's job, which re-checks consent at send time.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: Signals older than this are about a moment that has passed.
FRESH_DAYS = 45
#: Do not decide again for a customer offered anything this recently.
QUIET_DAYS = 7
NEGATIVE = "not_interested"


def candidates(conn: Any, *, tenant_id: str, limit: int = 200) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT s.customer_id,
                   json_agg(json_build_object(
                     'id', s.id, 'code', s.signal_code, 'confidence', s.confidence,
                     'productHint', s.product_hint, 'horizon', s.horizon,
                     'interactionId', s.interaction_id) ORDER BY s.created_at DESC) AS signals
              FROM customer_signals s
             WHERE s.tenant_id = :t AND s.superseded_at IS NULL
               AND s.created_at > now() - make_interval(days => :fresh)
               AND COALESCE(s.feedback, '') <> 'wrong'
               AND NOT EXISTS (
                 SELECT 1 FROM customer_signals n
                  WHERE n.customer_id = s.customer_id AND n.signal_code = :neg
                    AND n.superseded_at IS NULL AND n.created_at > now() - make_interval(days => :fresh))
               AND NOT EXISTS (
                 SELECT 1 FROM treatment_decisions d
                  WHERE d.customer_id = s.customer_id AND d.action_family = 'offer'
                    AND d.created_at > now() - make_interval(days => :quiet))
               AND s.signal_code <> :neg
             GROUP BY s.customer_id
             LIMIT :lim
            """
        ),
        {"t": tenant_id, "fresh": FRESH_DAYS, "quiet": QUIET_DAYS, "neg": NEGATIVE, "lim": limit},
    ).mappings().all()
    return [dict(r) for r in rows]


def sweep(*, tenant_id: str) -> dict[str, Any]:
    """Decide an offer for each customer with fresh signals. One transaction each."""
    import db
    from agent_core.reco import engine as reco

    with db.engine.connect() as conn:
        todo = candidates(conn, tenant_id=tenant_id)
    decided = offered = 0
    for row in todo:
        try:
            with db.engine.begin() as conn:
                result = reco.recommend(
                    customer_id=row["customer_id"],
                    conn=conn,
                    channel="whatsapp",
                    context=reco.PROMOTIONAL,
                    cited_signals=list(row["signals"] or []),
                )
            decided += 1
            offered += 1 if result.offers else 0
        except Exception:
            logger.exception("opportunity decision failed for %s", row["customer_id"])
    return {"customers": len(todo), "decided": decided, "offered": offered}
