"""Fitted estimators behind the :class:`Recommender` protocol.

Layer 1 of the design note. Four estimators were specified; three of them are
learned and this module loads all three from the same artifact format:

* **Reach** — P(an attempt reaches a human) by channel, hour and borrower.
* **Payment timing** — the hazard of payment over the next *t* days, which
  replaces the fixed ``urgency_halflife_hours`` decay. *When* to act, derived
  rather than configured.
* **Uplift** — τ(action, x), the incremental cure probability, which replaces
  ``p_resolve``. This is the reframing the whole document is about, and it is
  one term in the EV formula.

The fourth, cost, is accounting plus Layer 3's dual prices and has nothing to
fit.

**Why a linear model and not a gradient-boosted one.** Verbatim the reasoning
``reco.models`` gives, and it applies with more force here: a logistic
regression with recorded coefficients is a small JSON file this service loads,
explains line by line to a regulator, and diffs between versions. It adds no
dependency to an image that sits on the audio path of a live call, and it is a
genuinely strong baseline on the few thousand rows a treatment corpus will hold
for months. The artifact carries a ``type`` field so a GBM can replace it later
without touching anything here but :meth:`ModelArtifact.predict`.

**The fallback chain is the point.** Missing artifact, stale artifact, version
mismatch, malformed JSON, or an exception mid-scoring all degrade to
:class:`EVScorer` and its documented planning priors, warned once per process.
A recommender that can fail a decision is worse than one that is merely less
accurate — and in this package a failed decision means a borrower is either
contacted for no reason or not contacted when they should have been.

**Uplift is gated harder than the other two.** Reach and payment timing are
ordinary supervised problems: they predict something that happens and can be
fitted from any log. τ is the *difference of two noisy quantities* and can only
be estimated where a randomised control arm exists, so :func:`load_uplift`
refuses an artifact that does not name the arm it was fitted against. An uplift
model trained on observational data is a response model wearing the word
"uplift", and it will confidently rank self-curers first — which is the exact
failure the design note exists to prevent.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from agent_core.treatment.features import SCHEMA_VERSION
from agent_core.treatment.segments import (
    SEGMENT_VERSION,
    all_keys as all_segment_keys,
    key_for as segment_key_for,
)

logger = logging.getLogger(__name__)

#: Bumped when the meaning of a feature name changes. The same names scoring
#: different quantities is the one failure an artifact check cannot catch by
#: looking at shapes.
#:
#: t2 added the borrower-type block — return-code one-hots, security, broken
#: promises, disputes, holds. A t1 artifact scored against a t2 vector would
#: silently impute every one of them and report the same confident numbers it
#: always did, which is exactly why the version is checked at load rather than
#: trusted to a changelog.
VECTOR_VERSION = "t2"

#: Observations at which a segment carries half its own weight against the
#: population estimate. A planning figure, chosen to sit just above
#: :data:`MIN_CONTROL_N` so that a stratum which has only just cleared the
#: minimum still leans on the pooled answer rather than replacing it.
DEFAULT_SHRINKAGE_K = 750.0

#: Control-arm observations a single stratum needs before its own halves may
#: pull the population estimate at all. Lower than :data:`MIN_CONTROL_N`
#: because the segment is never used alone — shrinkage means a stratum at this
#: floor moves the answer by about a third — but not much lower, because below
#: a couple of hundred the difference of two rates is mostly the arm split.
MIN_SEGMENT_CONTROL_N = 200

_warned: set[str] = set()
_warn_lock = threading.Lock()


def _warn_once(key: str, message: str, *args: Any) -> None:
    """One warning per distinct reason per process.

    A model that is missing is missing on every decision, and at book-sweep
    volumes a line per decision buries the incident it is trying to report
    under two million copies of itself.
    """
    with _warn_lock:
        if key in _warned:
            return
        _warned.add(key)
    logger.warning(message, *args)


def _reset_warnings() -> None:
    """Test hook — production never calls this."""
    with _warn_lock:
        _warned.clear()


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-min(60.0, x)))
    e = math.exp(max(-60.0, x))
    return e / (1.0 + e)


@dataclass(frozen=True)
class SegmentModel:
    """One stratum's half of the granularity ladder — §9's middle rung.

    Present in an artifact only if the trainer measured it beating the
    population model on the *holdout*. A segment that did not win is simply
    absent, and the population halves answer for it. That is the ladder's rule
    expressed as a data structure rather than as a policy someone has to
    remember: there is no way to ship a segment model that was not measured,
    because there is nowhere to put one.
    """

    key: str
    coefficients: tuple[float, ...]
    intercept: float
    control_coefficients: tuple[float, ...]
    control_intercept: float
    n: int
    control_n: int
    #: Holdout improvement over the population model that earned this its place,
    #: in whatever the trainer scored on. Carried so a model card can show *why*
    #: each surviving segment survived rather than only that it did.
    holdout_lift: float = 0.0

    def weight(self, k: float) -> float:
        """Empirical-Bayes shrinkage weight, ``n / (n + k)``.

        The segment estimate is never used raw. A stratum with 600 observations
        and one with 60,000 are not equally believable, and hard-switching to
        the finer model at some threshold makes the estimate discontinuous
        across a boundary a borrower crosses by aging one day.

        Shrinking toward the population instead makes the ladder continuous: a
        thin segment barely moves off the pooled answer, a fat one dominates it,
        and nobody has to pick the threshold. It is also exactly the machinery
        §14 needs for cross-tenant priors — the only thing that changes there is
        what "the pool" means.
        """
        if self.n <= 0:
            return 0.0
        return self.n / (self.n + max(1.0, k))


@dataclass(frozen=True)
class ModelArtifact:
    """One fitted estimator, loaded from JSON."""

    name: str
    version: str
    kind: str
    #: What the model predicts: 'reach', 'timing' or 'uplift'.
    target: str
    feature_names: tuple[str, ...]
    coefficients: tuple[float, ...]
    intercept: float
    #: Per-feature imputation. An absent feature is filled with the training
    #: mean rather than zero, because in this package ``None`` means "we do not
    #: know" and zero means "we know it is zero" — a borrower we have never
    #: dialled is not a borrower who never answers.
    means: dict[str, float]
    #: Per-feature standard deviation at training time. Not used for scoring —
    #: the coefficients are already folded back onto the raw scale — but it is
    #: the only thing that makes feature drift measurable. "dpd has moved by 11"
    #: is not a finding without knowing whether 11 is a tenth of a standard
    #: deviation or three of them.
    stdevs: dict[str, float] = field(default_factory=dict)
    #: Platt scaling on the logit: p = sigmoid(a·logit + b). Identity when the
    #: trainer did not calibrate, which is honest rather than pretending the
    #: raw output is a probability. A model whose 0.7 does not mean 70% cannot
    #: go into an expected-value formula at all.
    calibration_a: float = 1.0
    calibration_b: float = 0.0
    base_rate: float = 0.1
    trained_at: datetime | None = None
    n_samples: int = 0
    vector_version: str = VECTOR_VERSION
    feature_schema_version: str = SCHEMA_VERSION
    #: Which corpus this was fitted on: 'live' or 'simulated'. A simulated
    #: artifact scores a synthetic book's behaviour, and nothing about the file
    #: itself would tell you that at three in the morning.
    corpus: str = "live"
    #: Uplift only: the arm this was estimated against, and how many
    #: observations it held. Absent means the artifact cannot claim to be causal.
    control_arm: str | None = None
    control_n: int = 0
    #: Uplift only: the control half of a T-learner. τ is a *difference*, and a
    #: single logistic cannot express one — so both halves live in one file,
    #: fitted on the same features, and :meth:`predict` returns
    #: P(cure | treated) − P(cure | untreated).
    #:
    #: Two files would have been the obvious alternative and would have been
    #: worse: nothing would stop the halves being trained on different vintages
    #: of the book, and a τ computed across two months of drift is not a
    #: treatment effect, it is a calendar effect.
    control_coefficients: tuple[float, ...] = ()
    control_intercept: float = 0.0
    #: Uplift only: the strata that beat the population model on the holdout,
    #: keyed by :func:`segments.key_for`. Empty is the normal state and the
    #: honest one — it means no segment has yet earned the finer model.
    segments: dict[str, SegmentModel] = field(default_factory=dict)
    #: Which banding produced those keys. A mismatch is refused rather than
    #: reconciled: the same string means a different population under a
    #: different version, and applying March's partition to August's book is
    #: silent rather than loud.
    segment_version: str = SEGMENT_VERSION
    #: The ``k`` in ``n / (n + k)``. A segment needs roughly this many
    #: observations before it carries half its own weight.
    shrinkage_k: float = DEFAULT_SHRINKAGE_K

    def age_days(self) -> float | None:
        if self.trained_at is None:
            return None
        return (datetime.now(timezone.utc) - self.trained_at).total_seconds() / 86400.0

    def predict(self, vec: Mapping[str, float | None]) -> float:
        """Calibrated probability from a feature vector.

        Takes a raw vector rather than an ``AccountFeatures`` so that offline
        replay can score a historical decision from the vector logged at the
        time — the only leakage-free way to evaluate one, because the DPD, the
        touch counts and the promise history have all moved since, and they
        moved partly *because* of the decision being scored.
        """
        row = [
            float(
                vec.get(n) if vec.get(n) is not None else self.means.get(n, 0.0)
            )
            for n in self.feature_names
        ]
        logit = self.intercept + sum(x * c for x, c in zip(row, self.coefficients))
        treated = _sigmoid(self.calibration_a * logit + self.calibration_b)

        if not self.control_coefficients:
            return treated

        # T-learner: the incremental effect, not the response. Clamped at zero
        # because a negative τ is a real finding — some contact makes things
        # worse — but the EV formula multiplies it by an exposure, and a
        # negative expected recovery would make the action look *better* the
        # more the borrower owes.
        tau = self._tau(row, self.coefficients, self.intercept,
                        self.control_coefficients, self.control_intercept)

        segment = self.segments.get(segment_key_for(vec)) if self.segments else None
        if segment is not None:
            # The granularity ladder, evaluated per borrower rather than per
            # deployment. The population answer is always computed; the segment
            # only pulls it, and only as far as its own sample size earns.
            w = segment.weight(self.shrinkage_k)
            local = self._tau(
                row,
                segment.coefficients,
                segment.intercept,
                segment.control_coefficients,
                segment.control_intercept,
            )
            tau = (1.0 - w) * tau + w * local

        return max(0.0, tau)

    def _tau(
        self,
        row: list[float],
        coefficients: tuple[float, ...],
        intercept: float,
        control_coefficients: tuple[float, ...],
        control_intercept: float,
    ) -> float:
        """P(cure | treated) − P(cure | untreated) for one pair of halves.

        Unclamped: the caller clamps once, after blending. Clamping each half
        would floor a genuinely negative segment effect at zero *before* it
        could pull the population estimate down, which is the one direction a
        segment most needs to be able to move it — "contacting this stratum
        makes things worse" is a finding, not a rounding error.
        """
        treated_logit = intercept + sum(x * c for x, c in zip(row, coefficients))
        control_logit = control_intercept + sum(
            x * c for x, c in zip(row, control_coefficients)
        )
        treated = _sigmoid(self.calibration_a * treated_logit + self.calibration_b)
        untreated = _sigmoid(self.calibration_a * control_logit + self.calibration_b)
        return treated - untreated

    def segment_for(self, vec: Mapping[str, float | None]) -> SegmentModel | None:
        """Which stratum answered for this vector, if a finer one did at all."""
        return self.segments.get(segment_key_for(vec)) if self.segments else None


def _parse_segments(
    raw: Mapping[str, Any], *, n_features: int, path: Path
) -> dict[str, SegmentModel]:
    """Read the segment map, dropping any entry that cannot be trusted.

    Drops rather than refuses the whole artifact, and that asymmetry is
    deliberate. A malformed *population* model has nothing to fall back to, so
    the artifact is refused; a malformed *segment* has the population model
    right behind it, so discarding it costs precision on one stratum and
    nothing else. Refusing the file would take the working strata down with the
    broken one.
    """
    entries = raw.get("segments")
    if not entries:
        return {}
    if not isinstance(entries, dict):
        _warn_once(f"segments:{path}", "artifact at %s has a non-object segments map", path)
        return {}

    version = str(raw.get("segmentVersion") or SEGMENT_VERSION)
    if version != SEGMENT_VERSION:
        # The keys would parse and score. They would just mean a different
        # population than the one they were fitted on, which no shape check can
        # detect — so it has to be caught by the version, here.
        _warn_once(
            f"segver:{path}",
            "artifact at %s carries %s segments, this build partitions on %s"
            " — ignoring its %d segment models",
            path,
            version,
            SEGMENT_VERSION,
            len(entries),
        )
        return {}

    known = set(all_segment_keys())
    out: dict[str, SegmentModel] = {}
    for key, body in entries.items():
        name = str(key)
        if name not in known:
            _warn_once(
                f"segkey:{path}:{name}",
                "artifact at %s has segment %r which this build cannot emit — dropping",
                path,
                name,
            )
            continue
        if not isinstance(body, dict):
            continue
        try:
            coefficients = tuple(float(c) for c in (body.get("coefficients") or []))
            control = tuple(float(c) for c in (body.get("controlCoefficients") or []))
            model = SegmentModel(
                key=name,
                coefficients=coefficients,
                intercept=float(body.get("intercept") or 0.0),
                control_coefficients=control,
                control_intercept=float(body.get("controlIntercept") or 0.0),
                n=int(body.get("n") or 0),
                control_n=int(body.get("controlN") or 0),
                holdout_lift=float(body.get("holdoutLift") or 0.0),
            )
        except (TypeError, ValueError):
            _warn_once(
                f"segnum:{path}:{name}",
                "artifact at %s has non-numeric fields in segment %r — dropping",
                path,
                name,
            )
            continue
        if len(model.coefficients) != n_features or len(model.control_coefficients) != n_features:
            _warn_once(
                f"seglen:{path}:{name}",
                "segment %r in %s has %d/%d coefficients for %d features — dropping",
                name,
                path,
                len(model.coefficients),
                len(model.control_coefficients),
                n_features,
            )
            continue
        if model.control_n < MIN_SEGMENT_CONTROL_N:
            # The same provenance rule as the population model, applied at the
            # granularity that actually risks it. A segment is where a thin
            # control arm hides: the artifact as a whole can hold twenty
            # thousand control observations while one stratum holds nine.
            _warn_once(
                f"segthin:{path}:{name}",
                "segment %r in %s was fitted against %d control observations"
                " (min %d) — dropping",
                name,
                path,
                model.control_n,
                MIN_SEGMENT_CONTROL_N,
            )
            continue
        out[name] = model
    return out


def _parse_trained_at(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        logger.warning("treatment artifact has unparseable trainedAt=%r", raw)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_artifact(
    path: str | Path, *, expect_target: str, allow_simulated: bool | None = None
) -> ModelArtifact | None:
    """Read and validate an artifact. Returns None (never raises) on any fault.

    ``allow_simulated`` overrides ``TREATMENT_ALLOW_SIMULATED_MODELS`` for one
    call. The registry needs it: its own gate has a specific, useful objection
    for a simulated artifact ("promoting it would serve a model of a book that
    does not exist"), and without this the loader would refuse first and the
    operator would be told the file does not parse.

    Validation is strict on purpose: a truncated or hand-edited artifact that
    scores *slightly* wrong is far more dangerous than one that refuses to
    load, because nothing downstream will notice. A refusal costs accuracy and
    is visible in a log line; a silent miscalibration costs borrowers contacts
    they should not have had and shows up months later as a complaint rate.
    """
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _warn_once(f"missing:{p}", "no %s artifact at %s — using the EV priors", expect_target, p)
        return None
    except (OSError, json.JSONDecodeError) as exc:
        _warn_once(f"unreadable:{p}", "%s artifact at %s is unreadable (%s)", expect_target, p, exc)
        return None

    if not isinstance(raw, dict):
        _warn_once(f"shape:{p}", "%s artifact at %s is not an object", expect_target, p)
        return None

    names = raw.get("featureNames")
    coefficients = raw.get("coefficients")
    if not isinstance(names, list) or not isinstance(coefficients, list):
        _warn_once(f"fields:{p}", "%s artifact at %s lacks featureNames/coefficients", expect_target, p)
        return None
    if len(names) != len(coefficients):
        _warn_once(
            f"len:{p}",
            "%s artifact at %s has %d names for %d coefficients",
            expect_target,
            p,
            len(names),
            len(coefficients),
        )
        return None

    try:
        cal = raw.get("calibration") or {}
        metrics = raw.get("metrics") or {}
        artifact = ModelArtifact(
            name=str(raw.get("name") or expect_target),
            version=str(raw.get("version") or "unversioned"),
            kind=str(raw.get("type") or "logistic"),
            target=str(raw.get("target") or ""),
            feature_names=tuple(str(n) for n in names),
            coefficients=tuple(float(c) for c in coefficients),
            intercept=float(raw.get("intercept", 0.0)),
            means={str(k): float(v) for k, v in (raw.get("means") or {}).items()},
            stdevs={str(k): float(v) for k, v in (raw.get("stdevs") or {}).items()},
            calibration_a=float(cal.get("a", 1.0)),
            calibration_b=float(cal.get("b", 0.0)),
            base_rate=min(0.99, max(0.0001, float(metrics.get("baseRate") or 0.1))),
            corpus=str(raw.get("corpus") or "live").strip().lower(),
            trained_at=_parse_trained_at(raw.get("trainedAt")),
            n_samples=int(raw.get("nSamples") or 0),
            vector_version=str(raw.get("vectorVersion") or VECTOR_VERSION),
            feature_schema_version=str(raw.get("featureSchemaVersion") or SCHEMA_VERSION),
            control_arm=(str(raw.get("controlArm")) if raw.get("controlArm") else None),
            control_n=int(raw.get("controlN") or 0),
            control_coefficients=tuple(
                float(c) for c in (raw.get("controlCoefficients") or [])
            ),
            control_intercept=float(raw.get("controlIntercept") or 0.0),
            segments=_parse_segments(raw, n_features=len(names), path=p),
            segment_version=str(raw.get("segmentVersion") or SEGMENT_VERSION),
            shrinkage_k=float(raw.get("shrinkageK") or DEFAULT_SHRINKAGE_K),
        )
    except (TypeError, ValueError) as exc:
        _warn_once(f"numeric:{p}", "%s artifact at %s has non-numeric fields (%s)", expect_target, p, exc)
        return None

    if artifact.kind != "logistic":
        _warn_once(
            f"kind:{p}",
            "%s artifact at %s is type=%r which this build cannot score",
            expect_target,
            p,
            artifact.kind,
        )
        return None
    if artifact.target != expect_target:
        # Loading a reach model where an uplift model was asked for would score
        # every action with the wrong quantity and produce numbers that look
        # entirely reasonable.
        _warn_once(
            f"target:{p}",
            "artifact at %s predicts %r but was loaded as %r — refusing",
            p,
            artifact.target,
            expect_target,
        )
        return None
    # Compatibility is decided here, in one place, so the serving path, offline
    # replay and an operator poking at a file all get the same verdict.
    if artifact.vector_version != VECTOR_VERSION:
        _warn_once(
            f"vector:{p}",
            "%s artifact %s was fitted on vector %s, this build emits %s — refusing",
            expect_target,
            artifact.version,
            artifact.vector_version,
            VECTOR_VERSION,
        )
        return None
    if artifact.feature_schema_version != SCHEMA_VERSION:
        _warn_once(
            f"schema:{p}",
            "%s artifact %s expects feature schema %s, this build emits %s — refusing",
            expect_target,
            artifact.version,
            artifact.feature_schema_version,
            SCHEMA_VERSION,
        )
        return None

    permit_simulated = (
        _allow_simulated_models() if allow_simulated is None else bool(allow_simulated)
    )
    if artifact.corpus == "simulated" and not permit_simulated:
        # The simulator writes a corpus that looks exactly like a real one,
        # because that is the point of it. The consequence is that a model
        # fitted on it also looks exactly like a real model — same shape, same
        # metrics block, plausible coefficients — and would happily rank
        # actions for borrowers who exist.
        #
        # Same predicate discipline as ``mode='simulated'`` on the decisions
        # themselves: one flag on the artifact, one check at the boundary.
        _warn_once(
            f"simulated:{p}",
            "%s artifact %s was fitted on a simulated corpus and this process has "
            "not set TREATMENT_ALLOW_SIMULATED_MODELS — refusing",
            expect_target,
            artifact.version,
        )
        return None

    max_age = _max_age_days()
    age = artifact.age_days()
    if max_age > 0 and age is not None and age > max_age:
        # A stale model is not a wrong model, but a book drifts: the mix of
        # buckets, the mandate population and the reachability of a phone
        # number all move. Refusing loudly beats scoring on last quarter's book
        # and calling it learned.
        _warn_once(
            f"stale:{p}",
            "%s artifact %s is %.0f days old (max %.0f) — refusing",
            expect_target,
            artifact.version,
            age,
            max_age,
        )
        return None
    return artifact


def _allow_simulated_models() -> bool:
    """Opt-in to scoring with a model of a book that does not exist.

    Legitimate for exercising the pipeline end to end before real traffic
    arrives, which is most of what the simulator is for. Never a default.
    """
    return (os.getenv("TREATMENT_ALLOW_SIMULATED_MODELS") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _max_age_days() -> float:
    try:
        return float((os.getenv("TREATMENT_MODEL_MAX_AGE_DAYS") or "90").strip())
    except ValueError:
        return 90.0


def _path(env: str, default: str) -> str:
    return (os.getenv(env) or default).strip()


def load_reach() -> ModelArtifact | None:
    return load_artifact(
        _path("TREATMENT_REACH_MODEL_PATH", "models/treatment_reach.json"),
        expect_target="reach",
    )


def load_timing() -> ModelArtifact | None:
    return load_artifact(
        _path("TREATMENT_TIMING_MODEL_PATH", "models/treatment_timing.json"),
        expect_target="timing",
    )


#: Minimum control-arm observations before an uplift artifact is allowed to
#: score anything. A planning figure, and the number the granularity ladder
#: turns on: τ is the difference of two noisy quantities, so a control arm of a
#: few hundred produces confident noise — which is strictly worse than the
#: current priors, because it *looks* learned.
MIN_CONTROL_N = 500


def load_uplift() -> ModelArtifact | None:
    """The causal estimator, and the only one with a provenance requirement.

    Refuses any artifact that does not name the randomised arm it was fitted
    against, and any whose control arm is too small to have measured anything.
    Uplift fitted on observational data is a response model with a different
    label on it: it will rank borrowers who cure on their own at the top,
    because they do have the highest absolute repayment probability, and the
    engine will spend its most expensive capacity on people who needed nothing.

    That failure is invisible in every offline metric except the one that
    compares against a control arm — so the check has to be here, at load time,
    rather than left to whoever reads the model card.
    """
    artifact = load_artifact(
        _path("TREATMENT_UPLIFT_MODEL_PATH", "models/treatment_uplift.json"),
        expect_target="uplift",
    )
    if artifact is None:
        return None
    if not artifact.control_arm:
        _warn_once(
            "uplift:no-arm",
            "uplift artifact %s names no control arm — it cannot be causal, refusing",
            artifact.version,
        )
        return None
    if len(artifact.control_coefficients) != len(artifact.coefficients):
        _warn_once(
            "uplift:half",
            "uplift artifact %s has no matching control half — it is a response"
            " model, not a treatment effect. Refusing.",
            artifact.version,
        )
        return None
    if artifact.control_n < MIN_CONTROL_N:
        _warn_once(
            "uplift:thin-arm",
            "uplift artifact %s was fitted against %d control observations (min %d) — refusing",
            artifact.version,
            artifact.control_n,
            MIN_CONTROL_N,
        )
        return None
    return artifact


# ---------------------------------------------------------------------------
# The scorer
# ---------------------------------------------------------------------------


#: Keys of :func:`scoring.vector` a trainer must never select as features.
#:
#: They are outputs of the baseline scorer, computed from the very priors these
#: models exist to replace. A reach model fitted with ``p_reach`` in its inputs
#: learns to copy ``REACH_PRIOR`` and reports an excellent holdout score for
#: doing so; an uplift model fitted with ``p_resolve`` learns ``RESOLVE_PRIOR``
#: and calls it a treatment effect. Neither failure is visible in any metric
#: that does not know where the column came from.
SCORER_DERIVED_KEYS: frozenset[str] = frozenset({"p_reach", "p_resolve", "cost"})


def trainable_features(vector_keys: Any) -> tuple[str, ...]:
    """The subset of a logged vector a trainer may fit on, in stable order."""
    return tuple(sorted(k for k in vector_keys if k not in SCORER_DERIVED_KEYS))


class EstimatorScorer:
    """``EVScorer`` with its priors replaced, one term at a time.

    Wraps rather than reimplements, and substitutes term by term rather than
    all at once. That is the whole design: reach and payment timing are
    ordinary supervised problems that can be fitted from any log, while τ needs
    a randomised arm and will be months behind them. A scorer that demanded all
    three would keep the two that are ready sitting on a shelf.

    Each substitution is independent and each falls back on its own. With no
    artifacts at all this scores byte-identically to ``EVScorer``.

    The formula, once every term is learned::

        EV = exposure × recovery × P(still unpaid at t) × P(reach) × τ − cost − fatigue

    ``P(still unpaid at t)`` is the timing model standing in for the fixed
    half-life, and it composes with τ rather than double-counting it: τ is the
    incremental effect *given we act*, and this is the chance acting is still
    relevant when it lands. A borrower who has already paid cannot be moved by
    anything.
    """

    version = "1.0.0"

    def __init__(
        self,
        base: Any,
        *,
        reach: ModelArtifact | None = None,
        timing: ModelArtifact | None = None,
        uplift: ModelArtifact | None = None,
    ) -> None:
        self._base = base
        self._reach = reach
        self._timing = timing
        self._uplift = uplift
        fitted = [
            n for n, a in (("reach", reach), ("timing", timing), ("uplift", uplift)) if a
        ]
        # The name records *which* estimators were live for this decision, and
        # it lands in treatment_decisions.recommender. Without that a corpus
        # spanning a rollout cannot be split by which model produced each row,
        # and the champion/challenger comparison silently mixes them.
        self.name = "ev+" + "+".join(fitted) if fitted else "ev"

    def score(
        self,
        features: Any,
        trigger: Any,
        candidates: Any,
        *,
        now: datetime,
        policy: Any,
        costs: Any,
    ) -> list[Any]:

        from agent_core.treatment import actions as A

        scored = self._base.score(
            features, trigger, candidates, now=now, policy=policy, costs=costs
        )
        if not (self._reach or self._timing or self._uplift):
            return scored

        out: list[Any] = []
        for s in scored:
            if s.action == A.WAIT:
                out.append(s)
                continue
            try:
                out.append(
                    self._rescore(
                        s, features, trigger, now=now, policy=policy, costs=costs
                    )
                )
            except Exception:
                # One action that cannot be re-scored keeps its prior-based
                # value rather than costing the whole decision. A model is an
                # improvement to a working system, not a dependency of it.
                logger.exception("estimator rescore failed for %s", s.action)
                out.append(s)

        out.sort(key=lambda s: (-s.expected_value, s.rung, s.action))
        return out

    def _rescore(
        self, s: Any, features: Any, trigger: Any, *, now: datetime, policy: Any, costs: Any
    ) -> Any:
        from dataclasses import replace

        from agent_core.treatment import actions as A
        from agent_core.treatment import scoring

        vec = scoring.vector(features, trigger, s, now=now)
        reasons = list(s.reason_codes)

        reach = s.p_reach
        if self._reach is not None and A.spec(s.action).channel is not None:
            reach = max(0.01, min(0.95, self._reach.predict(vec)))
            reasons.append("reach_from_model")

        resolve = s.p_resolve
        if self._uplift is not None:
            # τ, not P(cure | contacted). The difference is the entire point of
            # the reframing: a response model ranks a borrower who would have
            # paid anyway at the top, because they genuinely do have the
            # highest absolute repayment probability.
            resolve = max(0.0, min(0.95, self._uplift.predict(vec)))
            reasons.append("uplift_from_model")

        decay = s.components.get("urgency_decay", 1.0)
        if self._timing is not None:
            # P(the account resolves on its own before this lands). Acting late
            # is worth less because the borrower may no longer need us — which
            # is the honest version of what the half-life was approximating.
            already = max(0.0, min(0.99, self._timing.predict(vec)))
            decay = 1.0 - already
            reasons.append("timing_from_model")

        exposure = s.components.get("exposure", features.exposure)
        value = exposure * policy.recovery_fraction * scoring.VALUE_HORIZON.get(
            s.action, 1.0
        )
        gross = value * reach * resolve * decay
        cost = s.cost
        fatigue = -s.components.get("fatigue", 0.0)

        return replace(
            s,
            expected_value=gross - cost - fatigue,
            p_reach=reach,
            p_resolve=resolve,
            reason_codes=tuple(reasons),
            components={
                **s.components,
                "p_reach": reach,
                "p_resolve": resolve,
                "urgency_decay": decay,
                "gross": gross,
            },
        )


def build(base: Any) -> Any:
    """Wrap ``base`` in whatever estimators are loadable right now.

    Returns ``base`` unchanged when none are, which is what makes this safe to
    call unconditionally from ``scoring.build_scorer``.
    """
    reach, timing, uplift = load_reach(), load_timing(), load_uplift()
    if not (reach or timing or uplift):
        return base
    return EstimatorScorer(base, reach=reach, timing=timing, uplift=uplift)
