"""What the engine has learned from its own outcomes: the fast loop.

The scorer's probabilities start as hand-set planning figures
(``scoring.REACH_PRIOR`` / ``RESOLVE_PRIOR``). Every labelled decision is
evidence about them. This module counts that evidence and the scorer blends it
in, Beta-binomial style: the starting assumption counts as
:data:`PRIOR_STRENGTH` imaginary attempts, so ten real outcomes nudge it and a
thousand replace it. Nothing is promoted and nothing is refused: the estimate
is the assumption until there is data, and the data as it arrives.

This is a *response* rate, like the prior it updates (``estimand`` stays
``response_prior`` with source ``learned``). Whether contacting someone changed
what they did is the uplift question; the control arm and the slow loop
(panel, trainer, OPE, registry) answer that one.

ponytail: pooled per channel (reach) and per action (resolve), not per bucket;
the scorer's bucket and history multipliers still apply on top. Segment the
counts when a bucket has enough trials to disagree with the pool.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: The starting assumption is worth this many observed attempts.
PRIOR_STRENGTH = 20.0

#: Outcomes older than this stop counting: channels and books drift.
WINDOW_DAYS = 90

#: Seconds a loaded set of counts is reused before re-reading.
_TTL = 300.0

Counts = Mapping[tuple[str, str], tuple[int, int]]

_cache: dict[tuple[str, str], tuple[float, dict[tuple[str, str], tuple[int, int]]]] = {}
_lock = threading.Lock()


@dataclass(frozen=True)
class Estimate:
    """One probability and where it came from."""

    value: float
    source: str  # "prior" | "learned" | "history"
    prior: float
    successes: int = 0
    trials: int = 0

    def to_log(self) -> dict[str, Any]:
        out: dict[str, Any] = {"source": self.source, "value": round(self.value, 4)}
        if self.source != "history":
            out["prior"] = round(self.prior, 4)
        if self.trials:
            out["successes"] = self.successes
            out["trials"] = self.trials
            out["windowDays"] = WINDOW_DAYS
        return out


def blend(prior: float, counts: tuple[int, int] | None) -> Estimate:
    """The posterior mean of a Beta prior centred on ``prior``."""
    successes, trials = counts or (0, 0)
    if trials <= 0:
        return Estimate(prior, "prior", prior)
    value = (successes + prior * PRIOR_STRENGTH) / (trials + PRIOR_STRENGTH)
    return Estimate(value, "learned", prior, successes, trials)


def load(conn: Any, *, tenant_id: str, family: str = "collections") -> dict[tuple[str, str], tuple[int, int]]:
    """``{(metric, key): (successes, trials)}``. Empty when nothing is learned.

    Cached per tenant for a few minutes: the counts change nightly, and the
    scorer runs per decision. Read in a savepoint so a database without the
    table degrades to the priors instead of aborting the caller's transaction.
    """
    key = (tenant_id, family)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _TTL:
            return hit[1]
    counts: dict[tuple[str, str], tuple[int, int]] = {}
    if conn is not None:
        try:
            with conn.begin_nested():
                rows = conn.execute(
                    text(
                        """
                        SELECT metric, key, successes, trials FROM treatment_beliefs
                         WHERE tenant_id = :tenant AND family = :family
                        """
                    ),
                    {"tenant": tenant_id, "family": family},
                ).mappings().all()
            counts = {(r["metric"], r["key"]): (int(r["successes"]), int(r["trials"])) for r in rows}
        except Exception:
            logger.info("treatment_beliefs unreadable; scoring on starting assumptions")
        with _lock:
            _cache[key] = (now, counts)
    return counts


def invalidate() -> None:
    with _lock:
        _cache.clear()


#: Reach: an attempt on this channel reached a person. Enacted decisions only,
#: because an unsent plan reached nobody by construction.
_REACH_SQL = """
SELECT chosen_channel AS key,
       count(*) FILTER (WHERE reach_outcome = 'reached')::int AS successes,
       count(*)::int AS trials
  FROM treatment_decisions
 WHERE tenant_id = :tenant AND mode = 'live' AND enacted
   AND chosen_channel IS NOT NULL AND reach_outcome IS NOT NULL
   AND created_at >= now() - make_interval(days => :days)
   {family}
 GROUP BY 1
"""

#: Resolve: given the attempt landed, the account was cured. Only labels that
#: can no longer change count as failures (a mature label, or one that says the
#: case moved on); a payment counts the moment it posts.
_RESOLVE_SQL = """
SELECT chosen_action AS key,
       count(*) FILTER (WHERE outcome = 'paid' OR cure_outcome = 'paid')::int AS successes,
       count(*)::int AS trials
  FROM treatment_decisions
 WHERE tenant_id = :tenant AND mode = 'live' AND enacted
   AND reach_outcome = 'reached'
   AND (outcome = 'paid' OR cure_outcome IS NOT NULL
        OR (label_mature_at IS NOT NULL AND label_mature_at <= now()))
   AND created_at >= now() - make_interval(days => :days)
   {family}
 GROUP BY 1
"""


def refresh(conn: Any, *, tenant_id: str) -> dict[str, int]:
    """Recount the collections evidence for one tenant. Nightly job."""
    from agent_core.treatment.schema_ready import collections_only, labels_ready

    if not labels_ready(conn):
        return {"reach": 0, "resolve": 0}
    family = collections_only(conn)
    written = {"reach": 0, "resolve": 0}
    for metric, sql in (("reach", _REACH_SQL), ("resolve", _RESOLVE_SQL)):
        rows = conn.execute(
            text(sql.replace("{family}", family)), {"tenant": tenant_id, "days": WINDOW_DAYS}
        ).mappings().all()
        written[metric] = upsert(conn, tenant_id=tenant_id, family="collections", metric=metric, rows=rows)
    # Offers: of the offers actually delivered, how many drew interest.
    from agent_core.treatment.schema_ready import w12_ready

    if not w12_ready(conn):
        invalidate()
        return written
    offers = conn.execute(
        text(
            """
            SELECT product_id AS key,
                   count(*) FILTER (WHERE offer_response = 'interested')::int AS successes,
                   count(*)::int AS trials
              FROM treatment_decisions
             WHERE tenant_id = :tenant AND action_family = 'offer' AND mode = 'live' AND presented
               AND offer_response IN ('interested', 'declined')
               AND created_at >= now() - make_interval(days => :days)
             GROUP BY 1
            """
        ),
        {"tenant": tenant_id, "days": WINDOW_DAYS},
    ).mappings().all()
    written["offerResponse"] = upsert(conn, tenant_id=tenant_id, family="offer", metric="response", rows=offers)
    invalidate()
    return written


def upsert(conn: Any, *, tenant_id: str, family: str, metric: str, rows: Any) -> int:
    """Replace one metric's counts. Keys with no evidence left are dropped."""
    conn.execute(
        text("DELETE FROM treatment_beliefs WHERE tenant_id = :t AND family = :f AND metric = :m"),
        {"t": tenant_id, "f": family, "m": metric},
    )
    n = 0
    for r in rows:
        if not r["key"] or not r["trials"]:
            continue
        conn.execute(
            text(
                """
                INSERT INTO treatment_beliefs (tenant_id, family, metric, key, successes, trials, window_days)
                VALUES (:t, :f, :m, :k, :s, :n, :w)
                """
            ),
            {"t": tenant_id, "f": family, "m": metric, "k": str(r["key"]),
             "s": int(r["successes"]), "n": int(r["trials"]), "w": WINDOW_DAYS},
        )
        n += 1
    return n


if __name__ == "__main__":
    # The arithmetic the scorer leans on.
    assert blend(0.3, None).source == "prior" and blend(0.3, None).value == 0.3
    e = blend(0.3, (0, 20))
    assert e.source == "learned" and abs(e.value - 0.15) < 1e-9  # 6 / 40
    assert abs(blend(0.3, (900, 1000)).value - 0.8882) < 1e-3  # data dominates
    print("ok")
