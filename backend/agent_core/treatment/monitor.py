"""Drift and calibration — §15's model-health half, and the one that fails quietly.

Three checks, and they fail in three different ways that a single "model health"
number would blur together:

**Feature drift.** The book moves. The mix of buckets shifts as a portfolio
seasons, mandate penetration climbs as registration improves, and a phone number
that reached someone in March is dead by August. A model fitted on last
quarter's distribution keeps returning confident numbers on this quarter's, and
nothing in its own output says otherwise. Measured in standard deviations of the
training distribution, because "dpd has moved by 11" is not a finding until you
know whether 11 is a tenth of a σ or three of them.

**Reach calibration.** The design note is explicit that a model whose 0.7 does
not mean 70% cannot be used in an EV formula at all — and it is right, because
the formula multiplies that number by an exposure in rupees. A reach model that
is 15 points optimistic does not rank actions slightly wrongly; it prices every
contact 15% too high and pulls the whole ladder down toward more expensive
channels. This bins predictions against realised outcomes and reports the gap.

**Uplift calibration, which cannot be done the same way.** τ has no per-row
label — the whole difficulty of causal inference is that a borrower is either
contacted or not, never both — so there is no held-out τ to compare against.
What *can* be compared is the model's average predicted τ against the ATE the
randomised arm measured directly. If the model says it is finding +18 points of
uplift on a book where the control arm says the policy is worth +4, the model is
not finding uplift. It is finding self-curers, which is the exact failure the
whole design exists to prevent, and this is the only check that sees it.

Everything here reads the logged corpus and touches no borrower. It is safe to
run on a cron, and it is meant to be.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

from sqlalchemy import text

from agent_core.treatment import models

logger = logging.getLogger(__name__)

#: Standardised mean shift at which a feature is called drifted. Two tenths of a
#: training σ is small enough to catch a book seasoning before it hurts and
#: large enough not to fire on the ordinary week-to-week wobble of a live book.
DRIFT_WARN_SIGMA = 0.20
DRIFT_ALERT_SIGMA = 0.50

#: Expected calibration error above which a probability is not a probability.
#: Five points is generous; it is set where it is because the consequence of
#: exceeding it is an EV formula quietly multiplying rupees by a wrong number,
#: and a floor lead reading "worth ₹68" deserves better than a coin flip.
CALIBRATION_WARN_ECE = 0.05
CALIBRATION_ALERT_ECE = 0.10

#: Reliability bins. Ten is conventional and, more usefully, keeps roughly a
#: few hundred rows per bin on the corpus sizes this will see for months.
BINS = 10

REACHED = frozenset({"reached", "ptp", "refused"})
NOT_REACHED = frozenset({"no_answer", "undeliverable"})
CURED = frozenset({"paid", "ptp"})


#: Decisions to read per calibration check. Cheap: the query pulls two scalars
#: per row, not the feature vectors, so twenty thousand rows is a few hundred
#: kilobytes.
SAMPLE_LIMIT = 20_000

#: Decisions to read for *drift*, which is the one check that genuinely needs
#: the feature vector. Much smaller on purpose.
#:
#: Drift is a mean shift measured in training sigmas, and the alert threshold is
#: 0.20σ. Two thousand observations put the standard error of that mean at
#: 0.022σ — an order of magnitude inside the threshold — so reading a hundred
#: times more rows would not move a single verdict. It would only move ninety
#: megabytes of counterfactual feature vectors into Python to compute the same
#: answer, which is what the first version of this module did and why it
#: exceeded the statement timeout outright.
DRIFT_SAMPLE = 2_000


def _chosen_entry(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """The candidate entry for the action actually taken.

    The only one whose outcome was observed. Every other entry in the list is
    the counterfactual, and scoring a monitor against those would be scoring the
    model on questions nobody answered.

    Accepts either the pre-extracted ``chosen`` object the drift query selects,
    or a whole ``candidates`` array, so a caller holding raw decision rows — a
    test, a notebook — can pass them straight in.
    """
    direct = row.get("chosen")
    if isinstance(direct, dict):
        return direct
    candidates = row.get("candidates")
    if not isinstance(candidates, list):
        return None
    chosen_name = str(row.get("chosen_action") or "")
    for entry in candidates:
        if isinstance(entry, dict) and str(entry.get("action")) == chosen_name:
            return entry
    return None


def _calibration_rows(
    conn: Any, *, days: int, modes: Sequence[str], limit: int = SAMPLE_LIMIT
) -> list[dict[str, Any]]:
    """Outcomes and the two scored probabilities, and nothing else.

    Both calibration checks compare a *scalar* the engine logged against what
    happened. Neither looks at a feature vector, so neither should pay to move
    one: the scalars are extracted in SQL and a row comes back as a handful of
    bytes instead of the four to eight kilobytes ``candidates`` occupies.

    The first version of this selected ``candidates`` whole and filtered the
    array in Python. On eighteen thousand rows that is ninety megabytes to
    compute three summary statistics, and it exceeded the fifteen-second
    statement timeout the API path runs under.
    """
    return [
        dict(r)
        for r in conn.execute(
            text(
                """
                SELECT d.id, d.variant, d.mode, d.chosen_action, d.chosen_channel,
                       d.enacted, d.outcome, d.created_at,
                       (c.entry ->> 'pReach')::float AS p_reach,
                       (c.entry ->> 'pResolve')::float AS p_resolve
                FROM treatment_decisions d
                LEFT JOIN LATERAL (
                  SELECT e.entry
                  FROM jsonb_array_elements(d.candidates) AS e(entry)
                  WHERE e.entry ->> 'action' = d.chosen_action
                  LIMIT 1
                ) AS c(entry) ON true
                WHERE d.mode = ANY(:modes)
                  AND d.created_at >= now() - make_interval(days => :days)
                ORDER BY d.created_at DESC
                LIMIT :limit
                """
            ),
            {
                "modes": list(modes),
                "days": max(1, int(days)),
                "limit": max(1, int(limit)),
            },
        ).mappings()
    ]


def _drift_rows(
    conn: Any,
    *,
    days: int,
    modes: Sequence[str],
    limit: int = DRIFT_SAMPLE,
    contacting_only: bool = False,
) -> list[dict[str, Any]]:
    """The chosen action's feature vector, for a bounded recent sample.

    ``contacting_only`` exists because **a model's drift baseline is its own
    training distribution**, so the comparison population has to match the
    filter that produced it. The reach model is fitted on attempts that went out
    on a channel; comparing it against every decision — including mandate
    presentments scheduled a month out and waits that go nowhere — compares two
    different populations and reports drift that is really a definition
    mismatch. It did: the first run alerted on seven features at once, none of
    which had moved.
    """
    return [
        dict(r)
        for r in conn.execute(
            text(
                """
                SELECT d.id, d.chosen_action, c.entry AS chosen
                FROM treatment_decisions d
                LEFT JOIN LATERAL (
                  SELECT e.entry
                  FROM jsonb_array_elements(d.candidates) AS e(entry)
                  WHERE e.entry ->> 'action' = d.chosen_action
                  LIMIT 1
                ) AS c(entry) ON true
                WHERE d.mode = ANY(:modes)
                  AND d.created_at >= now() - make_interval(days => :days)
                  AND (NOT :contacting OR d.chosen_channel IS NOT NULL)
                ORDER BY d.created_at DESC
                LIMIT :limit
                """
            ),
            {
                "modes": list(modes),
                "days": max(1, int(days)),
                "limit": max(1, int(limit)),
                "contacting": bool(contacting_only),
            },
        ).mappings()
    ]


# ---------------------------------------------------------------------------
# Feature drift
# ---------------------------------------------------------------------------


def feature_drift(
    rows: Sequence[Mapping[str, Any]], artifact: models.ModelArtifact
) -> dict[str, Any]:
    """How far the recent book has moved from what this model was fitted on.

    Reports per feature and never aggregates to a single score. A single number
    would let one badly drifted feature hide behind twenty stable ones, and the
    one that moved is the finding.
    """
    if not artifact.stdevs:
        # An artifact from before stdevs were recorded. Saying so is the right
        # answer; inventing a scale from the recent data would measure the
        # recent data against itself and report no drift, forever.
        return {
            "available": False,
            "reason": (
                "artifact carries no training stdevs — refit to measure drift "
                "against it"
            ),
            "features": [],
        }

    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for row in rows:
        entry = _chosen_entry(row)
        vec = (entry or {}).get("vector")
        if not isinstance(vec, dict):
            continue
        for name in artifact.feature_names:
            value = vec.get(name)
            if value is None:
                continue
            try:
                sums[name] = sums.get(name, 0.0) + float(value)
            except (TypeError, ValueError):
                continue
            counts[name] = counts.get(name, 0) + 1

    findings: list[dict[str, Any]] = []
    unmeasurable: list[str] = []
    for name in artifact.feature_names:
        n = counts.get(name, 0)
        if n < 30:
            continue
        recent = sums[name] / n
        trained = artifact.means.get(name, 0.0)
        sigma = artifact.stdevs.get(name, 0.0)
        if sigma <= 1e-6:
            # The feature never varied while this model was fitted, so there is
            # no scale to express a shift in. Dividing by a floor here is what
            # produced a +57.9σ "finding" about a column that had been constant
            # at zero — an arithmetic artefact wearing a drift alert.
            unmeasurable.append(name)
            continue
        shift = (recent - trained) / sigma
        level = (
            "alert"
            if abs(shift) >= DRIFT_ALERT_SIGMA
            else "warn"
            if abs(shift) >= DRIFT_WARN_SIGMA
            else "ok"
        )
        findings.append(
            {
                "feature": name,
                "trainedMean": round(trained, 4),
                "recentMean": round(recent, 4),
                "shiftSigma": round(shift, 3),
                "n": n,
                "level": level,
            }
        )

    findings.sort(key=lambda f: -abs(f["shiftSigma"]))
    return {
        "available": True,
        "modelVersion": artifact.version,
        "features": findings,
        # Named rather than dropped. "This feature was constant while the model
        # was fitted" is worth knowing — it usually means the training
        # population was narrower than the one being scored.
        "unmeasurable": unmeasurable,
        "drifted": [f["feature"] for f in findings if f["level"] != "ok"],
        "worst": findings[0] if findings else None,
    }


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


def reliability(pairs: Sequence[tuple[float, int]], bins: int = BINS) -> dict[str, Any]:
    """Predicted-versus-realised, binned, plus expected calibration error.

    ECE is the sample-weighted mean absolute gap between a bin's mean prediction
    and its observed rate. It is reported alongside the table rather than
    instead of it: a model can be well calibrated on average while being badly
    wrong at the top of the range, which is exactly where an EV formula spends
    money.
    """
    if not pairs:
        return {"n": 0, "ece": None, "bins": []}
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for p, y in pairs:
        idx = min(bins - 1, max(0, int(p * bins)))
        buckets[idx].append((p, y))

    table: list[dict[str, Any]] = []
    ece = 0.0
    total = len(pairs)
    for i, bucket in enumerate(buckets):
        if not bucket:
            continue
        predicted = sum(p for p, _ in bucket) / len(bucket)
        observed = sum(y for _, y in bucket) / len(bucket)
        ece += (len(bucket) / total) * abs(predicted - observed)
        table.append(
            {
                "range": f"{i / bins:.1f}-{(i + 1) / bins:.1f}",
                "n": len(bucket),
                "predicted": round(predicted, 4),
                "observed": round(observed, 4),
                "gap": round(observed - predicted, 4),
            }
        )
    return {
        "n": total,
        "ece": round(ece, 4),
        "level": (
            "alert"
            if ece >= CALIBRATION_ALERT_ECE
            else "warn"
            if ece >= CALIBRATION_WARN_ECE
            else "ok"
        ),
        "bins": table,
    }


def reach_calibration(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Does the reach term mean what it says?

    Scored against the ``pReach`` the engine logged at decision time, not
    against a re-prediction. The logged value is what the EV formula actually
    multiplied by, so it is the number whose honesty matters — and re-predicting
    would silently score today's model on yesterday's decisions and call the
    difference calibration.
    """
    pairs: list[tuple[float, int]] = []
    for row in rows:
        if not row.get("enacted") or not row.get("chosen_channel"):
            continue
        outcome = str(row.get("outcome") or "")
        if outcome in REACHED:
            label = 1
        elif outcome in NOT_REACHED:
            label = 0
        else:
            continue
        # The scalar the query extracted, or the entry for a caller that passed
        # raw decision rows.
        predicted = row.get("p_reach")
        if predicted is None:
            predicted = (_chosen_entry(row) or {}).get("pReach")
        if predicted is None:
            continue
        try:
            pairs.append((float(predicted), label))
        except (TypeError, ValueError):
            continue
    out = reliability(pairs)
    out["quantity"] = "P(attempt reaches a human)"
    return out


def uplift_calibration(
    rows: Sequence[Mapping[str, Any]],
    *,
    control_arm: str = "null_treatment",
    fitted: bool = True,
) -> dict[str, Any]:
    """Predicted mean τ against the ATE the randomised arm actually measured.

    ``fitted`` says whether an uplift artifact was actually serving over this
    window, and it changes what the comparison *means* rather than how it is
    computed. The logged ``pResolve`` is τ only when the uplift model produced
    it; with the EV priors it is ``P(resolve | reach)``, which never claimed to
    be an incremental effect. Both are worth comparing against the arm — the
    prior being far above the measured ATE is the design note's central point,
    stated in numbers — but calling the prior "a response model wearing an
    uplift label" would be accusing it of something it never claimed.

    The only calibration check available for a causal estimate, and the most
    important one in the package. τ has no per-row label, so there is no
    reliability curve to draw — but there is one number the randomisation gives
    for free, and comparing the model's average claim against it catches the
    failure mode that every offline metric misses.

    A model claiming far more uplift than the arm measured is not a
    miscalibrated uplift model. It is a response model: it has learned to rank
    the borrowers with the highest absolute cure probability, who are largely
    the ones who would have cured anyway.
    """
    predicted: list[float] = []
    treated_cured = treated_n = control_cured = control_n = 0
    for row in rows:
        arm = str(row.get("variant") or "")
        outcome = str(row.get("outcome") or "")
        if outcome:
            cured = 1 if outcome in CURED else 0
            if arm == control_arm:
                control_n += 1
                control_cured += cured
            elif str(row.get("chosen_action") or "") not in ("", "wait"):
                treated_n += 1
                treated_cured += cured
        if arm == control_arm:
            continue
        value = row.get("p_resolve")
        if value is None:
            value = (_chosen_entry(row) or {}).get("pResolve")
        if value is None:
            continue
        try:
            predicted.append(float(value))
        except (TypeError, ValueError):
            continue

    if not predicted or not control_n or not treated_n:
        return {
            "available": False,
            "reason": (
                "needs labelled outcomes in both the treated and the control arm"
            ),
            "treatedN": treated_n,
            "controlN": control_n,
        }

    mean_tau = sum(predicted) / len(predicted)
    measured = treated_cured / treated_n - control_cured / control_n
    gap = mean_tau - measured

    if gap >= CALIBRATION_WARN_ECE:
        note = (
            "the score claims more uplift than the control arm measured — the "
            "usual cause is a response model wearing an uplift label, which "
            "ranks borrowers who would have cured anyway"
            if fitted
            else "the EV priors sit above the measured incremental effect, which "
            "is the design note's central point in numbers: p_resolve is "
            "P(cure | contacted), not the effect of contacting. Fitting τ is "
            "what closes this gap"
        )
    elif gap <= -CALIBRATION_WARN_ECE:
        note = (
            "the score claims less uplift than the control arm measured, so the "
            "engine is leaving lift on the table rather than inventing it"
        )
    else:
        note = "predicted and measured effect agree"

    return {
        "available": True,
        # Named for what it is in each case, because a reader who sees
        # "predictedMeanTau" on a run with no uplift model will believe there
        # was one.
        "quantity": "tau" if fitted else "p_resolve_prior",
        "fittedUplift": fitted,
        "predictedMeanTau": round(mean_tau, 4),
        "measuredAte": round(measured, 4),
        "gap": round(gap, 4),
        "treatedN": treated_n,
        "controlN": control_n,
        "level": "alert" if abs(gap) >= 0.10 else "warn" if abs(gap) >= 0.05 else "ok",
        "note": note,
    }


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def report(
    conn: Any,
    *,
    days: int = 14,
    include_simulated: bool = False,
    limit: int = SAMPLE_LIMIT,
    drift_limit: int = DRIFT_SAMPLE,
) -> dict[str, Any]:
    """Everything §15 asks to be monitored, in two bounded reads of the corpus."""
    modes = ["shadow", "live"] + (["simulated"] if include_simulated else [])
    rows = _calibration_rows(conn, days=days, modes=modes, limit=limit)
    # Reach is fitted on channel-bearing attempts, so that is the population it
    # is compared against.
    drift_rows = _drift_rows(
        conn, days=days, modes=modes, limit=drift_limit, contacting_only=True
    )

    reach = models.load_reach()
    uplift = models.load_uplift()

    out: dict[str, Any] = {
        "windowDays": int(days),
        "decisions": len(rows),
        # Said out loud. A statistic computed from a truncated window that does
        # not mention the truncation reads as "we looked at everything".
        "sampleLimit": int(limit),
        "truncated": len(rows) >= limit,
        "driftSampled": len(drift_rows),
        "driftSampleLimit": int(drift_limit),
        "reachCalibration": reach_calibration(rows),
        "upliftCalibration": uplift_calibration(rows, fitted=uplift is not None),
        "featureDrift": (
            feature_drift(drift_rows, reach)
            if reach is not None
            else {
                "available": False,
                "reason": "no reach artifact is loaded; the EV priors have no distribution to drift from",
                "features": [],
            }
        ),
        "models": {
            "reach": reach.version if reach else None,
            "uplift": uplift.version if uplift else None,
            "upliftSegments": len(uplift.segments) if uplift else 0,
        },
    }
    out["alerts"] = _alerts(out)
    return out


def _alerts(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    """The lines somebody should read first, or an empty list.

    Deliberately not a severity score. "Reach is 12 points optimistic" and
    "dpd has moved 0.6σ" want different people and different responses, and
    collapsing them into one number would produce a dashboard that is amber
    forever.
    """
    alerts: list[dict[str, str]] = []
    reach = payload.get("reachCalibration") or {}
    if reach.get("level") in {"warn", "alert"}:
        alerts.append({
            "level": reach["level"],
            "check": "reach_calibration",
            "detail": (
                f"expected calibration error {reach['ece']:.3f} over {reach['n']} "
                "attempts — the EV formula is multiplying rupees by this number"
            ),
        })
    up = payload.get("upliftCalibration") or {}
    if up.get("available") and up.get("level") in {"warn", "alert"}:
        alerts.append({
            "level": up["level"],
            "check": "uplift_calibration",
            "detail": (
                f"predicted mean τ {up['predictedMeanTau']:+.3f} against a measured "
                f"ATE of {up['measuredAte']:+.3f} — {up['note']}"
            ),
        })
    drift = payload.get("featureDrift") or {}
    for feature in (drift.get("features") or []):
        if feature["level"] == "alert":
            alerts.append({
                "level": "alert",
                "check": "feature_drift",
                "detail": (
                    f"{feature['feature']} has moved {feature['shiftSigma']:+.2f}σ "
                    f"from training ({feature['trainedMean']} → {feature['recentMean']})"
                ),
            })
    return alerts
