"""Closing an offer nobody answered — the other half of the label.

`agent_core/reco/decisions.py` writes a response when somebody tells us one.
Almost nobody does. Measured on `collections` on 2026-09-10, the offer log held
**16 decisions and zero responses in its entire history**, and the reason is
structural rather than lazy: a borrower who is not interested says nothing, and
silence has no route to post itself back.

An unanswered offer is not a missing label. It is a label, and which one it is
depends on a fact the log already holds:

* delivered and unanswered  -> ``deferred``. They were asked and did not take it.
* never delivered           -> ``not_reached``. **Censoring** (§11.5), not
  refusal: nobody was asked, so nobody declined. An estimator that scores these
  as rejections is measuring the promotional series' delivery rate and calling
  it demand — which is precisely the mistake §4.6 records on the collections
  side, where an undelivered SMS was labelled a *failed treatment* rather than a
  *failed reach*.

**The window never closes early**, on the same rule §11.6 applies to the
collections labels: a fixed grace measured from the decision, identical for both
arms, so `observed_days` is the same number at every horizon regardless of what
happened. A sweep that closed a case as soon as it looked settled would make the
observation window a function of the outcome.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: How long an offer has to be answered before silence becomes the answer.
#:
#: Fourteen days because the promotional series is asynchronous and a borrower
#: who thinks about a top-up for a week is a real borrower, not a lapse. It is
#: NOT tuned, has never been measured against anything, and must not be selected
#: from an outcome rate under the current value — that is what
#: `agent_core/tuner.py` did before W0 deleted it. §8.10's rule applies: the
#: constant ships with its provenance and the experiment that would replace it,
#: which is a response-time histogram over a corpus that does not yet exist.
GRACE_DAYS = 14

#: Only these are ever written by the sweep. `interested` and `declined` are
#: things a person said, and nothing here is entitled to say them.
DEFERRED = "deferred"
NOT_REACHED = "not_reached"


def sweep(conn: Any, *, now: datetime | None = None, limit: int = 500) -> dict[str, int]:
    """Close every offer past its grace with no response. Returns the counts.

    Takes a connection and a clock rather than reaching for either, so a worker
    and a test on a frozen transaction clock agree about what "today" is —
    the `db_tx` fixture freezes `now()`, and a sweep that read the wall clock
    would disagree with the rows it is reading.

    Idempotent by predicate: the UPDATE matches only rows whose response is
    still NULL, so running it twice writes the second time nothing.
    """
    at = now or datetime.now(timezone.utc)
    cutoff = at - timedelta(days=GRACE_DAYS)
    counts = {DEFERRED: 0, NOT_REACHED: 0}
    for response, delivered in ((DEFERRED, True), (NOT_REACHED, False)):
        try:
            rows = conn.execute(
                text(
                    """
                    UPDATE offer_decisions
                    SET response = :response, responded_at = :at
                    WHERE id IN (
                      SELECT id FROM offer_decisions
                      WHERE response IS NULL
                        AND mode = 'live'
                        AND chosen_product_id IS NOT NULL
                        AND created_at <= :cutoff
                        AND presented = :delivered
                      ORDER BY created_at
                      LIMIT :limit
                      FOR NO KEY UPDATE SKIP LOCKED
                    )
                    RETURNING id
                    """
                ),
                {
                    "response": response,
                    "at": at,
                    "cutoff": cutoff,
                    "delivered": delivered,
                    "limit": limit,
                },
            ).scalars().all()
        except Exception:
            logger.exception("offer follow-through sweep failed for %s", response)
            continue
        counts[response] = len(rows)
        for decision_id in rows:
            _mirror(conn, decision_id=str(decision_id), response=response, at=at)
    if counts[DEFERRED] or counts[NOT_REACHED]:
        logger.info(
            "offer follow-through closed deferred=%s not_reached=%s after %s days",
            counts[DEFERRED],
            counts[NOT_REACHED],
            GRACE_DAYS,
        )
    return counts


def _mirror(conn: Any, *, decision_id: str, response: str, at: datetime) -> None:
    from agent_core.reco import decisions

    decisions.mirror_update(
        conn,
        "offer_response = :response, responded_at = :at",
        {"id": decision_id, "response": response, "at": at},
    )


def process_one(engine: Any) -> bool:
    """Worker entry point. Returns whether this pass closed anything.

    Matches the `process_one(engine) -> bool` shape every other stage in
    `bot_worker.py` uses, so the loop's "did this stage do work?" contract and
    its stage timing apply here without a special case. Batched rather than
    one-row-at-a-time because closing an offer is a bookkeeping write with no
    provider call in it -- there is nothing to time out on, which is what the
    per-row shape exists to bound.
    """
    with engine.begin() as conn:
        counts = sweep(conn)
    return bool(counts[DEFERRED] or counts[NOT_REACHED])
