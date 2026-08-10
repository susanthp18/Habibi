#!/usr/bin/env python
"""Latency benchmark for the offer engine.

    python scripts/bench_recommender.py --iterations 400
    python scripts/bench_recommender.py --scorer hybrid --concurrency 4

`recommend()` runs on the audio path of a live phone call. The budget is 150ms
at p99 (Part 6 of upsell_engine_plan.md) — not because 200ms is catastrophic,
but because it lands inside the silence after the customer stops speaking, and
that silence is already spent on ASR finalisation and the LLM's first token.

Reports p50/p95/p99 and a per-stage breakdown, because "it got slower" is not
an actionable finding: the fix for a slow feature build (add an index) and a
slow eligibility veto (hoist the customer-level reads out of the loop) are
entirely different, and the second one is a bug this engine has already had.

Runs against whatever database `DATABASE_URL` points at, so the numbers are
only meaningful on hardware and data volumes you care about. Read the p99 as a
regression signal, not as a production SLO measured in a container on a laptop.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

P99_BUDGET_MS = 150.0


def _percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile. No interpolation: with a few hundred samples,
    interpolating invents a latency nobody observed."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q * len(ordered) + 0.5)) - 1))
    return ordered[index]


def _summary(name: str, values: list[float]) -> dict[str, float]:
    return {
        "stage": name,
        "n": len(values),
        "mean": round(statistics.fmean(values), 2) if values else float("nan"),
        "p50": round(_percentile(values, 0.50), 2),
        "p95": round(_percentile(values, 0.95), 2),
        "p99": round(_percentile(values, 0.99), 2),
        "max": round(max(values), 2) if values else float("nan"),
    }


def _stage_breakdown(customer_ids: list[str], iterations: int, rng: random.Random) -> list[dict]:
    """Time the layers separately, using the same code the engine calls."""
    import capture
    import db

    from agent_core.reco import candidates as candidates_mod, config, features as features_mod
    from agent_core.reco.scoring import build_scorer

    policy = config.policy()
    scorer = build_scorer(config.scorer_name(), config.weights())

    feature_ms: list[float] = []
    candidate_ms: list[float] = []
    veto_ms: list[float] = []
    score_ms: list[float] = []

    for _ in range(iterations):
        customer_id = rng.choice(customer_ids)

        t0 = time.perf_counter()
        feats, signals = features_mod.build_features(customer_id, channel="voice")
        feature_ms.append((time.perf_counter() - t0) * 1000)

        with db.engine.connect() as conn:
            t0 = time.perf_counter()
            pool, _ = candidates_mod.generate(
                conn,
                features=feats,
                channel="voice",
                decline_cooldown_days=policy.decline_cooldown_days,
                family_cooldown_days=policy.family_cooldown_days,
            )
            candidate_ms.append((time.perf_counter() - t0) * 1000)

            t0 = time.perf_counter()
            facts = capture.customer_eligibility_facts(conn, customer_id)
            for candidate in pool:
                capture.evaluate_product_eligibility(
                    conn,
                    customer_id=customer_id,
                    product_id=candidate.product_id,
                    channel="voice",
                    facts=facts,
                )
            veto_ms.append((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        scorer.score(feats, signals, pool)
        score_ms.append((time.perf_counter() - t0) * 1000)

    return [
        _summary("features (L1)", feature_ms),
        _summary("candidates (L2)", candidate_ms),
        _summary("eligibility veto (L3)", veto_ms),
        _summary("scoring (L4)", score_ms),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iterations", type=int, default=300)
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--scorer", default=None, help="overrides RECO_SCORER")
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--no-stages", action="store_true", help="skip the per-stage breakdown")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.scorer:
        os.environ["RECO_SCORER"] = args.scorer
    # Shadow mode does the full pipeline and logs, which is the expensive path
    # and the one that has to fit the budget. Measuring `off` would measure an
    # early return.
    os.environ.setdefault("RECO_MODE", "shadow")

    import db
    from sqlalchemy import text

    from agent_core.reco import config, engine
    from agent_core.reco.features import CallSignals

    with db.engine.connect() as conn:
        customer_ids = [r[0] for r in conn.execute(text("SELECT id FROM customers ORDER BY id"))]
    if not customer_ids:
        print("no customers seeded — run seed_postgres.py first", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    live = CallSignals(
        channel="voice",
        intents_seen=("upsell_opportunity",),
        dominant_intent="upsell_opportunity",
        sentiment_current=0.4,
        commitment_secured=True,
        customer_turns=12,
    )

    def _once() -> float:
        customer_id = rng.choice(customer_ids)
        t0 = time.perf_counter()
        engine.recommend(customer_id=customer_id, channel="voice", live=live)
        return (time.perf_counter() - t0) * 1000

    # Warm the connection pool and the import graph. Including cold starts would
    # measure Python's first-call cost, which a long-lived worker pays once.
    for _ in range(args.warmup):
        _once()

    if args.concurrency > 1:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            timings = list(pool.map(lambda _: _once(), range(args.iterations)))
    else:
        timings = [_once() for _ in range(args.iterations)]

    end_to_end = _summary("recommend() end to end", timings)
    stages = [] if args.no_stages else _stage_breakdown(customer_ids, min(args.iterations, 150), rng)

    within_budget = end_to_end["p99"] <= P99_BUDGET_MS
    report = {
        "scorer": config.scorer_name(),
        "mode": config.mode(),
        "concurrency": args.concurrency,
        "customers": len(customer_ids),
        "endToEnd": end_to_end,
        "stages": stages,
        "budgetMs": P99_BUDGET_MS,
        "withinBudget": within_budget,
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if within_budget else 1

    print(
        f"\n  Recommender latency — scorer={report['scorer']} mode={report['mode']} "
        f"concurrency={args.concurrency}"
    )
    print(f"  {'-' * 68}")
    header = f"  {'stage':26} {'n':>5} {'mean':>8} {'p50':>8} {'p95':>8} {'p99':>8} {'max':>8}"
    print(header)
    for row in [end_to_end] + stages:
        print(
            f"  {row['stage']:26} {row['n']:>5} {row['mean']:>8.2f} {row['p50']:>8.2f} "
            f"{row['p95']:>8.2f} {row['p99']:>8.2f} {row['max']:>8.2f}"
        )
    verdict = "WITHIN" if within_budget else "OVER"
    print(
        f"\n  p99 {end_to_end['p99']:.2f}ms against a {P99_BUDGET_MS:.0f}ms budget — {verdict}\n"
    )
    return 0 if within_budget else 1


if __name__ == "__main__":
    raise SystemExit(main())
