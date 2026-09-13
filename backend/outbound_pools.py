"""The number pools an outbound call dials from: which number a call gets, and
which numbers are resting because the carriers have stopped putting them
through. Carved out of ``outbound`` (the attempt lifecycle), which reads
``pick_number`` at placement; the worker runs ``sweep_pool_health``.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def pick_number(conn: Any, *, tenant_id: str, pool_name: str | None) -> dict[str, Any] | None:
    """Least-recently-used active number from the named pool.

    Three problems this solves, and only the first is obvious:

    * **TRAI.** BFSI service and transactional calls must originate from the
      1600 series, and one ``TWILIO_PHONE_NUMBER`` in the environment cannot be
      two series at once.
    * **Multi-tenancy.** Two banks on one deployment cannot share a caller ID
      without one of them appearing to call the other's customers.
    * **Spam decay.** A number enough handsets have flagged simply stops
      connecting. Rotating LRU spreads the load; ``answer_rate_7d`` is what
      eventually lets a bad one be retired on evidence rather than on a hunch.

    Returns None when no pool is configured, which is the normal state today —
    the caller then falls back to ``TWILIO_PHONE_NUMBER`` exactly as before.
    """
    if not pool_name:
        return None
    row = conn.execute(
        text(
            """
            SELECT n.id, n.e164, p.kind
            FROM pool_numbers n
            JOIN number_pools p ON p.id = n.pool_id
            WHERE p.tenant_id = :tid AND p.name = :pool AND p.enabled IS TRUE
              AND n.state = 'active'
            ORDER BY n.last_used_at ASC NULLS FIRST
            FOR UPDATE OF n SKIP LOCKED
            LIMIT 1
            """
        ),
        {"tid": tenant_id, "pool": pool_name},
    ).mappings().first()
    if row is None:
        return None
    # Only `last_used_at`, which is what LRU rotation turns on. `attempts_7d` is
    # deliberately not incremented here: incrementing per dial and never decaying
    # produced a lifetime counter with `_7d` in its name, which reads as a rate
    # on any dashboard that renders it. `refresh_pool_health` recomputes both it
    # and `answer_rate_7d` from `call_attempts` over an actual seven days.
    conn.execute(
        text("UPDATE pool_numbers SET last_used_at = now(), updated_at = now() WHERE id = :id"),
        {"id": row["id"]},
    )
    return {"e164": row["e164"], "kind": row["kind"], "pool": pool_name}


#: A number needs this many attempts inside the window before its answer rate is
#: allowed to say anything. Three dials and no answer is a Tuesday; forty dials
#: and no answer is a number the carriers have stopped putting through.
POOL_MIN_ATTEMPTS = 30

#: Below this connect rate, with enough volume behind it, the number rests.
POOL_ANSWER_FLOOR = 0.05

#: How long it rests. Long enough for handset spam lists to age, short enough
#: that a pool of four numbers is not permanently a pool of three.
POOL_COOL_HOURS = 168


def refresh_pool_health(
    conn: Any,
    *,
    tenant_id: str,
    min_attempts: int = POOL_MIN_ATTEMPTS,
    answer_floor: float = POOL_ANSWER_FLOOR,
    cool_hours: int = POOL_COOL_HOURS,
) -> dict[str, int]:
    """Recompute the 7-day pool stats and rotate spam-decayed caller IDs.

    Section 8.2 of the design doc justifies number pools on three grounds, and
    the third — *"a number that has been marked spam by enough handsets stops
    connecting, and there is currently no way to observe that, let alone
    rotate"* — was the one nothing implemented. The columns shipped empty:
    ``answer_rate_7d`` was never computed, no number was ever moved to
    ``cooling``, and ``attempts_7d`` was incremented on every dial and never
    decayed, which made it a lifetime counter wearing a rate's name.

    Two movements, and the second is the one that is easy to leave out:

    * **active -> cooling** when there are enough attempts behind the number to
      judge it and its answer rate has collapsed. The volume gate comes first: a
      rate over four dials is noise, and cooling a good number on noise shrinks
      the pool, which raises the load on the survivors, which is how a rotation
      scheme eats itself.
    * **cooling -> active** once the rest is over. A cooling number takes no
      attempts, so its window empties and it can never again clear the volume
      gate. Without this, the first movement is a one-way door and every caller
      ID eventually ends up behind it.

    ``retired`` is left alone in both directions. Retirement is a human decision
    about a number we intend to hand back to the carrier, and a sweep that could
    undo it would make it mean nothing.
    """
    counts = {"scored": 0, "cooled": 0, "restored": 0}
    params = {
        "tid": tenant_id,
        "min_attempts": max(1, int(min_attempts)),
        "floor": float(answer_floor),
        "hours": max(1, int(cool_hours)),
    }

    scored = conn.execute(
        text(
            """
            WITH windowed AS (
              SELECT from_number,
                     count(*)                                          AS attempts,
                     count(*) FILTER (WHERE answered_at IS NOT NULL)   AS answered
              FROM call_attempts
              WHERE tenant_id = :tid
                AND placed_at >= now() - interval '7 days'
              GROUP BY from_number
            )
            UPDATE pool_numbers n
            SET attempts_7d       = s.attempts,
                answer_rate_7d    = s.rate,
                health_checked_at = now(),
                updated_at        = now()
            FROM (
              SELECT pn.id,
                     COALESCE(w.attempts, 0) AS attempts,
                     CASE WHEN COALESCE(w.attempts, 0) > 0
                          THEN round(w.answered::numeric / w.attempts, 4)
                     END AS rate
              FROM pool_numbers pn
              JOIN number_pools p ON p.id = pn.pool_id AND p.tenant_id = :tid
              LEFT JOIN windowed w ON w.from_number = pn.e164
            ) s
            WHERE n.id = s.id
            """
        ),
        params,
    )
    counts["scored"] = int(scored.rowcount or 0)

    cooled = conn.execute(
        text(
            """
            UPDATE pool_numbers n
            SET state = 'cooling',
                state_changed_at = now(),
                updated_at = now(),
                note = 'answer rate ' || COALESCE(n.answer_rate_7d::text, '?')
                       || ' over ' || n.attempts_7d || ' attempts'
            FROM number_pools p
            WHERE p.id = n.pool_id
              AND p.tenant_id = :tid
              AND n.state = 'active'
              AND n.attempts_7d >= :min_attempts
              AND n.answer_rate_7d IS NOT NULL
              AND n.answer_rate_7d < :floor
            """
        ),
        params,
    )
    counts["cooled"] = int(cooled.rowcount or 0)

    restored = conn.execute(
        text(
            """
            UPDATE pool_numbers n
            SET state = 'active',
                state_changed_at = now(),
                updated_at = now(),
                note = NULL
            FROM number_pools p
            WHERE p.id = n.pool_id
              AND p.tenant_id = :tid
              AND n.state = 'cooling'
              AND n.state_changed_at < now() - make_interval(hours => :hours)
            """
        ),
        params,
    )
    counts["restored"] = int(restored.rowcount or 0)

    if counts["cooled"] or counts["restored"]:
        logger.info(
            "number pool health · tenant=%s · scored=%s cooled=%s restored=%s",
            tenant_id,
            counts["scored"],
            counts["cooled"],
            counts["restored"],
        )
    return counts


def sweep_pool_health(engine: Any, *, tenant_id: str | None = None) -> dict[str, int]:
    """Transaction wrapper for :func:`refresh_pool_health`. Never raises.

    Sweeps **every** tenant that owns a pool rather than the ambient one. The
    worker drains a queue that spans tenants and never binds one, so resolving
    the tenant from ``current_tenant()`` would have kept exactly one bank's
    caller IDs healthy and left every other bank's rotting quietly — with the
    columns populated, which is the version of the bug that survives review.
    """
    totals = {"scored": 0, "cooled": 0, "restored": 0}
    try:
        with engine.begin() as conn:
            if tenant_id:
                tenants = [tenant_id]
            else:
                tenants = [
                    str(r[0])
                    for r in conn.execute(
                        text("SELECT DISTINCT tenant_id FROM number_pools WHERE enabled IS TRUE")
                    ).fetchall()
                ]
            for tid in tenants:
                counts = refresh_pool_health(conn, tenant_id=tid)
                for key in totals:
                    totals[key] += counts.get(key, 0)
        return totals
    except Exception:
        logger.exception("pool health sweep failed")
        return totals
