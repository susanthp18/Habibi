#!/usr/bin/env python
"""Development tool — synthesise an offer-decision corpus.

    python scripts/simulate_offer_decisions.py --calls 800

**This is not production data and must never be run against a production
database.** It writes rows into `offer_decisions` that look like real shadow
traffic so the parts of the pipeline that only exist once a corpus does —
`train_propensity.py`, `replay_offers.py`, the observability queries — can be
exercised and tested before two weeks of live shadow mode have elapsed.

It refuses to run unless `RECO_SIMULATION_OK=1` is set, and it tags every row
it writes with `mode='simulated'` so the trainer, the replay harness and the
dashboards can all exclude it with one predicate.

The latent "truth" it samples outcomes from is deliberately a *different*
function from the rule scorer: if the simulated customer accepted exactly what
the rule scorer already ranks first, a model trained on it would learn nothing
except to imitate the baseline, and the whole exercise would prove nothing.
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("simulate_offers")

SIMULATED_MODE = "simulated"


def _accept_probability(vector: dict[str, float | None]) -> float:
    """The latent truth outcomes are drawn from.

    Weighted towards in-call intent and affordability and *against* fatigue and
    exit intent — a plausible reality, and one the rule scorer's flat weighting
    only partly captures, so there is something for a model to find.
    """

    def get(name: str, default: float = 0.5) -> float:
        value = vector.get(name)
        return default if value is None else float(value)

    # The intercept sets the base rate. Tuned to land around 12-18% conversion,
    # which is roughly what a well-targeted in-call cross-sell achieves — a
    # corpus at 60% would make every metric downstream look wonderful and prove
    # nothing about a real one.
    z = (
        -4.6
        + 2.4 * get("in_call_intent", 0.25)
        + 1.6 * get("affordability")
        + 1.1 * get("credit_health")
        + 0.9 * get("affinity")
        + 0.7 * get("sentiment")
        - 1.8 * get("fatigue", 0.0)
        - 2.2 * get("exit_intent", 0.0)
        + 1.3 * get("product_mentioned", 0.0)
        + 0.8 * get("kb_topic_match", 0.0)
        - 1.0 * get("utilization")
    )
    return 1.0 / (1.0 + pow(2.718281828, -z))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--calls", type=int, default=800)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--purge", action="store_true", help="delete previously simulated rows first")
    args = ap.parse_args()

    if (os.getenv("RECO_SIMULATION_OK") or "").strip() != "1":
        logger.error(
            "refusing to write synthetic decisions without RECO_SIMULATION_OK=1. "
            "This writes fake rows into offer_decisions; never run it against production."
        )
        return 2

    # Force the engine to score everything so the corpus covers the whole
    # candidate space, not only the calls that happened to clear arbitration.
    os.environ["RECO_MODE"] = "live"
    os.environ["RECO_REQUIRE_COMMITMENT"] = "false"
    os.environ["RECO_SCORER"] = "rule"
    os.environ["RECO_MIN_SCORE"] = "0.0"
    os.environ["RECO_MAX_PER_CUSTOMER_30D"] = "999999"
    # Cool-downs and frequency caps are real policy and they work — which is
    # exactly the problem here. Over a few hundred simulated calls against a
    # seed of twenty customers they starve the catalogue within a handful of
    # calls each and the corpus ends up a few dozen rows of whatever survived.
    # Disabled so the simulation produces feature coverage; the gates
    # themselves are covered by unit tests, not by this.
    os.environ["RECO_DECLINE_COOLDOWN_DAYS"] = "0"
    os.environ["RECO_FAMILY_COOLDOWN_DAYS"] = "0"

    import db
    from sqlalchemy import text

    from agent_core.reco import decisions, engine
    from agent_core.reco.features import CallSignals

    rng = random.Random(args.seed)

    with db.engine.connect() as conn:
        customers = [r[0] for r in conn.execute(text("SELECT id FROM customers ORDER BY id"))]
        products = [
            (str(r[0]), str(r[1] or ""))
            for r in conn.execute(
                text("SELECT id, COALESCE(family, category) FROM products WHERE is_active IS TRUE")
            )
        ]
    if not customers:
        logger.error("no customers seeded — run seed_postgres.py first")
        return 2
    if not products:
        logger.error("no active products — run seed_postgres.py first")
        return 2
    logger.info("simulating %d calls over %d customers", args.calls, len(customers))

    if args.purge:
        with db.engine.begin() as conn:
            removed = conn.execute(
                text("DELETE FROM offer_decisions WHERE mode = :m"), {"m": SIMULATED_MODE}
            ).rowcount
        logger.info("purged %d previously simulated rows", removed)

    intents = [
        (),
        ("balance_query",),
        ("product_faq",),
        ("upsell_opportunity",),
        ("payment_intent", "product_faq"),
    ]
    written = presented = positive = 0

    for i in range(args.calls):
        customer_id = rng.choice(customers)
        seen = rng.choice(intents)

        # Some callers name a product or read up on one. Without this the two
        # strongest in-call features are constant zero across the whole corpus,
        # and a model trained on it can only learn from sentiment noise — which
        # is exactly the AUC-0.55 result that makes a propensity model look
        # useless when the real problem is the sampling.
        mentioned: tuple[str, ...] = ()
        topics: tuple[str, ...] = ()
        if rng.random() < 0.18:
            mentioned = (rng.choice(products)[0],)
        if rng.random() < 0.30:
            family = rng.choice(products)[1]
            if family:
                topics = (f"{family}_policy",)

        live = CallSignals(
            channel="voice",
            intents_seen=seen,
            dominant_intent=seen[-1] if seen else None,
            sentiment_current=round(rng.uniform(-0.4, 0.9), 2),
            sentiment_trend=round(rng.uniform(-0.3, 0.3), 2),
            product_mentions=mentioned,
            kb_topics_queried=topics,
            commitment_secured=rng.random() < 0.75,
            ptp_captured=rng.random() < 0.5,
            customer_turns=rng.randint(3, 25),
        )

        result = engine.recommend(
            customer_id=customer_id,
            channel="voice",
            live=live,
            force_mode="live",
        )
        if not result.decision_id:
            continue
        written += 1

        # Retag as simulated. Done as an UPDATE rather than by passing a mode
        # through the engine, because the engine's mode is a real operational
        # setting and adding a fake value to it would leak this tool into
        # production config.
        with db.engine.begin() as conn:
            conn.execute(
                text("UPDATE offer_decisions SET mode = :m WHERE id = :id"),
                {"m": SIMULATED_MODE, "id": result.decision_id},
            )

        top = result.top
        if result.suppressed or top is None:
            continue

        # Not every approved offer gets spoken — the call ends, the customer
        # talks over it. Modelling that keeps the presented/approved ratio
        # realistic instead of a flat 100%.
        if rng.random() > 0.85:
            continue
        decisions.mark_presented(result.decision_id)
        presented += 1

        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT candidates FROM offer_decisions WHERE id = :id"),
                {"id": result.decision_id},
            ).scalar()
        vector = {}
        for candidate in row or []:
            if isinstance(candidate, dict) and candidate.get("productId") == top.product_id:
                vector = candidate.get("vector") or {}
                break
        if not vector:
            logger.warning("decision %s logged no vector — skipping label", result.decision_id)
            continue

        accepted = rng.random() < _accept_probability(vector)
        decisions.record_response(result.decision_id, "interested" if accepted else "declined")
        positive += int(accepted)

        if (i + 1) % 200 == 0:
            logger.info("  %d/%d calls", i + 1, args.calls)

    logger.info(
        "wrote %d decisions, %d presented, %d accepted (%.1f%% conversion)",
        written,
        presented,
        positive,
        100.0 * positive / presented if presented else 0.0,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
