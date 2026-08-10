#!/usr/bin/env python
"""Offline replay — would a different scorer have done better?

    python scripts/replay_offers.py --scorer propensity
    python scripts/replay_offers.py --scorer propensity --artifact models/candidate.json
    python scripts/replay_offers.py --scorer hybrid --rule-weight 0.3 --include-simulated

Re-ranks every logged decision with a candidate scorer and compares the result
to what was actually logged and to what the customer actually said.

**Everything is scored from the vectors logged at decision time.** Rebuilding
features from today's tables would leak the outcome into the inputs — DPD, lead
counts and offer history have all moved since, partly *because* of the decision
being evaluated — and would produce a model that looks excellent offline and
does nothing in production. Decisions logged without a vector are counted and
excluded, never reconstructed.

**How to read `replayConversion`.** This is replay (rejection-sampling)
evaluation: of the decisions where the candidate scorer would have picked the
same product that was actually offered, what fraction converted? Compared
against the conversion rate of everything that was offered.

That estimator is only unbiased if the logging policy explored randomly, and
this one does not — it is deterministic. So a lift here is *evidence*, not
proof, and the honest reading is "worth an A/B", never "ship it". `matched` is
printed alongside precisely so a lift computed on nine decisions is visibly a
lift computed on nine decisions.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_core.reco import config, models, scoring  # noqa: E402
from agent_core.reco.features import SCHEMA_VERSION  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("replay_offers")


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def fetch(limit: int, include_simulated: bool) -> list[dict[str, Any]]:
    import db
    from sqlalchemy import text

    modes = ["live", "shadow"] + (["simulated"] if include_simulated else [])
    with db.engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text(
                    """
                    SELECT d.id, d.chosen_product_id, d.candidates, d.response,
                           d.presented, d.created_at, d.suggested_amount,
                           d.feature_schema_version, d.recommender,
                           l.stage AS lead_stage
                    FROM offer_decisions d
                    LEFT JOIN leads l ON l.id = d.lead_id
                    WHERE d.mode = ANY(:modes)
                    ORDER BY d.created_at DESC
                    LIMIT :lim
                    """
                ),
                {"lim": limit, "modes": modes},
            ).mappings()
        ]


def outcome(row: dict[str, Any]) -> int | None:
    """1 accepted / 0 refused / None unlabelled."""
    response = (row.get("response") or "").strip().lower()
    if response == "interested":
        return 1
    if response == "declined":
        return 0
    stage = (row.get("lead_stage") or "").strip().lower()
    if stage == "won":
        return 1
    if stage == "lost":
        return 0
    return None


def build_ranker(args: argparse.Namespace):
    """Return ``(name, rank_fn)`` where rank_fn scores one logged vector."""
    weights = config.weights()

    if args.scorer == "rule":
        return "rule", (lambda vec: scoring.rule_score_from_vector(vec, weights)), None

    artifact = models.load_artifact(args.artifact or "models/propensity.json")
    if artifact is None:
        logger.error("no usable artifact at %s", args.artifact or "models/propensity.json")
        return None, None, None
    if artifact.feature_schema_version != SCHEMA_VERSION:
        logger.warning(
            "artifact was fitted on feature schema %s, this build emits %s — "
            "replay numbers are not comparable",
            artifact.feature_schema_version,
            SCHEMA_VERSION,
        )

    if args.scorer == "propensity":
        return (
            f"propensity@{artifact.version}",
            (lambda vec: artifact.comparable_score(artifact.predict(vec))),
            artifact,
        )

    w = args.rule_weight
    return (
        f"hybrid@{artifact.version}(rule={w:.2f})",
        (
            lambda vec: w * scoring.rule_score_from_vector(vec, weights)
            + (1.0 - w) * artifact.comparable_score(artifact.predict(vec))
        ),
        artifact,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scorer", choices=("rule", "propensity", "hybrid"), default="propensity")
    ap.add_argument("--artifact", default=None)
    ap.add_argument("--rule-weight", type=float, default=0.5)
    ap.add_argument("--limit", type=int, default=50_000)
    ap.add_argument("--min-score", type=float, default=None, help="defaults to RECO_MIN_SCORE")
    ap.add_argument("--include-simulated", action="store_true")
    ap.add_argument("--json", action="store_true", help="emit metrics as JSON only")
    args = ap.parse_args()

    name, rank, artifact = build_ranker(args)
    if rank is None:
        return 2

    floor = args.min_score if args.min_score is not None else config.policy().min_score
    rows = fetch(args.limit, args.include_simulated)

    total = len(rows)
    no_vector = 0
    scored_decisions = 0
    would_offer = 0
    matched = 0
    matched_positive = 0
    logged_presented = 0
    logged_positive = 0
    labelled_top1 = 0
    top1_correct = 0
    brier_terms: list[float] = []

    for row in rows:
        candidates = [
            c
            for c in _as_list(row.get("candidates"))
            if isinstance(c, dict) and isinstance(c.get("vector"), dict) and c["vector"]
        ]
        if not candidates:
            no_vector += 1
            continue
        scored_decisions += 1

        ranked = sorted(
            ((rank(c["vector"]), str(c.get("productId") or "")) for c in candidates),
            key=lambda pair: (-pair[0], pair[1]),
        )
        top_score, top_product = ranked[0]
        if top_score >= floor:
            would_offer += 1

        label = outcome(row)
        chosen = row.get("chosen_product_id")

        if row.get("presented") and chosen:
            logged_presented += 1
            if label is not None:
                logged_positive += label

        # Rejection sampling: only decisions where the candidate scorer agrees
        # with what was actually offered carry an observable outcome.
        if label is not None and chosen and top_score >= floor:
            if top_product == chosen:
                matched += 1
                matched_positive += label
            labelled_top1 += 1
            top1_correct += int(top_product == chosen and label == 1)

            if artifact is not None:
                vector = next(
                    (c["vector"] for c in candidates if c.get("productId") == chosen), None
                )
                if vector is not None:
                    p = artifact.predict(vector)
                    brier_terms.append((p - label) ** 2)

    baseline = (logged_positive / logged_presented) if logged_presented else None
    replayed = (matched_positive / matched) if matched else None

    metrics = {
        "scorer": name,
        "decisions": total,
        "scorable": scored_decisions,
        "skippedNoVector": no_vector,
        "coverage": round(would_offer / scored_decisions, 4) if scored_decisions else None,
        "matched": matched,
        "replayConversion": round(replayed, 4) if replayed is not None else None,
        "loggedPresented": logged_presented,
        "baselineConversion": round(baseline, 4) if baseline is not None else None,
        "lift": (
            round(replayed / baseline - 1.0, 4)
            if replayed is not None and baseline
            else None
        ),
        "precisionAt1": (
            round(top1_correct / labelled_top1, 4) if labelled_top1 else None
        ),
        "brier": round(sum(brier_terms) / len(brier_terms), 5) if brier_terms else None,
        "minScore": floor,
    }

    if args.json:
        print(json.dumps(metrics, indent=2))
        return 0

    print(f"\n  Replay — {name}")
    print(f"  {'-' * 58}")
    print(f"  decisions read            {metrics['decisions']}")
    print(f"  scorable (had a vector)   {metrics['scorable']}  (skipped {no_vector})")
    print(f"  coverage (>= {floor:.2f})        {_pct(metrics['coverage'])}")
    print(f"  matched the logged offer  {matched}")
    print(f"  replay conversion         {_pct(metrics['replayConversion'])}")
    print(f"  baseline conversion       {_pct(metrics['baselineConversion'])}  (n={logged_presented})")
    print(f"  lift                      {_pct(metrics['lift'], signed=True)}")
    print(f"  precision@1               {_pct(metrics['precisionAt1'])}")
    print(f"  Brier                     {metrics['brier'] if metrics['brier'] is not None else '—'}")
    if matched < 100:
        print(
            f"\n  NOTE: {matched} matched decisions is too few to conclude anything.\n"
            "  Treat the lift as a reason to run an A/B, not as a result."
        )
    print()
    return 0


def _pct(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value:+.1%}" if signed else f"{value:.1%}"


if __name__ == "__main__":
    raise SystemExit(main())
