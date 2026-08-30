#!/usr/bin/env python
"""Fit the Layer 1 estimators from the treatment decision log.

    .venv/Scripts/python scripts/train_treatment_models.py --target reach
    .venv/Scripts/python scripts/train_treatment_models.py --target all --include-simulated
    .venv/Scripts/python scripts/train_treatment_models.py --target uplift --min-control 500

Three targets, three quite different labelling problems, and the differences
are where all the danger is.

**reach** — did the attempt reach a person? Positive on direct evidence of
contact (``reached`` / ``ptp`` / ``refused``); negative on ``no_answer`` /
negative on ``no_answer`` / ``undeliverable``. Only *enacted* decisions on a
the outcome rather than about whether the phone was answered. Only enacted
decisions on a channel qualify, and ``cancelled`` / ``superseded`` are excluded
rather than zeroed: an attempt the executor withdrew is not an attempt that
went unanswered, and training on it teaches our own suppression rules.

**timing** — would this account have resolved on its own, before the moment we
planned to act? Fitted only on decisions where nothing was done: ``wait``,
suppressed, and control-arm rows. That restriction is the whole validity of the
label. Fitting it on treated rows would measure "resolved after we contacted
them", which is the opposite quantity, and the resulting decay term would tell
the engine that acting later is *better* on exactly the borrowers it helped.

**uplift** — τ(action, x), and it is fitted as a T-learner: one logistic on the
treated arm, one on the randomised control arm, τ = the difference. Both halves
go in one artifact fitted on one extraction, because a τ computed from halves
trained on different vintages of the book is a calendar effect wearing a
treatment effect's name.

Discipline carried verbatim from ``train_propensity.py``, for the same reasons:

* **The vectors come from the log, never rebuilt.** Reconstructing features now
  for a decision made in March leaks the outcome into the inputs — the DPD, the
  touch counts and the promise history have all moved since, and they moved
  partly *because* of the decision being labelled. Rows without a logged vector
  are refused rather than reconstructed.
* **Plain Python. No numpy, no sklearn.** This artifact is loaded by a service
  on the audio path of a live call, and the fewer things in that image the
  better. A few thousand rows and thirty features fit in a second.
* **Scorer-derived columns are never features.** ``p_reach``, ``p_resolve`` and
  ``cost`` are outputs of the very priors these models replace; a reach model
  fitted with ``p_reach`` in its inputs learns to copy ``REACH_PRIOR`` and
  reports an excellent holdout score for doing so.

Simulated rows are excluded by default. Include them with
``--include-simulated`` to exercise the pipeline before real traffic exists, and
note that every artifact so fitted records ``"corpus": "simulated"`` so nothing
downstream can mistake it for a model of a real book.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env_loader import load_env

load_env()

import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from agent_core.treatment import models  # noqa: E402
from agent_core.treatment.features import SCHEMA_VERSION  # noqa: E402
from agent_core.treatment.segments import SEGMENT_VERSION  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("train_treatment")

TARGETS = ("reach", "timing", "uplift")

#: Outcomes that say an attempt reached a person, and those that say it did not.
#: Everything else is excluded rather than assigned a class.
#:
#: ``paid`` is deliberately in neither. A payment is evidence about the
#: *outcome*, not about whether anybody answered the phone: a borrower who was
#: going to pay anyway pays whether the call connected or not, so counting it as
#: a reach positive pours the entire self-cure population into the reach label
#: and the model learns to predict payment instead. That was measurable — the
#: first fit on this corpus scored an AUC of 0.504 with ``paid`` included, on a
#: simulated book that had real, learnable reach heterogeneity in it.
REACHED = frozenset({"reached", "ptp", "refused"})
NOT_REACHED = frozenset({"no_answer", "undeliverable"})

CONTROL_ARM = "null_treatment"


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _lift_timeout(conn: Any) -> None:
    """Take this connection out of the API's statement budget.

    ``db.engine`` sets ``statement_timeout`` to fifteen seconds because it is
    sized for a request on the audio path of a live call. These scripts are
    batch jobs that read the whole corpus once — eighteen thousand decisions,
    each carrying a feature vector per scored action — and fifteen seconds is
    not a budget, it is a guarantee of failure at any real book size.

    Session-scoped and only on this connection, so nothing the service does
    inherits it. The same reasoning as the corpus generator's purge.
    """
    conn.execute(text("SET statement_timeout = 0"))


def _rows(conn: Any, *, include_simulated: bool) -> list[dict[str, Any]]:
    _lift_timeout(conn)
    modes = ["shadow", "live"] + (["simulated"] if include_simulated else [])
    return [
        dict(r)
        for r in conn.execute(
            text(
                """
                SELECT id, customer_id, account_id, variant, mode,
                       chosen_action, chosen_channel, enacted, outcome,
                       scheduled_at, created_at, candidates, features
                FROM treatment_decisions
                WHERE mode = ANY(:modes)
                  AND feature_schema_version = :schema
                ORDER BY created_at ASC
                """
            ),
            {"modes": modes, "schema": SCHEMA_VERSION},
        ).mappings()
    ]


def _vector_for(row: dict[str, Any]) -> dict[str, float | None] | None:
    """The vector logged for the action actually chosen.

    ``candidates`` holds one entry per scored action, each with the vector as
    it was at decision time. The chosen action's entry is the only one whose
    outcome we observe, so it is the only one that can be labelled — the rest
    are the counterfactual, and they belong to off-policy evaluation rather
    than to supervised training.
    """
    candidates = row.get("candidates")
    if not isinstance(candidates, list):
        return None
    chosen = str(row.get("chosen_action") or "")
    for entry in candidates:
        if not isinstance(entry, dict) or str(entry.get("action")) != chosen:
            continue
        vec = entry.get("vector")
        return vec if isinstance(vec, dict) else None
    return None


def _label_reach(row: dict[str, Any]) -> int | None:
    if not row.get("enacted") or not row.get("chosen_channel"):
        return None
    outcome = str(row.get("outcome") or "")
    if outcome in REACHED:
        return 1
    if outcome in NOT_REACHED:
        return 0
    return None


def _label_timing(row: dict[str, Any]) -> int | None:
    """Did this account resolve with nothing done to it?

    Restricted to decisions that produced no action at all. That restriction is
    the label's entire claim to validity, and it is also why this model will
    always have less data than the other two: most decisions do something.
    """
    acted = bool(row.get("enacted")) and str(row.get("chosen_action") or "") != "wait"
    if acted:
        return None
    outcome = str(row.get("outcome") or "")
    if outcome in {"paid", "ptp"}:
        return 1
    # An un-enacted decision on a case that stayed open is a genuine negative:
    # nothing was done and nothing happened. ``superseded`` is not — the case
    # was re-decided, so we never observed the counterfactual to its end.
    # ``unresolved`` is the label this model exists for: nothing was done and
    # the borrower did not pay inside the observation window.
    if outcome in {"unresolved", "cancelled"}:
        return 0
    if outcome in {"no_answer", "refused", "undeliverable", "reached"}:
        return 0
    return None


def _label_cure(row: dict[str, Any]) -> int | None:
    outcome = str(row.get("outcome") or "")
    if outcome in {"paid", "ptp"}:
        return 1
    if outcome in {
        "no_answer",
        "refused",
        "undeliverable",
        "reached",
        "cancelled",
        "unresolved",
    }:
        return 0
    return None


# ---------------------------------------------------------------------------
# Fitting — lifted from train_propensity.py, same reasoning
# ---------------------------------------------------------------------------


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-min(60.0, x)))
    e = math.exp(max(-60.0, x))
    return e / (1.0 + e)


def fit_logistic(
    X: list[list[float]],
    y: list[int],
    *,
    epochs: int = 2000,
    lr: float = 1.0,
    l2: float = 1e-3,
    seed: int = 7,
) -> tuple[list[float], float]:
    """Batch gradient descent with L2. Returns (coefficients, intercept).

    L2 is not optional. With thirty correlated features and a few hundred rows,
    an unregularised fit produces confident coefficients on whichever feature
    happened to separate the training set, and those are precisely the ones
    that do not survive contact with next month's traffic.
    """
    n, d = len(X), len(X[0])
    rng = random.Random(seed)
    w = [rng.uniform(-0.01, 0.01) for _ in range(d)]
    b = 0.0

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


def platt_calibrate(
    logits: list[float], y: list[int], *, epochs: int = 300, lr: float = 0.1
) -> tuple[float, float]:
    """Fit p = sigmoid(a·logit + b) so the output is a usable probability.

    Class weighting above made the raw scores good at *ranking* and useless as
    probabilities. Expected value multiplies this by a rupee amount, so an
    uncalibrated p puts a confident figure on a number that does not mean what
    it says.
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


def auc(probabilities: list[float], y: list[int]) -> float:
    """Rank-based AUC. 0.5 is a coin flip; below it the model is inverted."""
    pairs = sorted(zip(probabilities, y))
    positives = sum(y)
    negatives = len(y) - positives
    if not positives or not negatives:
        return float("nan")
    rank_sum = 0.0
    i = rank = 0
    rank = 1
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg = (rank + (rank + (j - i))) / 2.0
        for k in range(i, j + 1):
            if pairs[k][1] == 1:
                rank_sum += avg
        rank += j - i + 1
        i = j + 1
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def brier(probabilities: list[float], y: list[int]) -> float:
    if not probabilities:
        return float("nan")
    return sum((p - yi) ** 2 for p, yi in zip(probabilities, y)) / len(probabilities)


def logloss(probabilities: list[float], y: list[int]) -> float:
    """Mean negative log likelihood. Lower is better; the gate's scoring rule.

    Preferred to Brier for the segment gate because it is the loss the halves
    were actually fitted under, so "the finer model fits better" is measured in
    the same units the fit optimised. Clamped away from 0 and 1: one confident
    wrong prediction would otherwise return infinity and take the whole
    comparison with it.
    """
    if not probabilities:
        return float("nan")
    total = 0.0
    for p, yi in zip(probabilities, y):
        q = min(1.0 - 1e-9, max(1e-9, p))
        total += -(math.log(q) if yi else math.log(1.0 - q))
    return total / len(probabilities)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _design(
    samples: list[tuple[dict[str, float | None], int]], names: tuple[str, ...]
) -> tuple[list[list[float]], list[int], dict[str, float]]:
    """Feature matrix with mean imputation. Absent is filled, never zeroed."""
    means: dict[str, float] = {}
    for name in names:
        seen = [
            float(v[name])
            for v, _ in samples
            if v.get(name) is not None
        ]
        means[name] = sum(seen) / len(seen) if seen else 0.0
    X = [
        [float(v[n]) if v.get(n) is not None else means[n] for n in names]
        for v, _ in samples
    ]
    y = [label for _, label in samples]
    return X, y, means


def _dispersions(X: list[list[float]], means: list[float]) -> list[float]:
    """True per-feature standard deviation, unfloored.

    Distinct from :func:`_scales`, which floors at one so standardisation
    cannot divide by a near-zero. That floor is right for fitting and wrong for
    reporting: a feature that never varied in training has a dispersion of zero,
    and saying so lets a drift monitor report "not measurable" instead of
    dividing by the floor and calling the result fifty sigmas.
    """
    if not X:
        return [0.0] * len(means)
    out: list[float] = []
    for j, mu in enumerate(means):
        var = sum((row[j] - mu) ** 2 for row in X) / len(X)
        out.append(var ** 0.5)
    return out


def _scales(X: list[list[float]], means: list[float]) -> list[float]:
    """Per-feature standard deviation, floored at one.

    Without this the fit does not converge and the failure is silent. The
    treatment vector is raw — ``exposure`` is thousands of rupees, ``risk_score``
    is hundreds, ``intrusiveness`` is 0.15 — and at a learning rate that suits
    the small columns the large ones produce gradients that saturate every
    sigmoid on the first pass. The model then predicts a constant, and a
    constant predictor scores an AUC of exactly 0.500, which reads like
    "these features carry no signal" rather than "this fit diverged".

    ``reco.vectorize`` avoids the problem by normalising at vectorisation time.
    This vector deliberately does not: raw values are what a decision log should
    contain, because ``exposure=4503.96`` is inspectable a year later and
    ``0.31`` is not. So the scaling lives here, and :func:`_unscale` folds it
    back into the coefficients afterwards so the artifact still consumes raw
    vectors and the serving path never has to know.
    """
    n = len(X) or 1
    out: list[float] = []
    for j, mu in enumerate(means):
        var = sum((row[j] - mu) ** 2 for row in X) / n
        sd = math.sqrt(var)
        # A constant column has no scale and no information; leaving it at 1.0
        # makes its standardised value 0 for every row, so it contributes
        # nothing rather than dividing by nothing.
        out.append(sd if sd > 1e-9 else 1.0)
    return out


def _standardise(
    X: list[list[float]], means: list[float], scales: list[float]
) -> list[list[float]]:
    return [
        [(x - mu) / sd for x, mu, sd in zip(row, means, scales)] for row in X
    ]


def _unscale(
    w: list[float], b: float, means: list[float], scales: list[float]
) -> tuple[list[float], float]:
    """Fold standardisation back into the coefficients.

    ``logit = b + Σ wⱼ·(xⱼ − μⱼ)/σⱼ`` is the same line as
    ``logit = (b − Σ wⱼμⱼ/σⱼ) + Σ (wⱼ/σⱼ)·xⱼ``, so the artifact can carry the
    second form and score a raw vector directly. One transformation here beats
    shipping the scaling parameters and hoping every consumer applies them.
    """
    raw_w = [wj / sd for wj, sd in zip(w, scales)]
    raw_b = b - sum(wj * mu / sd for wj, mu, sd in zip(w, means, scales))
    return raw_w, raw_b


def _split(n: int, holdout: float, seed: int) -> tuple[list[int], list[int]]:
    idx = list(range(n))
    random.Random(seed).shuffle(idx)
    cut = max(1, int(n * (1.0 - holdout)))
    return idx[:cut], idx[cut:]


def _artifact(
    *,
    target: str,
    names: tuple[str, ...],
    weights: list[float],
    intercept: float,
    means: dict[str, float],
    cal: tuple[float, float],
    metrics: dict[str, Any],
    n: int,
    corpus: str,
    stdevs: dict[str, float] | None = None,
    control: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": f"treatment_{target}",
        "target": target,
        "type": "logistic",
        "version": datetime.now(timezone.utc).strftime("%Y%m%d%H%M"),
        "trainedAt": datetime.now(timezone.utc).isoformat(),
        "featureNames": list(names),
        "coefficients": [round(w, 8) for w in weights],
        "intercept": round(intercept, 8),
        "means": {k: round(v, 8) for k, v in means.items()},
        # Recorded so drift is measurable in standard deviations rather than in
        # raw units, which are not comparable across features.
        #
        # These are the *true* dispersions, not the scales used for
        # standardisation. Those are floored at 1.0 for numerical safety, and a
        # feature with no variance at training time would come back with a
        # stdev of 1.0 — against which any shift at all reads as many sigmas.
        # A drift monitor reported ``planned_delay_hours`` at +57.9σ that way,
        # which is not a finding about a book, it is a floor being divided by.
        "stdevs": {k: round(v, 8) for k, v in (stdevs or {}).items()},
        "calibration": {"a": round(cal[0], 8), "b": round(cal[1], 8)},
        "metrics": metrics,
        "nSamples": n,
        "vectorVersion": models.VECTOR_VERSION,
        "featureSchemaVersion": SCHEMA_VERSION,
        # Recorded on the artifact, not just in a log line. A model fitted on a
        # synthetic book must announce that fact everywhere it travels.
        "corpus": corpus,
    }
    if control:
        out.update(control)
    return out


def train_one(
    samples: list[tuple[dict[str, float | None], int]],
    *,
    target: str,
    holdout: float,
    seed: int,
    corpus: str,
) -> dict[str, Any] | None:
    if len(samples) < 40:
        logger.error("%s: only %d labelled rows — refusing to fit", target, len(samples))
        return None
    names = models.trainable_features(
        {k for vec, _ in samples for k in vec}
    )
    if not names:
        logger.error("%s: no trainable features in the logged vectors", target)
        return None

    X, y, means = _design(samples, names)
    train_idx, test_idx = _split(len(X), holdout, seed)
    if not test_idx:
        logger.error("%s: holdout is empty — raise --holdout or gather more rows", target)
        return None

    mu = [means[n] for n in names]
    scales = _scales(X, mu)
    Z = _standardise(X, mu, scales)
    zw, zb = fit_logistic([Z[i] for i in train_idx], [y[i] for i in train_idx], seed=seed)
    w, b = _unscale(zw, zb, mu, scales)

    logits = [sum(a * c for a, c in zip(X[i], w)) + b for i in train_idx]
    cal = platt_calibrate(logits, [y[i] for i in train_idx])

    probs = [
        _sigmoid(cal[0] * (sum(a * c for a, c in zip(X[i], w)) + b) + cal[1])
        for i in test_idx
    ]
    truth = [y[i] for i in test_idx]
    metrics = {
        "baseRate": round(sum(y) / len(y), 6),
        "holdoutAuc": round(auc(probs, truth), 4),
        "holdoutBrier": round(brier(probs, truth), 6),
        "holdoutN": len(test_idx),
    }
    logger.info(
        "%s: n=%d base=%.3f auc=%.3f brier=%.4f",
        target,
        len(X),
        metrics["baseRate"],
        metrics["holdoutAuc"],
        metrics["holdoutBrier"],
    )
    return _artifact(
        target=target,
        names=names,
        weights=w,
        intercept=b,
        means=means,
        cal=cal,
        metrics=metrics,
        n=len(X),
        corpus=corpus,
        stdevs=dict(zip(names, _dispersions(X, mu))),
    )


def train_uplift(
    treated: list[tuple[dict[str, float | None], int]],
    control: list[tuple[dict[str, float | None], int]],
    *,
    holdout: float,
    seed: int,
    corpus: str,
    min_control: int,
    segment_ladder: bool = True,
) -> dict[str, Any] | None:
    """T-learner: one fit per arm, τ is the difference.

    Both halves share one feature list and one imputation, because a τ computed
    from two models that disagree about what "unknown" means is not a
    difference of comparable quantities.
    """
    if len(control) < min_control:
        logger.error(
            "uplift: control arm holds %d rows (need %d). τ is the difference of two "
            "noisy quantities — fitting it here would ship confident noise, which is "
            "strictly worse than the priors because it looks learned.",
            len(control),
            min_control,
        )
        return None
    if len(treated) < 40:
        logger.error("uplift: only %d treated rows — refusing to fit", len(treated))
        return None

    names = models.trainable_features(
        {k for vec, _ in (treated + control) for k in vec}
    )
    X_t, y_t, means = _design(treated, names)
    X_c = [
        [float(v[n]) if v.get(n) is not None else means[n] for n in names]
        for v, _ in control
    ]
    y_c = [label for _, label in control]

    # One scaling for both halves. Two would make the coefficients
    # incomparable, and τ is a difference of the two predictions.
    mu = [means[n] for n in names]
    scales = _scales(X_t + X_c, mu)
    Z_t = _standardise(X_t, mu, scales)
    Z_c = _standardise(X_c, mu, scales)

    t_idx, t_test = _split(len(X_t), holdout, seed)
    zw_t, zb_t = fit_logistic([Z_t[i] for i in t_idx], [y_t[i] for i in t_idx], seed=seed)
    w_t, b_t = _unscale(zw_t, zb_t, mu, scales)
    zw_c, zb_c = fit_logistic(Z_c, y_c, seed=seed + 1)
    w_c, b_c = _unscale(zw_c, zb_c, mu, scales)

    logits = [sum(a * c for a, c in zip(X_t[i], w_t)) + b_t for i in t_idx]
    cal = platt_calibrate(logits, [y_t[i] for i in t_idx])

    probs = [
        _sigmoid(cal[0] * (sum(a * c for a, c in zip(X_t[i], w_t)) + b_t) + cal[1])
        for i in t_test
    ]
    truth = [y_t[i] for i in t_test]

    treated_rate = sum(y_t) / len(y_t)
    control_rate = sum(y_c) / len(y_c)
    metrics = {
        "baseRate": round(treated_rate, 6),
        "controlRate": round(control_rate, 6),
        # The headline number, and the only one that is causal: the average
        # treatment effect measured against the randomised arm.
        "ate": round(treated_rate - control_rate, 6),
        "holdoutAuc": round(auc(probs, truth), 4) if t_test else None,
        "holdoutN": len(t_test),
    }
    logger.info(
        "uplift: treated=%d control=%d cure_treated=%.3f cure_control=%.3f ATE=%+.3f",
        len(X_t),
        len(X_c),
        treated_rate,
        control_rate,
        metrics["ate"],
    )
    if metrics["ate"] <= 0:
        logger.warning(
            "uplift: measured ATE is %+.3f — on this corpus the logging policy is "
            "not beating no-treatment at all. The artifact is still written so the "
            "finding is inspectable, but promoting it would be promoting a policy "
            "the control arm says does not work.",
            metrics["ate"],
        )

    control_block = {
        "controlArm": CONTROL_ARM,
        "controlN": len(X_c),
        "controlCoefficients": [round(w, 8) for w in w_c],
        "controlIntercept": round(b_c, 8),
    }

    if segment_ladder:
        promoted, report = fit_segments(
            treated,
            control,
            names=names,
            means=means,
            scales=scales,
            cal=cal,
            population_ate=treated_rate - control_rate,
            holdout=holdout,
            seed=seed,
        )
        considered = [r for r in report if r.get("verdict") != "skipped"]
        logger.info(
            "granularity ladder: %d strata had the power to be tested, %d beat the "
            "population model. The other %d keep the pooled τ, which is the ladder "
            "working rather than the ladder failing.",
            len(considered),
            len(promoted),
            len(considered) - len(promoted),
        )
        for row in report:
            if row.get("verdict") == "promoted":
                logger.info(
                    "  promoted %-24s %-38s ATE %+.3f (pop %+.3f, z=%.1f) logloss %+.4f",
                    row["segment"], row.get("label", ""), row["ate"],
                    treated_rate - control_rate, row["z"], row["holdoutLift"],
                )
            elif row.get("verdict") == "rejected":
                logger.info(
                    "  rejected %-24s %s", row["segment"], row.get("reason"),
                )
        control_block["segments"] = promoted
        control_block["segmentVersion"] = SEGMENT_VERSION
        control_block["shrinkageK"] = models.DEFAULT_SHRINKAGE_K
        metrics["segmentLadder"] = report
        metrics["segmentsPromoted"] = len(promoted)

    return _artifact(
        target="uplift",
        names=names,
        weights=w_t,
        intercept=b_t,
        means=means,
        cal=cal,
        metrics=metrics,
        n=len(X_t),
        corpus=corpus,
        stdevs=dict(zip(names, _dispersions(X_t + X_c, mu))),
        control=control_block,
    )


# ---------------------------------------------------------------------------
# The granularity ladder — §9's middle rung
# ---------------------------------------------------------------------------

#: Treated rows a stratum needs before it is worth fitting at all. The control
#: side has its own, stricter floor in ``models.MIN_SEGMENT_CONTROL_N``.
MIN_SEGMENT_TREATED_N = 150

#: Family-wise error rate for the heterogeneity gate. 0.05 two-sided is the
#: conventional choice and the right conventionality to borrow: this number
#: will be read by a risk committee, and "we used the usual threshold" is a
#: shorter conversation than a bespoke one.
HETEROGENEITY_ALPHA = 0.05


def heterogeneity_z(strata_tested: int) -> float:
    """The z the gate demands, Bonferroni-corrected for how many strata were tried.

    Thirty candidate strata tested at an uncorrected 5% produce about one and a
    half spurious "this segment is different" findings *by construction*, and
    each one would ship a segment model fitted to noise. The ladder exists to
    stop confident noise; a gate that manufactures its own would be a poor place
    to leave a multiple-comparisons hole.

    Correcting on the number actually tested rather than on the size of the
    partition matters: most strata never reach this gate because they are
    underpowered, and charging the correction for cells nobody looked at would
    make the threshold depend on the banding rather than on the evidence.
    """
    tested = max(1, int(strata_tested))
    return NormalDist().inv_cdf(1.0 - HETEROGENEITY_ALPHA / (2.0 * tested))


def _predict(row: list[float], weights: list[float], intercept: float,
             cal: tuple[float, float]) -> float:
    return _sigmoid(cal[0] * (sum(a * c for a, c in zip(row, weights)) + intercept) + cal[1])


def _ate_stderr(p_t: float, n_t: int, p_c: float, n_c: int) -> float:
    """SE of a difference of two independent proportions."""
    if n_t <= 0 or n_c <= 0:
        return float("inf")
    return math.sqrt(p_t * (1 - p_t) / n_t + p_c * (1 - p_c) / n_c)


def fit_segments(
    treated: list[tuple[dict[str, float | None], int]],
    control: list[tuple[dict[str, float | None], int]],
    *,
    names: tuple[str, ...],
    means: dict[str, float],
    scales: list[float],
    cal: tuple[float, float],
    population_ate: float,
    holdout: float,
    seed: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fit a T-learner per stratum and keep only the ones that earned their place.

    Returns ``(promoted, report)`` — the map that goes into the artifact, and a
    row per candidate stratum whether it passed or not. The report is the point
    as much as the map is: "we tried twenty-four segments and two beat the
    population" is the finding, and an artifact that silently contained two
    segments would tell you the first half of it.

    **Three gates, and all three must pass.**

    *Power.* Enough treated and control rows to estimate a difference at all.
    Skipped strata are reported as skipped, never as failed — those are
    different facts about a book.

    *Heterogeneity.* The segment's measured ATE must sit more than
    :data:`HETEROGENEITY_Z` standard errors from the population ATE. This is the
    causal gate and the load-bearing one: it is backed by the randomisation
    rather than by a model, so passing it means this stratum genuinely responds
    differently, not that a fit found a pattern in it.

    *Holdout fit.* Both halves must predict held-out cure labels better than the
    population halves do on the same rows, measured in log loss.

    Fit-quality alone is not enough, which is why the causal gate is separate. A
    segment model will nearly always fit its own stratum better than a pooled
    model does — it has fewer rows to explain and its own intercept. That is
    overfitting, and on a difference of two noisy quantities it is exactly how
    confident noise gets shipped.
    """
    from agent_core.treatment import segments as seg

    # One global train/holdout split, and every segment inherits it. Splitting
    # within each segment instead would put a row in that segment's holdout
    # while the comparison population model — fitted on the global training set
    # — had already seen it, so the population half would be graded on rows it
    # was trained on and the segment half on rows it was not. That biases the
    # gate toward the population model, which is the safe direction but is still
    # a rigged comparison, and a rigged comparison in the safe direction is how
    # a genuinely better segment model never gets found.
    t_train_idx, t_test_idx = _split(len(treated), holdout, seed)
    c_train_idx, c_test_idx = _split(len(control), holdout, seed + 101)
    t_fold = {i: "train" for i in t_train_idx}
    t_fold.update({i: "test" for i in t_test_idx})
    c_fold = {i: "train" for i in c_train_idx}
    c_fold.update({i: "test" for i in c_test_idx})

    buckets: dict[str, dict[str, list[Any]]] = {}
    for i, (vec, label) in enumerate(treated):
        entry = buckets.setdefault(
            seg.key_for(vec), {"t": [], "c": [], "t_train": [], "t_test": [], "c_train": [], "c_test": []}
        )
        entry["t"].append((vec, label))
        entry[f"t_{t_fold[i]}"].append((vec, label))
    for i, (vec, label) in enumerate(control):
        entry = buckets.setdefault(
            seg.key_for(vec), {"t": [], "c": [], "t_train": [], "t_test": [], "c_train": [], "c_test": []}
        )
        entry["c"].append((vec, label))
        entry[f"c_{c_fold[i]}"].append((vec, label))

    mu = [means[n] for n in names]

    # The comparison population model is fitted on the training split only, so
    # the fight on each segment's holdout is fair. The *shipped* population
    # halves keep their full-data fit — they are the fallback for every stratum
    # that loses, and handicapping them to run this experiment would be paying
    # for the measurement with the thing being measured.
    pop_wt, pop_bt = _fit_half([treated[i] for i in t_train_idx], names, mu, scales, seed)
    pop_wc, pop_bc = _fit_half([control[i] for i in c_train_idx], names, mu, scales, seed + 1)

    # Counted before the loop so every stratum faces the same threshold. Doing
    # it as we go would charge the first candidate a laxer test than the last,
    # and which stratum is "first" is an alphabetical accident.
    testable = sum(
        1
        for key, rows in buckets.items()
        if key != seg.UNKNOWN
        and len(rows["t"]) >= MIN_SEGMENT_TREATED_N
        and len(rows["c"]) >= models.MIN_SEGMENT_CONTROL_N
    )
    z_required = heterogeneity_z(testable)
    if testable:
        logger.info(
            "granularity ladder: %d strata have the power to be tested, so the "
            "heterogeneity gate is Bonferroni-corrected to z >= %.2f",
            testable,
            z_required,
        )

    promoted: dict[str, Any] = {}
    report: list[dict[str, Any]] = []

    for key in sorted(buckets):
        if key == seg.UNKNOWN:
            # Never fitted. A model of "the rows whose DPD was missing" is a
            # model of a data-quality incident, and it would be applied to
            # whichever accounts happen to be broken on the day it scores.
            report.append({"segment": key, "verdict": "skipped", "reason": "unplaceable"})
            continue
        rows_t = buckets[key]["t"]
        rows_c = buckets[key]["c"]
        if len(rows_t) < MIN_SEGMENT_TREATED_N or len(rows_c) < models.MIN_SEGMENT_CONTROL_N:
            report.append({
                "segment": key,
                "verdict": "skipped",
                "reason": "underpowered",
                "treatedN": len(rows_t),
                "controlN": len(rows_c),
            })
            continue

        p_t = sum(l for _, l in rows_t) / len(rows_t)
        p_c = sum(l for _, l in rows_c) / len(rows_c)
        ate = p_t - p_c
        se = _ate_stderr(p_t, len(rows_t), p_c, len(rows_c))
        z = abs(ate - population_ate) / se if se > 0 else 0.0

        entry: dict[str, Any] = {
            "segment": key,
            "label": seg.describe(key),
            "treatedN": len(rows_t),
            "controlN": len(rows_c),
            "ate": round(ate, 6),
            "ateStderr": round(se, 6),
            "z": round(z, 3),
            "zRequired": round(z_required, 3),
        }

        if z < z_required:
            entry.update({"verdict": "rejected", "reason": "no_heterogeneity"})
            report.append(entry)
            continue

        train_t, test_t = buckets[key]["t_train"], buckets[key]["t_test"]
        train_c, test_c = buckets[key]["c_train"], buckets[key]["c_test"]
        if not test_t or not test_c or len(train_t) < 40 or len(train_c) < 40:
            entry.update({"verdict": "skipped", "reason": "empty_holdout"})
            report.append(entry)
            continue

        w_t, b_t = _fit_half(train_t, names, mu, scales, seed + 13)
        w_c, b_c = _fit_half(train_c, names, mu, scales, seed + 17)

        held = list(test_t) + list(test_c)
        held_pop = [(pop_wt, pop_bt)] * len(test_t) + [(pop_wc, pop_bc)] * len(test_c)
        held_seg = [(w_t, b_t)] * len(test_t) + [(w_c, b_c)] * len(test_c)
        X = [
            [float(v[n]) if v.get(n) is not None else means[n] for n in names]
            for v, _ in held
        ]
        y = [l for _, l in held]
        loss_pop = logloss(
            [_predict(x, w, b, cal) for x, (w, b) in zip(X, held_pop)], y
        )
        loss_seg = logloss(
            [_predict(x, w, b, cal) for x, (w, b) in zip(X, held_seg)], y
        )
        lift = loss_pop - loss_seg
        entry.update({
            "holdoutLoglossPopulation": round(loss_pop, 6),
            "holdoutLoglossSegment": round(loss_seg, 6),
            "holdoutLift": round(lift, 6),
        })

        if lift <= 0:
            entry.update({"verdict": "rejected", "reason": "no_holdout_lift"})
            report.append(entry)
            continue

        # Shipped halves are refitted on everything this stratum has. The split
        # above bought the verdict; having bought it, there is no reason to ship
        # a model that has seen three quarters of the evidence.
        fw_t, fb_t = _fit_half(rows_t, names, mu, scales, seed + 13)
        fw_c, fb_c = _fit_half(rows_c, names, mu, scales, seed + 17)
        promoted[key] = {
            "coefficients": [round(w, 8) for w in fw_t],
            "intercept": round(fb_t, 8),
            "controlCoefficients": [round(w, 8) for w in fw_c],
            "controlIntercept": round(fb_c, 8),
            "n": len(rows_t),
            "controlN": len(rows_c),
            "holdoutLift": round(lift, 6),
        }
        entry["verdict"] = "promoted"
        report.append(entry)

    return promoted, report


def _fit_half(
    samples: list[tuple[dict[str, float | None], int]],
    names: tuple[str, ...],
    mu: list[float],
    scales: list[float],
    seed: int,
) -> tuple[list[float], float]:
    """One logistic half, standardised on the shared scaling and folded back.

    ``mu`` and ``scales`` come from the *pooled* data on purpose. Standardising
    each stratum on its own moments would make the coefficients incomparable
    across segments and, worse, incomparable with the population halves they
    are blended against — and τ is a difference of exactly those predictions.
    """
    X = [
        [float(v[n]) if v.get(n) is not None else mu[i] for i, n in enumerate(names)]
        for v, _ in samples
    ]
    y = [label for _, label in samples]
    Z = _standardise(X, mu, scales)
    zw, zb = fit_logistic(Z, y, seed=seed)
    return _unscale(zw, zb, mu, scales)


def _samples(
    rows: Iterable[dict[str, Any]], labeller: Any
) -> list[tuple[dict[str, float | None], int]]:
    out: list[tuple[dict[str, float | None], int]] = []
    missing_vector = 0
    for row in rows:
        label = labeller(row)
        if label is None:
            continue
        vec = _vector_for(row)
        if vec is None:
            missing_vector += 1
            continue
        out.append((vec, label))
    if missing_vector:
        logger.info(
            "%d labelled rows had no logged vector and were refused rather than "
            "reconstructed (see TREATMENT_LOG_VECTORS)",
            missing_vector,
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", choices=(*TARGETS, "all"), default="all")
    ap.add_argument("--out-dir", default="models")
    ap.add_argument("--holdout", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--min-control", type=int, default=models.MIN_CONTROL_N)
    ap.add_argument(
        "--no-segments",
        action="store_true",
        help=(
            "fit the population uplift model only, skipping the granularity "
            "ladder. Useful for producing the coarser champion a segmented "
            "challenger has to beat."
        ),
    )
    ap.add_argument(
        "--include-simulated",
        action="store_true",
        help="fit on the synthetic corpus too; every artifact records that it did",
    )
    args = ap.parse_args()

    with db.engine.connect() as conn:
        rows = _rows(conn, include_simulated=args.include_simulated)
    if not rows:
        logger.error("no decisions at feature schema %s to train on", SCHEMA_VERSION)
        return 1
    logger.info("%d decisions in scope", len(rows))

    corpus = "simulated" if args.include_simulated else "live"
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = TARGETS if args.target == "all" else (args.target,)
    written = 0

    for target in wanted:
        if target == "reach":
            artifact = train_one(
                _samples(rows, _label_reach),
                target="reach",
                holdout=args.holdout,
                seed=args.seed,
                corpus=corpus,
            )
        elif target == "timing":
            artifact = train_one(
                _samples(rows, _label_timing),
                target="timing",
                holdout=args.holdout,
                seed=args.seed,
                corpus=corpus,
            )
        else:
            control_rows = [r for r in rows if str(r.get("variant") or "") == CONTROL_ARM]
            treated_rows = [r for r in rows if str(r.get("variant") or "") != CONTROL_ARM]
            artifact = train_uplift(
                _samples(treated_rows, _label_cure),
                _samples(control_rows, _label_cure),
                holdout=args.holdout,
                seed=args.seed,
                corpus=corpus,
                min_control=args.min_control,
                segment_ladder=not args.no_segments,
            )
        if artifact is None:
            continue
        path = out_dir / f"treatment_{target}.json"
        path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
        logger.info("wrote %s", path)
        written += 1

    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
