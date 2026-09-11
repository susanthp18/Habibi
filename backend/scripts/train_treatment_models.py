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
from typing import Any, Iterable, Mapping, NamedTuple, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env_loader import load_env

load_env()

import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from agent_core.treatment import cluster, models  # noqa: E402
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
                       scheduled_at, created_at, label_mature_at,
                       candidates, features
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


def _as_utc(raw: Any) -> datetime | None:
    """A timestamptz off the driver, normalised. Naive is read as UTC."""
    if not isinstance(raw, datetime):
        return None
    return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)


class Sample(NamedTuple):
    """One labelled decision, carrying what the split needs to be honest.

    ``customer_id`` and ``at`` are not features and never reach the design
    matrix. They are here because a training row that cannot say *whose*
    decision it was and *when* can only be split at random, and a random split
    of a time-ordered, borrower-clustered corpus is the defect this record
    exists to make impossible to reintroduce.
    """

    vec: dict[str, float | None]
    label: int
    customer_id: str
    at: datetime
    #: When this row's label became final. ``None`` means it never will under
    #: this build — a decision logged before W3 defined the horizon.
    mature_at: datetime | None


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
    samples: list[Sample], names: tuple[str, ...]
) -> tuple[list[list[float]], list[int], dict[str, float]]:
    """Feature matrix with mean imputation. Absent is filled, never zeroed."""
    means: dict[str, float] = {}
    for name in names:
        seen = [
            float(v[name])
            for s in samples
            for v in (s.vec,)
            if v.get(name) is not None
        ]
        means[name] = sum(seen) / len(seen) if seen else 0.0
    X = [
        [float(s.vec[n]) if s.vec.get(n) is not None else means[n] for n in names]
        for s in samples
    ]
    y = [s.label for s in samples]
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


class SplitReport(NamedTuple):
    """What the split did, in numbers, so it can be printed and filed."""

    train: int
    test: int
    train_customers: int
    test_customers: int
    #: Rows dropped for not having reached the primary horizon. §8.12 gate 3
    #: requires this reported rather than silently excluded: the immature tail
    #: is always the most recent slice, so dropping it quietly is how a model
    #: comes to be graded on a period that no longer resembles today.
    immature: int

    def describe(self) -> str:
        return (
            f"train {self.train} rows / {self.train_customers} customers · "
            f"holdout {self.test} rows / {self.test_customers} customers · "
            f"{self.immature} immature rows excluded"
        )


def holdout_split(
    samples: Sequence[Sample], *, fraction: float
) -> tuple[list[int], list[int], SplitReport]:
    """Gate 3 — out of time, and disjoint by borrower.

    What this replaces was ``random.Random(seed).shuffle(idx)`` over rows the
    extractor had deliberately pulled ``ORDER BY created_at ASC``, with
    ``customer_id`` selected and never used. Two leaks, both inflating the AUC a
    risk committee reads: the model memorises borrowers and is then graded on
    borrowers it has seen `[train-holdout-split-is-by-row-not-by-borrower]`, and
    March's decisions predict February's `[random-split-not-out-of-time]`.

    **The split is by customer, not by row, and the ordering is by time.** Rank
    each borrower by their most recent mature decision, take the most recent
    borrowers until the holdout holds ``fraction`` of the rows, and give each
    borrower's rows entirely to one side. Splitting rows and then repairing the
    overlap would leave a borrower straddling the boundary with nowhere honest
    to put their early decisions; splitting borrowers cannot produce one.

    Immature rows are dropped first and counted, per gate 3 — a decision whose
    90-day window is still open contributes a label of "has not paid yet", and
    the immature tail is always the newest slice, so training on it teaches the
    model that recent means unsuccessful.

    There is no ``seed``. An ordering is not a draw, and a seed here would be an
    invitation to re-roll a holdout somebody did not like.
    """
    now = datetime.now(timezone.utc)
    mature = [i for i, s in enumerate(samples) if s.mature_at is not None and s.mature_at <= now]
    immature = len(samples) - len(mature)
    if not mature:
        return [], [], SplitReport(0, 0, 0, 0, immature)

    last_seen: dict[str, datetime] = {}
    rows_by_customer: dict[str, list[int]] = {}
    for i in mature:
        s = samples[i]
        rows_by_customer.setdefault(s.customer_id, []).append(i)
        if s.customer_id not in last_seen or s.at > last_seen[s.customer_id]:
            last_seen[s.customer_id] = s.at

    # Most recent borrower first, then by id so the split is reproducible
    # without a seed.
    order = sorted(last_seen, key=lambda c: (last_seen[c], c), reverse=True)
    want = max(1, int(round(len(mature) * max(0.0, min(1.0, fraction)))))
    test_customers: set[str] = set()
    held = 0
    for customer in order:
        # Stop *before* taking a borrower who would leave nothing to train on:
        # a holdout containing every customer is not a holdout.
        if held >= want or len(test_customers) >= len(order) - 1:
            break
        test_customers.add(customer)
        held += len(rows_by_customer[customer])

    test = sorted(i for c in test_customers for i in rows_by_customer[c])
    train = sorted(i for i in mature if samples[i].customer_id not in test_customers)
    return (
        train,
        test,
        SplitReport(
            train=len(train),
            test=len(test),
            train_customers=len(order) - len(test_customers),
            test_customers=len(test_customers),
            immature=immature,
        ),
    )


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
    samples: list[Sample],
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
        {k for s in samples for k in s.vec}
    )
    if not names:
        logger.error("%s: no trainable features in the logged vectors", target)
        return None

    X, y, means = _design(samples, names)
    train_idx, test_idx, split = holdout_split(samples, fraction=holdout)
    logger.info("%s: %s", target, split.describe())
    if not test_idx or not train_idx:
        logger.error(
            "%s: the out-of-time holdout is empty (%s). Gate 3 splits by borrower "
            "and by date, so this means too few mature borrowers rather than too "
            "few rows — raise --holdout only if there are borrowers to move",
            target,
            split.describe(),
        )
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
    treated: list[Sample],
    control: list[Sample],
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
        {k for s in (treated + control) for k in s.vec}
    )
    X_t, y_t, means = _design(treated, names)
    X_c = [
        [float(s.vec[n]) if s.vec.get(n) is not None else means[n] for n in names]
        for s in control
    ]
    y_c = [s.label for s in control]

    # One scaling for both halves. Two would make the coefficients
    # incomparable, and τ is a difference of the two predictions.
    mu = [means[n] for n in names]
    scales = _scales(X_t + X_c, mu)
    Z_t = _standardise(X_t, mu, scales)
    Z_c = _standardise(X_c, mu, scales)

    t_idx, t_test, t_split = holdout_split(treated, fraction=holdout)
    logger.info("uplift: treated half %s", t_split.describe())
    if not t_idx or not t_test:
        logger.error("uplift: the treated half has no out-of-time holdout (%s)", t_split.describe())
        return None
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

#: Treated **customers** a stratum needs before it is worth testing at all, and
#: the control side has its own stricter floor in
#: ``models.MIN_SEGMENT_CONTROL_N``. §8.10 rung 3 states both in customers, and
#: they used to be applied to rows: on a corpus where one borrower contributes
#: fourteen decisions, a "150-row" stratum can be eleven people, and a variance
#: estimated across it is a description of those eleven.
MIN_SEGMENT_TREATED_N = 150

#: §8.10 rung 3's multiplicity control, and it lives in
#: ``agent_core/treatment/cluster.py`` beside the intervals whose p-values it
#: corrects. Named here so the trainer has one import rather than a literal.
HETEROGENEITY_FDR = cluster.DEFAULT_FDR


def _customers(rows: Sequence[Sample]) -> int:
    """Distinct borrowers, which is the unit every floor in §8.10 is stated in."""
    return len({r.customer_id for r in rows})


def _arm_rate(rows: Sequence[Mapping[str, Any]], arm: str) -> float:
    """Cure rate within one arm of a mixed row set. 0.0 when the arm is empty."""
    vals = [float(r["label"]) for r in rows if r["arm"] == arm]
    return (sum(vals) / len(vals)) if vals else 0.0


def _difference(rows: Sequence[Mapping[str, Any]]) -> float:
    """(segment ATE) - (leave-one-segment-out population ATE), on one row set.

    The statistic the cluster bootstrap resamples. It is computed *inside* the
    resample rather than differenced afterwards, which is the whole point: the
    segment and the population estimate share borrowers, so their errors are
    correlated, and the standard error of a difference of two correlated
    quantities is not the root of the sum of their squares. Resampling the
    borrowers and recomputing both halves gets that right without anyone having
    to write down the covariance.
    """
    inside = [r for r in rows if r["inside"]]
    outside = [r for r in rows if not r["inside"]]
    seg = _arm_rate(inside, "t") - _arm_rate(inside, "c")
    pop = _arm_rate(outside, "t") - _arm_rate(outside, "c")
    return seg - pop


def _pvalue(point: float, band: cluster.Interval) -> float:
    """Two-sided p for the difference, from the bootstrap band's width.

    The band is a percentile or wild-bootstrap interval, not a normal one, so
    reading a standard error back out of it assumes symmetry that the bootstrap
    did not promise. It is done anyway and said out loud, because BH needs a
    p-value per cell and the alternative — a bootstrap p from the sign of the
    replicate draws — is granular at 1/replications, which at 400 replications
    cannot express a p below 0.0025 and would floor every genuinely strong cell
    at the same value.
    """
    if not math.isfinite(band.low) or not math.isfinite(band.high):
        return 1.0
    se = (band.high - band.low) / (2.0 * NormalDist().inv_cdf(0.975))
    if se <= 0:
        return 0.0 if abs(point) > 0 else 1.0
    return 2.0 * (1.0 - NormalDist().cdf(abs(point) / se))


def _predict(row: list[float], weights: list[float], intercept: float,
             cal: tuple[float, float]) -> float:
    return _sigmoid(cal[0] * (sum(a * c for a, c in zip(row, weights)) + intercept) + cal[1])


def fit_segments(
    treated: list[Sample],
    control: list[Sample],
    *,
    names: tuple[str, ...],
    means: dict[str, float],
    scales: list[float],
    cal: tuple[float, float],
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

    *Power.* Enough treated and control **customers** (§8.10 rung 3 states the
    floors in customers, and they used to be applied to rows). Skipped strata
    are reported as skipped, never as failed — those are different facts about
    a book.

    *Heterogeneity.* §8.10 rung 3, and W12 rebuilt it. The segment's ATE is
    measured **out of sample**, on the held-out slice only; compared against the
    **leave-one-segment-out** population ATE rather than against a pool
    containing it; with a **cluster-bootstrap standard error for the
    difference**, resampling borrowers so the two halves' shared errors are
    carried rather than assumed away; and multiplicity is controlled by
    **Benjamini–Hochberg at FDR 0.10** across the cells actually tested. Each of
    the four replaces something that was wrong in a direction nobody checks
    `[heterogeneity-gate-is-in-sample-and-subset-vs-pool]`. This is the causal
    gate and the load-bearing one: it is backed by the randomisation rather than
    by a model, so passing it means this stratum genuinely responds differently,
    not that a fit found a pattern in it.

    *Holdout fit.* Both halves must predict held-out cure labels better than the
    population halves do on the same rows, measured in log loss.

    Fit-quality alone is not enough, which is why the causal gate is separate. A
    segment model will nearly always fit its own stratum better than a pooled
    model does — it has fewer rows to explain and its own intercept. That is
    overfitting, and on a difference of two noisy quantities it is exactly how
    confident noise gets shipped.

    Because BH is a **step-up** procedure, the causal gate cannot be applied one
    cell at a time: which cells pass depends on how many were tested and on
    where each p-value ranks. So this runs in three passes — measure, correct,
    fit — and the report carries every cell's ``pValue``, ``bhRank`` and
    ``bhCritical`` whether it passed or not. §15.2 makes that report W12's
    deliverable in its own right: *"a segment promotion under the repaired gate,
    **or an honest refusal with the FDR-adjusted numbers filed**"*.
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
    t_train_idx, t_test_idx, _ = holdout_split(treated, fraction=holdout)
    c_train_idx, c_test_idx, _ = holdout_split(control, fraction=holdout)
    t_fold = {i: "train" for i in t_train_idx}
    t_fold.update({i: "test" for i in t_test_idx})
    c_fold = {i: "train" for i in c_train_idx}
    c_fold.update({i: "test" for i in c_test_idx})

    def _empty() -> dict[str, list[Any]]:
        return {"t": [], "c": [], "t_train": [], "t_test": [], "c_train": [], "c_test": []}

    # A row in neither fold is an immature one that ``holdout_split`` dropped.
    # It still counts toward the segment's ATE — that estimate is a description
    # of the corpus — but it may not enter a fit or a holdout, which is the
    # whole point of dropping it.
    buckets: dict[str, dict[str, list[Any]]] = {}
    for i, sample in enumerate(treated):
        entry = buckets.setdefault(seg.key_for(sample.vec), _empty())
        entry["t"].append(sample)
        if i in t_fold:
            entry[f"t_{t_fold[i]}"].append(sample)
    for i, sample in enumerate(control):
        entry = buckets.setdefault(seg.key_for(sample.vec), _empty())
        entry["c"].append(sample)
        if i in c_fold:
            entry[f"c_{c_fold[i]}"].append(sample)

    mu = [means[n] for n in names]

    # The comparison population model is fitted on the training split only, so
    # the fight on each segment's holdout is fair. The *shipped* population
    # halves keep their full-data fit — they are the fallback for every stratum
    # that loses, and handicapping them to run this experiment would be paying
    # for the measurement with the thing being measured.
    pop_wt, pop_bt = _fit_half([treated[i] for i in t_train_idx], names, mu, scales, seed)
    pop_wc, pop_bc = _fit_half([control[i] for i in c_train_idx], names, mu, scales, seed + 1)

    promoted: dict[str, Any] = {}
    report: list[dict[str, Any]] = []

    # ---------------------------------------------------------------------
    # Pass 1 -- measure every testable cell. Nothing is decided here, because
    # Benjamini-Hochberg is a step-up procedure over the whole family: which
    # cells pass depends on how many were tried and on where each p-value ranks
    # among the others, so no cell can be judged until all are measured.
    # ---------------------------------------------------------------------
    measured: list[tuple[str, dict[str, Any]]] = []
    for key in sorted(buckets):
        if key == seg.UNKNOWN:
            # Never fitted. A model of "the rows whose DPD was missing" is a
            # model of a data-quality incident, and it would be applied to
            # whichever accounts happen to be broken on the day it scores.
            report.append({"segment": key, "verdict": "skipped", "reason": "unplaceable"})
            continue
        rows_t = buckets[key]["t"]
        rows_c = buckets[key]["c"]
        # The floors are in CUSTOMERS (§8.10 rung 3). They used to be applied to
        # rows, and on a corpus where one borrower contributes fourteen
        # decisions that is a different and far weaker test: a "150-row" stratum
        # can be eleven people, and a variance estimated across it is a
        # description of those eleven.
        cust_t, cust_c = _customers(rows_t), _customers(rows_c)
        if cust_t < MIN_SEGMENT_TREATED_N or cust_c < models.MIN_SEGMENT_CONTROL_N:
            report.append({
                "segment": key,
                "verdict": "skipped",
                "reason": "underpowered",
                "treatedN": len(rows_t),
                "controlN": len(rows_c),
                "treatedCustomers": cust_t,
                "controlCustomers": cust_c,
                "treatedCustomersRequired": MIN_SEGMENT_TREATED_N,
                "controlCustomersRequired": models.MIN_SEGMENT_CONTROL_N,
            })
            continue

        if not buckets[key]["t_test"] or not buckets[key]["c_test"]:
            report.append({
                "segment": key,
                "verdict": "skipped",
                "reason": "empty_holdout",
                "treatedCustomers": cust_t,
                "controlCustomers": cust_c,
            })
            continue

        # The gate is measured OUT OF SAMPLE, on the held-out slice only, and
        # against the LEAVE-ONE-SEGMENT-OUT population -- the two repairs §8.10
        # rung 3 asks for. What this replaces compared each segment ATE, over
        # every one of its rows, to a population ATE computed over a pool that
        # CONTAINED those rows: a subset is always closer to a mean it is part
        # of, so the test was biased toward finding no heterogeneity, and the
        # rows the verdict was measured on were the rows the segment model then
        # fitted `[heterogeneity-gate-is-in-sample-and-subset-vs-pool]`.
        inside = {id(x) for x in buckets[key]["t_test"]}
        inside |= {id(x) for x in buckets[key]["c_test"]}
        held: list[dict[str, Any]] = []
        for arm, idx, source in (("t", t_test_idx, treated), ("c", c_test_idx, control)):
            for i in idx:
                sample = source[i]
                held.append({
                    "customer_id": sample.customer_id,
                    "arm": arm,
                    "label": float(sample.label),
                    "inside": id(sample) in inside,
                })

        point = _difference(held)
        # Clustered on the borrower, because a borrower contributes to the
        # segment half and the population half of the same difference and the
        # two errors are the same person's. `_ate_stderr` counted fourteen
        # decisions on one borrower as fourteen independent observations.
        band = cluster.bootstrap(held, _difference, cluster_key="customer_id")
        pvalue = _pvalue(point, band)
        held_in = [r for r in held if r["inside"]]
        held_out = [r for r in held if not r["inside"]]

        entry: dict[str, Any] = {
            "segment": key,
            "label": seg.describe(key),
            "treatedN": len(rows_t),
            "controlN": len(rows_c),
            "treatedCustomers": cust_t,
            "controlCustomers": cust_c,
            "ate": round(_arm_rate(held_in, "t") - _arm_rate(held_in, "c"), 6),
            "losoAte": round(_arm_rate(held_out, "t") - _arm_rate(held_out, "c"), 6),
            "difference": round(point, 6),
            "differenceInterval": band.as_dict(),
            "pValue": round(pvalue, 6),
            "clusters": band.clusters,
        }
        measured.append((key, entry))

    # ---------------------------------------------------------------------
    # Pass 2 -- Benjamini-Hochberg across everything that was tested.
    # ---------------------------------------------------------------------
    tested = len(measured)
    rejected = cluster.bh_reject(
        [e["pValue"] for _, e in measured], fdr=HETEROGENEITY_FDR
    )
    ranks = {
        key: rank
        for rank, (key, _) in enumerate(
            sorted(measured, key=lambda item: item[1]["pValue"]), start=1
        )
    }
    if tested:
        logger.info(
            "granularity ladder: %d strata had the power to be tested; "
            "Benjamini-Hochberg at FDR %.2f finds %d heterogeneous",
            tested,
            HETEROGENEITY_FDR,
            sum(rejected),
        )

    # ---------------------------------------------------------------------
    # Pass 3 -- the holdout fit, for the cells BH let through.
    # ---------------------------------------------------------------------
    for (key, entry), heterogeneous in zip(measured, rejected):
        entry["bhRank"] = ranks[key]
        entry["bhTested"] = tested
        entry["bhFdr"] = HETEROGENEITY_FDR
        entry["bhCritical"] = round(
            cluster.bh_critical(ranks[key], tested, fdr=HETEROGENEITY_FDR), 6
        )
        if not heterogeneous:
            entry.update({"verdict": "rejected", "reason": "no_heterogeneity"})
            report.append(entry)
            continue

        rows_t = buckets[key]["t"]
        rows_c = buckets[key]["c"]
        train_t, test_t = buckets[key]["t_train"], buckets[key]["t_test"]
        train_c, test_c = buckets[key]["c_train"], buckets[key]["c_test"]
        if len(train_t) < 40 or len(train_c) < 40:
            # The cell is heterogeneous and there is not enough of it left to
            # fit both halves on. "Skipped" rather than "rejected": the finding
            # stands, what is missing is a model to carry it.
            entry.update({"verdict": "skipped", "reason": "thin_training_split"})
            report.append(entry)
            continue

        w_t, b_t = _fit_half(train_t, names, mu, scales, seed + 13)
        w_c, b_c = _fit_half(train_c, names, mu, scales, seed + 17)

        held = list(test_t) + list(test_c)
        held_pop = [(pop_wt, pop_bt)] * len(test_t) + [(pop_wc, pop_bc)] * len(test_c)
        held_seg = [(w_t, b_t)] * len(test_t) + [(w_c, b_c)] * len(test_c)
        X = [
            [float(s.vec[n]) if s.vec.get(n) is not None else means[n] for n in names]
            for s in held
        ]
        y = [s.label for s in held]
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
    samples: list[Sample],
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
        [float(s.vec[n]) if s.vec.get(n) is not None else mu[i] for i, n in enumerate(names)]
        for s in samples
    ]
    y = [s.label for s in samples]
    Z = _standardise(X, mu, scales)
    zw, zb = fit_logistic(Z, y, seed=seed)
    return _unscale(zw, zb, mu, scales)


def _samples(rows: Iterable[dict[str, Any]], labeller: Any) -> list[Sample]:
    out: list[Sample] = []
    missing_vector = 0
    for row in rows:
        label = labeller(row)
        if label is None:
            continue
        vec = _vector_for(row)
        if vec is None:
            missing_vector += 1
            continue
        out.append(
            Sample(
                vec=vec,
                label=label,
                customer_id=str(row.get("customer_id") or ""),
                at=_as_utc(row.get("created_at")) or datetime.now(timezone.utc),
                mature_at=_as_utc(row.get("label_mature_at")),
            )
        )
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
    ap.add_argument("--out-dir", default="models/challengers")
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
    out_dir = Path(args.out_dir).resolve()
    serving_dir = Path("models").resolve()
    if out_dir == serving_dir:
        logger.error(
            "refusing to write challengers into the serving path %s — use models/challengers",
            out_dir,
        )
        return 2
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
        try:
            # ``allow_nan=False`` is the write half of the finite-value gate.
            # Python's default emits the JavaScript-illegal literals ``NaN`` and
            # ``Infinity``, which ``json.loads`` then reads back happily — so a
            # column with no variance in it produces an artifact that loads and
            # scores a confident zero rather than one that fails. Refusing at
            # the point of writing means the trainer, which knows which column
            # it was, reports it instead of the loader months later.
            body = json.dumps(artifact, indent=2, allow_nan=False)
        except ValueError as exc:
            logger.error(
                "%s: refusing to write a non-finite artifact (%s). A NaN here "
                "does not crash downstream — it scores ~0 with full confidence "
                "and the engine goes quiet.",
                target,
                exc,
            )
            continue
        path.write_text(body, encoding="utf-8")
        logger.info("wrote %s", path)
        written += 1

    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
