#!/usr/bin/env python
"""Fit the propensity artifact from the offer decision log.

    python scripts/train_propensity.py --out models/propensity.json

Reads `offer_decisions` joined to `leads` outcomes, fits a regularised logistic
regression on the feature vectors logged at decision time, calibrates it, and
writes the JSON artifact `agent_core.reco.models.PropensityScorer` loads.

**Why the vectors come from the log and not from today's tables.** Rebuilding
features now for a decision made months ago leaks the outcome into the inputs:
the customer's DPD, lead count and offer history have all moved since, and
partly *because* of the decision being labelled. `engine._candidate_log` writes
the vector as it was; this trainer refuses rows that lack one rather than
silently reconstructing them.

**Labelling.** Positive = the customer said yes. In order of reliability:

    offer_decisions.response = 'interested'   → 1
    offer_decisions.response = 'declined'     → 0
    linked lead reached stage 'won'           → 1
    linked lead reached stage 'lost'          → 0

Rows still open, never presented, or suppressed are *excluded*, not zeroed. An
offer nobody made is not an offer that was refused, and training on it teaches
the model to reproduce the suppression rules it is supposed to be independent
of.

Plain Python, no numpy or sklearn: this artifact is loaded by a service on the
audio path of a live phone call, and the fewer things in that image the better.
A few thousand rows and 23 features fit in a second.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_core.reco import vectorize  # noqa: E402
from agent_core.reco.features import SCHEMA_VERSION  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("train_propensity")

# Below this the coefficients are noise dressed up as a model. The fallback to
# the rule scorer is not a failure state — it is the correct answer until there
# is enough signal to beat it.
MIN_SAMPLES = 200
MIN_POSITIVES = 30


def fetch_rows(limit: int) -> list[dict[str, Any]]:
    import db
    from sqlalchemy import text

    with db.engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text(
                    """
                    SELECT
                      d.id,
                      d.chosen_product_id,
                      d.candidates,
                      d.response,
                      d.presented,
                      d.created_at,
                      d.feature_schema_version,
                      l.stage AS lead_stage
                    FROM offer_decisions d
                    LEFT JOIN leads l ON l.id = d.lead_id
                    WHERE d.presented IS TRUE
                      AND d.chosen_product_id IS NOT NULL
                    ORDER BY d.created_at DESC
                    LIMIT :lim
                    """
                ),
                {"lim": limit},
            ).mappings()
        ]


def label(row: dict[str, Any]) -> int | None:
    """1 / 0 / None. None means "do not train on this row"."""
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
    # 'deferred', 'not_reached', still-open leads, no response yet — genuinely
    # unlabelled. Excluded rather than assumed negative.
    return None


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


def extract(rows: list[dict[str, Any]]) -> tuple[list[dict[str, float | None]], list[int], dict[str, int]]:
    """Vector + label per row, with a tally of why rows were dropped."""
    vectors: list[dict[str, float | None]] = []
    labels: list[int] = []
    skipped = {"unlabelled": 0, "no_vector": 0, "schema_mismatch": 0}

    for row in rows:
        y = label(row)
        if y is None:
            skipped["unlabelled"] += 1
            continue
        if (row.get("feature_schema_version") or SCHEMA_VERSION) != SCHEMA_VERSION:
            # A vector built under a different schema is a different quantity.
            skipped["schema_mismatch"] += 1
            continue

        chosen = row.get("chosen_product_id")
        vector = None
        for candidate in _as_list(row.get("candidates")):
            if isinstance(candidate, dict) and candidate.get("productId") == chosen:
                vector = candidate.get("vector")
                break
        if not isinstance(vector, dict) or not vector:
            skipped["no_vector"] += 1
            continue

        vectors.append({k: (None if v is None else float(v)) for k, v in vector.items()})
        labels.append(y)

    return vectors, labels, skipped


def column_means(vectors: list[dict[str, float | None]], names: list[str]) -> dict[str, float]:
    """Mean of the observed values per column, for imputation at serve time.

    0.5 when a column was never observed — the midpoint of every bounded
    feature in the vector, and the least opinionated thing to substitute.
    """
    means: dict[str, float] = {}
    for name in names:
        observed = [v[name] for v in vectors if v.get(name) is not None]
        means[name] = sum(observed) / len(observed) if observed else 0.5
    return means


def densify(
    vectors: list[dict[str, float | None]], names: list[str], means: dict[str, float]
) -> list[list[float]]:
    return [[float(v.get(n) if v.get(n) is not None else means[n]) for n in names] for v in vectors]


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def fit_logistic(
    X: list[list[float]],
    y: list[int],
    *,
    epochs: int = 3000,
    lr: float = 1.0,
    l2: float = 1e-3,
    seed: int = 7,
) -> tuple[list[float], float]:
    """Batch gradient descent with L2. Returns (coefficients, intercept).

    L2 is not optional here. With 23 correlated features and a few hundred
    rows, an unregularised fit produces confident coefficients on whichever
    feature happened to separate the training set, and those are exactly the
    ones that do not survive contact with next month's traffic.
    """
    n, d = len(X), len(X[0])
    rng = random.Random(seed)
    w = [rng.uniform(-0.01, 0.01) for _ in range(d)]
    b = 0.0

    # Class weighting: conversion is rare, and an unweighted fit on a 5%
    # positive rate learns to predict "no" and stops there.
    positives = sum(y) or 1
    negatives = (n - sum(y)) or 1
    pos_w = n / (2.0 * positives)
    neg_w = n / (2.0 * negatives)

    for _ in range(epochs):
        grad_w = [0.0] * d
        grad_b = 0.0
        for xi, yi in zip(X, y):
            p = _sigmoid(sum(a * c for a, c in zip(xi, w)) + b)
            weight = pos_w if yi == 1 else neg_w
            err = (p - yi) * weight
            for j in range(d):
                grad_w[j] += err * xi[j]
            grad_b += err
        for j in range(d):
            w[j] -= lr * (grad_w[j] / n + l2 * w[j])
        b -= lr * (grad_b / n)

    return w, b


def platt_calibrate(logits: list[float], y: list[int], *, epochs: int = 300, lr: float = 0.1) -> tuple[float, float]:
    """Fit p = sigmoid(a·logit + b) so the output is a usable probability.

    Class weighting made the raw scores good at *ranking* and useless as
    probabilities. Expected value multiplies p by an amount, so an uncalibrated
    p would put a confident rupee figure on a number that does not mean what it
    says.
    """
    a, b = 1.0, 0.0
    n = len(logits) or 1
    for _ in range(epochs):
        ga = gb = 0.0
        for z, yi in zip(logits, y):
            p = _sigmoid(a * z + b)
            err = p - yi
            ga += err * z
            gb += err
        a -= lr * ga / n
        b -= lr * gb / n
    return a, b


def brier(probabilities: list[float], y: list[int]) -> float:
    if not probabilities:
        return float("nan")
    return sum((p - yi) ** 2 for p, yi in zip(probabilities, y)) / len(probabilities)


def auc(probabilities: list[float], y: list[int]) -> float:
    """Rank-based AUC. 0.5 is a coin flip; below that the model is inverted."""
    pairs = sorted(zip(probabilities, y))
    positives = sum(y)
    negatives = len(y) - positives
    if not positives or not negatives:
        return float("nan")
    rank_sum = 0.0
    i = 0
    rank = 1
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg_rank = (rank + (rank + (j - i))) / 2.0
        for k in range(i, j + 1):
            if pairs[k][1] == 1:
                rank_sum += avg_rank
        rank += j - i + 1
        i = j + 1
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.getenv("RECO_MODEL_PATH", "models/propensity.json"))
    ap.add_argument("--limit", type=int, default=50_000)
    ap.add_argument("--holdout", type=float, default=0.2, help="fraction held out for metrics")
    ap.add_argument("--min-samples", type=int, default=MIN_SAMPLES)
    ap.add_argument(
        "--force",
        action="store_true",
        help="write the artifact even if it is below the sample floor or fails to beat a coin flip",
    )
    args = ap.parse_args()

    rows = fetch_rows(args.limit)
    logger.info("read %d presented decisions", len(rows))

    vectors, labels, skipped = extract(rows)
    logger.info(
        "usable %d (skipped: %d unlabelled, %d without a logged vector, %d schema mismatch)",
        len(vectors),
        skipped["unlabelled"],
        skipped["no_vector"],
        skipped["schema_mismatch"],
    )

    positives = sum(labels)
    if not args.force and (len(vectors) < args.min_samples or positives < MIN_POSITIVES):
        logger.error(
            "not enough signal: %d rows, %d positive (need %d / %d). "
            "The rule scorer remains the right answer — no artifact written.",
            len(vectors),
            positives,
            args.min_samples,
            MIN_POSITIVES,
        )
        return 2

    names = [n for n in vectorize.FEATURE_NAMES if any(n in v for v in vectors)]
    if not names:
        logger.error("no known feature names present in the logged vectors")
        return 2
    means = column_means(vectors, names)
    X = densify(vectors, names, means)

    # Split by recency, not at random: the question a holdout has to answer is
    # "does this generalise to next month", and a random split answers "does it
    # interpolate within the same month", which it always does.
    #
    # `fetch_rows` orders newest-first, so the holdout is the *head* of the
    # list and the training set is the older tail. Train on the past, score the
    # future — the other way round is a time machine.
    cut = max(1, int(len(X) * args.holdout))
    X_test, y_test = X[:cut], labels[:cut]
    X_train, y_train = X[cut:], labels[cut:]
    if not X_train or not sum(y_train):
        logger.warning("holdout split left no positive training rows — training on everything")
        X_train, y_train = X, labels
        X_test, y_test = X, labels

    w, b = fit_logistic(X_train, y_train)
    train_logits = [sum(a * c for a, c in zip(xi, w)) + b for xi in X_train]
    cal_a, cal_b = platt_calibrate(train_logits, y_train)

    test_logits = [sum(a * c for a, c in zip(xi, w)) + b for xi in X_test]
    test_p = [_sigmoid(cal_a * z + cal_b) for z in test_logits]
    model_auc = auc(test_p, y_test)
    model_brier = brier(test_p, y_test)
    base_rate = sum(y_test) / len(y_test) if y_test else float("nan")
    baseline_brier = brier([base_rate] * len(y_test), y_test)

    logger.info(
        "holdout: n=%d  AUC=%.3f  Brier=%.4f  (base-rate Brier=%.4f)",
        len(y_test),
        model_auc,
        model_brier,
        baseline_brier,
    )

    if not args.force and (math.isnan(model_auc) or model_auc <= 0.55):
        logger.error(
            "AUC %.3f does not beat a coin flip — refusing to write an artifact "
            "that would replace a rule scorer nobody has shown it is better than. "
            "Use --force to override.",
            model_auc,
        )
        return 3

    artifact = {
        "name": "propensity",
        "version": datetime.now(timezone.utc).strftime("%Y%m%d.%H%M%S"),
        "type": "logistic",
        "featureNames": names,
        "coefficients": [round(c, 6) for c in w],
        "intercept": round(b, 6),
        "means": {k: round(v, 6) for k, v in means.items()},
        "calibration": {"a": round(cal_a, 6), "b": round(cal_b, 6)},
        "trainedAt": datetime.now(timezone.utc).isoformat(),
        "nSamples": len(X_train),
        "vectorVersion": vectorize.VECTOR_VERSION,
        "featureSchemaVersion": SCHEMA_VERSION,
        "metrics": {
            "holdoutN": len(y_test),
            "auc": None if math.isnan(model_auc) else round(model_auc, 4),
            "brier": None if math.isnan(model_brier) else round(model_brier, 5),
            "baselineBrier": None if math.isnan(baseline_brier) else round(baseline_brier, 5),
            "baseRate": None if math.isnan(base_rate) else round(base_rate, 4),
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Atomic: a half-written artifact is one a running service may load.
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    tmp.replace(out)
    logger.info("wrote %s (version %s)", out, artifact["version"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
