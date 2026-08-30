"""Off-policy evaluation — what a *different* policy would have recovered.

Layer 4 of the design note. The corpus records what the engine did and what
happened; this answers the question that actually gates a rollout, which is what
would have happened if it had done something else. Without it a challenger can
only be promoted by running it on borrowers, and "we tried it on ten thousand
people and it was worse" is an expensive way to learn.

Three estimators, in the order they should be trusted:

* **IPS** — inverse propensity scoring. Unbiased, and high variance. Reweights
  each logged reward by how much more (or less) likely the candidate policy was
  to take the action that was actually taken.
* **SNIPS** — the self-normalised form. Divides by the sum of the weights rather
  than by *n*. Slightly biased, far lower variance, and bounded by the range of
  the observed rewards — which matters because an unnormalised IPS estimate can
  and does exceed the largest reward anybody actually received.
* **Doubly robust** — combines a reward model with the importance weights, and
  is consistent if *either* is right. The one to quote when a reward model
  exists.

**The diagnostics are not optional and are reported alongside every estimate.**
An off-policy number without them is worse than no number, because it is a
number:

* **Effective sample size.** ``(Σw)² / Σw²``. Ten thousand rows with an ESS of
  forty is an estimate computed from forty rows wearing ten thousand rows'
  confidence interval.
* **Unsupported actions.** IPS is only valid under common support: the
  candidate policy may not put mass where the logging policy had none. A
  deterministic logging policy has support on exactly one action per decision,
  so *every* disagreement is unsupported — which is precisely why exploration
  had to come first, and why this module reports the count rather than quietly
  contributing a zero.
* **Clipping.** Weights are capped, because one row with a propensity of 1e-5
  contributes a weight of 100,000 and swamps the corpus. Capping trades a
  little bias for an estimate that is not a single borrower's opinion.

**Arms cancel, so evaluation happens within one.** The logged ``propensity``
column is P(arm) × P(action | arm); the per-candidate propensities in
``candidates[]`` are P(action | arm) alone. Comparing rankings is a within-arm
question and uses the latter, so the arm assignment divides out. The control arm
is not for this — it measures the treatment effect itself, by difference of
means, and needs no importance weights at all.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

#: Largest importance weight any single observation may contribute.
#:
#: A propensity of 1e-5 buys a weight of 100,000, and one such row decides the
#: estimate on its own. The cap is a bias/variance trade made explicitly and
#: reported, rather than an unbounded estimator that is technically unbiased and
#: practically a coin flip.
MAX_WEIGHT = 50.0

#: Below this share of the sample, an estimate is reported but should not be
#: acted on. Not enforced here — refusing to compute would hide the diagnostic
#: that explains why — but :meth:`Estimate.trustworthy` says so.
MIN_ESS_FRACTION = 0.10

#: Above this share of unsupported decisions the estimate is describing a
#: different population from the one the policy would act on.
MAX_UNSUPPORTED_FRACTION = 0.35


@dataclass(frozen=True)
class Observation:
    """One logged decision, reduced to what an estimator needs."""

    decision_id: str
    action: str
    reward: float
    #: π_log(a|x) for the action taken, within its arm.
    propensity: float
    #: π_log(·|x) over the whole approved set. Needed by doubly-robust, which
    #: has to evaluate the candidate policy's expectation over actions nobody
    #: took.
    support: Mapping[str, float] = field(default_factory=dict)
    #: action → the candidate entry logged at decision time, vector included.
    candidates: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    variant: str | None = None


#: A candidate policy: given the logged candidates, what would it have done?
#: Returns a distribution over actions. Deterministic policies return a single
#: action at 1.0, which is fine and common.
Policy = Callable[[Mapping[str, Mapping[str, Any]]], Mapping[str, float]]

#: A reward model: given a decision's candidates and one action, the expected
#: reward. Only doubly-robust needs one.
RewardModel = Callable[[Mapping[str, Mapping[str, Any]], str], float]


@dataclass(frozen=True)
class Estimate:
    method: str
    value: float
    stderr: float
    n: int
    ess: float
    clipped: int
    unsupported: int
    #: The logged policy's own average reward, for comparison. Computing it here
    #: rather than leaving it to the caller means the two numbers always come
    #: from exactly the same rows.
    baseline: float = 0.0

    @property
    def ess_fraction(self) -> float:
        return self.ess / self.n if self.n else 0.0

    @property
    def unsupported_fraction(self) -> float:
        return self.unsupported / self.n if self.n else 0.0

    @property
    def lift(self) -> float:
        return self.value - self.baseline

    @property
    def trustworthy(self) -> bool:
        """Whether this estimate should be allowed to promote anything.

        Three ways to fail, and the first two are what make off-policy
        evaluation dangerous rather than merely uncertain: an estimate can be
        precise, plausible and computed from four rows.
        """
        return (
            self.n > 0
            and self.ess_fraction >= MIN_ESS_FRACTION
            and self.unsupported_fraction <= MAX_UNSUPPORTED_FRACTION
        )

    def to_log(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "value": round(self.value, 4),
            "baseline": round(self.baseline, 4),
            "lift": round(self.lift, 4),
            "stderr": round(self.stderr, 4),
            "n": self.n,
            "ess": round(self.ess, 1),
            "essFraction": round(self.ess_fraction, 3),
            "unsupported": self.unsupported,
            "clipped": self.clipped,
            "trustworthy": self.trustworthy,
        }


# ---------------------------------------------------------------------------
# Estimators
# ---------------------------------------------------------------------------


def _weights(
    observations: Sequence[Observation], policy: Policy
) -> tuple[list[float], list[float], int, int]:
    """Per-observation importance weights, plus the two diagnostics.

    Returns ``(weights, rewards, clipped, unsupported)``. An unsupported
    observation contributes a weight of zero *and* is counted, because a zero
    that is not reported reads as "this policy would have earned nothing there"
    rather than "we cannot say".
    """
    weights: list[float] = []
    rewards: list[float] = []
    clipped = unsupported = 0

    for obs in observations:
        target = policy(obs.candidates)
        p_new = float(target.get(obs.action, 0.0))
        p_log = float(obs.propensity)

        if p_log <= 0:
            # The log says this action could not have been taken, yet it was.
            # A corrupt row rather than a small probability, so it is dropped
            # rather than divided by.
            unsupported += 1
            weights.append(0.0)
            rewards.append(obs.reward)
            continue

        # Does the candidate policy want to do something the log never tried?
        # That is the failure common support exists to catch, and it is invisible
        # in the estimate itself: those decisions simply contribute nothing, so
        # the policy is evaluated only where it happens to agree.
        if any(
            weight > 0 and float(obs.support.get(action, 0.0)) <= 0
            for action, weight in target.items()
        ):
            unsupported += 1

        w = p_new / p_log
        if w > MAX_WEIGHT:
            w = MAX_WEIGHT
            clipped += 1
        weights.append(w)
        rewards.append(obs.reward)

    return weights, rewards, clipped, unsupported


def _ess(weights: Sequence[float]) -> float:
    total = sum(weights)
    squares = sum(w * w for w in weights)
    return (total * total / squares) if squares > 0 else 0.0


def _baseline(observations: Sequence[Observation]) -> float:
    return (
        sum(o.reward for o in observations) / len(observations) if observations else 0.0
    )


def ips(observations: Sequence[Observation], policy: Policy) -> Estimate:
    """Inverse propensity scoring. Unbiased, high variance."""
    weights, rewards, clipped, unsupported = _weights(observations, policy)
    n = len(observations)
    if not n:
        return Estimate("ips", 0.0, 0.0, 0, 0.0, 0, 0)

    terms = [w * r for w, r in zip(weights, rewards)]
    value = sum(terms) / n
    variance = sum((t - value) ** 2 for t in terms) / max(1, n - 1)
    return Estimate(
        method="ips",
        value=value,
        stderr=math.sqrt(variance / n),
        n=n,
        ess=_ess(weights),
        clipped=clipped,
        unsupported=unsupported,
        baseline=_baseline(observations),
    )


def snips(observations: Sequence[Observation], policy: Policy) -> Estimate:
    """Self-normalised IPS. Slightly biased, much lower variance.

    Normalising by the sum of the weights rather than by *n* bounds the estimate
    within the range of observed rewards. Plain IPS has no such bound and will
    cheerfully report a cure rate above one when a handful of low-propensity
    rows happen to be positive — a number that is unbiased in expectation and
    useless in the hand.
    """
    weights, rewards, clipped, unsupported = _weights(observations, policy)
    n = len(observations)
    total = sum(weights)
    if not n or total <= 0:
        return Estimate(
            "snips", 0.0, 0.0, n, 0.0, clipped, unsupported, _baseline(observations)
        )

    value = sum(w * r for w, r in zip(weights, rewards)) / total
    # Variance of a ratio estimator, first-order. Good enough to tell "this is
    # a real difference" from "this is noise", which is the only question being
    # asked of it.
    residual = sum((w * (r - value)) ** 2 for w, r in zip(weights, rewards))
    return Estimate(
        method="snips",
        value=value,
        stderr=math.sqrt(residual) / total if total > 0 else 0.0,
        n=n,
        ess=_ess(weights),
        clipped=clipped,
        unsupported=unsupported,
        baseline=_baseline(observations),
    )


def doubly_robust(
    observations: Sequence[Observation],
    policy: Policy,
    reward_model: RewardModel,
) -> Estimate:
    """Consistent if *either* the reward model or the propensities are right.

    The direct-method term carries the estimate where the importance weights
    have no support, and the weighted-residual term corrects the reward model
    where they do. That is why this is the one to quote once a reward model
    exists: a deterministic stretch of the log contributes a modelled value
    instead of contributing nothing.
    """
    weights, rewards, clipped, unsupported = _weights(observations, policy)
    n = len(observations)
    if not n:
        return Estimate("dr", 0.0, 0.0, 0, 0.0, 0, 0)

    terms: list[float] = []
    for obs, w, r in zip(observations, weights, rewards):
        target = policy(obs.candidates)
        direct = sum(
            prob * reward_model(obs.candidates, action)
            for action, prob in target.items()
            if prob > 0
        )
        taken = reward_model(obs.candidates, obs.action)
        terms.append(direct + w * (r - taken))

    value = sum(terms) / n
    variance = sum((t - value) ** 2 for t in terms) / max(1, n - 1)
    return Estimate(
        method="dr",
        value=value,
        stderr=math.sqrt(variance / n),
        n=n,
        ess=_ess(weights),
        clipped=clipped,
        unsupported=unsupported,
        baseline=_baseline(observations),
    )


# ---------------------------------------------------------------------------
# Candidate policies
# ---------------------------------------------------------------------------


def greedy_on_logged_ev(candidates: Mapping[str, Mapping[str, Any]]) -> dict[str, float]:
    """The policy the engine would follow with exploration switched off.

    Useful as a sanity check rather than as a challenger: evaluated against a
    log produced by the *same* ranking, it should come out at or slightly above
    the logged average, and if it does not, something upstream is wrong.
    """
    best = _argmax(candidates, lambda entry: float(entry.get("expectedValue") or 0.0))
    return {best: 1.0} if best else {}


def greedy_on(score: Callable[[Mapping[str, Any]], float]) -> Policy:
    """A deterministic policy that ranks by an arbitrary score of the log entry."""

    def _policy(candidates: Mapping[str, Mapping[str, Any]]) -> dict[str, float]:
        best = _argmax(candidates, score)
        return {best: 1.0} if best else {}

    return _policy


def estimator_policy(
    *,
    reach: Any = None,
    uplift: Any = None,
    timing: Any = None,
    recovery_fraction: float = 0.35,
) -> Policy:
    """Rank by re-scoring the *logged* vectors with fitted estimators.

    The only leakage-free way to ask "would the learned scorer have chosen
    better?". Rebuilding features now for a decision made in March would leak
    the outcome into the inputs — the DPD and the touch counts have moved since,
    and they moved partly because of the decision being evaluated.
    """

    def _score(entry: Mapping[str, Any]) -> float:
        vec = entry.get("vector")
        if not isinstance(vec, Mapping):
            # No vector, no re-score. Falling back to the logged EV keeps the
            # row in the comparison instead of silently ranking it last.
            return float(entry.get("expectedValue") or 0.0)
        components = entry.get("components") or {}
        exposure = float(components.get("exposure") or 0.0)
        p_reach = (
            reach.predict(vec) if reach is not None else float(entry.get("pReach") or 0.0)
        )
        tau = (
            uplift.predict(vec)
            if uplift is not None
            else float(entry.get("pResolve") or 0.0)
        )
        decay = (
            1.0 - timing.predict(vec)
            if timing is not None
            else float(components.get("urgency_decay") or 1.0)
        )
        cost = float(entry.get("cost") or 0.0)
        fatigue = -float(components.get("fatigue") or 0.0)
        return exposure * recovery_fraction * p_reach * tau * decay - cost - fatigue

    return greedy_on(_score)


def _argmax(
    candidates: Mapping[str, Mapping[str, Any]], score: Callable[[Mapping[str, Any]], float]
) -> str | None:
    best: str | None = None
    best_score = float("-inf")
    # Sorted so ties break deterministically and two runs of the same evaluation
    # cannot disagree — the same guarantee EVScorer makes for the same reason.
    for action in sorted(candidates):
        value = score(candidates[action])
        if value > best_score:
            best, best_score = action, value
    return best


# ---------------------------------------------------------------------------
# Reward models
# ---------------------------------------------------------------------------


def logged_ev_reward(recovery_fraction: float = 1.0) -> RewardModel:
    """The engine's own expected value, as the direct-method term.

    Deliberately naive: this is the model the policy was already using, so
    doubly-robust with it is "trust the weights where there is support, trust
    the priors elsewhere". A fitted reward model replaces it and the estimator
    does not change.
    """

    def _reward(candidates: Mapping[str, Mapping[str, Any]], action: str) -> float:
        entry = candidates.get(action) or {}
        components = entry.get("components") or {}
        gross = float(components.get("gross") or 0.0)
        exposure = float(components.get("exposure") or 0.0) or 1.0
        # Normalised to a cure-probability scale so it is comparable with a
        # 0/1 reward. An estimate that mixes rupees and indicators is a number
        # with no units.
        return min(1.0, gross / (exposure * recovery_fraction)) if exposure else 0.0

    return _reward


# ---------------------------------------------------------------------------
# Loading a corpus
# ---------------------------------------------------------------------------

#: Outcomes that count as the borrower resolving. ``ptp`` is included because a
#: promise is what a collections floor is measured on and what the engine is
#: asked to produce; excluding it would score the engine on payments it was
#: never trying to collect on the day.
CURED = frozenset({"paid", "ptp"})


def observations(
    conn: Any,
    *,
    modes: Sequence[str] = ("shadow", "live"),
    variant: str | None = None,
    exclude_variants: Sequence[str] = ("null_treatment", "holdout"),
    limit: int | None = None,
) -> list[Observation]:
    """Read the corpus into evaluable observations.

    Untreated arms are excluded by default. They are not a different ranking of
    the same actions — they are the absence of one — so importance-weighting
    them against a policy that acts would be comparing a policy with a
    condition. Their job is the difference of means in :func:`treatment_effect`.
    """
    from sqlalchemy import text

    clauses = ["mode = ANY(:modes)", "outcome IS NOT NULL", "propensity IS NOT NULL"]
    params: dict[str, Any] = {"modes": list(modes)}
    if variant:
        clauses.append("variant = :variant")
        params["variant"] = variant
    elif exclude_variants:
        clauses.append("(variant IS NULL OR variant <> ALL(:excluded))")
        params["excluded"] = list(exclude_variants)

    sql = f"""
        SELECT id, chosen_action, outcome, propensity, variant, candidates
        FROM treatment_decisions
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at ASC
    """
    if limit:
        sql += " LIMIT :limit"
        params["limit"] = int(limit)

    out: list[Observation] = []
    for row in conn.execute(text(sql), params).mappings():
        entries = row["candidates"]
        if not isinstance(entries, list):
            continue
        by_action = {
            str(e.get("action")): e
            for e in entries
            if isinstance(e, Mapping) and e.get("action")
        }
        support = {
            action: float(entry["propensity"])
            for action, entry in by_action.items()
            if entry.get("propensity") is not None
        }
        chosen = str(row["chosen_action"] or "")
        # Within-arm propensity. The top-level column carries the arm factor
        # too, and using it here would weight every row by the inverse of its
        # arm share — which is a correction for a comparison nobody is making.
        p_log = support.get(chosen)
        if p_log is None or p_log <= 0:
            continue
        out.append(
            Observation(
                decision_id=str(row["id"]),
                action=chosen,
                reward=1.0 if str(row["outcome"]) in CURED else 0.0,
                propensity=p_log,
                support=support,
                candidates=by_action,
                variant=row["variant"],
            )
        )
    return out


@dataclass(frozen=True)
class TreatmentEffect:
    """The one causal number, and it needs no importance weights."""

    treated_n: int
    control_n: int
    treated_rate: float
    control_rate: float

    @property
    def ate(self) -> float:
        return self.treated_rate - self.control_rate

    @property
    def stderr(self) -> float:
        """Standard error of a difference of two proportions."""

        def _var(p: float, n: int) -> float:
            return p * (1 - p) / n if n else 0.0

        return math.sqrt(_var(self.treated_rate, self.treated_n) + _var(self.control_rate, self.control_n))

    @property
    def significant(self) -> bool:
        """Two standard errors clear of zero. Not a p-value, and not pretending to be."""
        return abs(self.ate) > 2 * self.stderr if self.stderr > 0 else False

    def to_log(self) -> dict[str, Any]:
        return {
            "treatedN": self.treated_n,
            "controlN": self.control_n,
            "treatedRate": round(self.treated_rate, 4),
            "controlRate": round(self.control_rate, 4),
            "ate": round(self.ate, 4),
            "stderr": round(self.stderr, 4),
            "significant": self.significant,
        }


def treatment_effect(
    conn: Any,
    *,
    modes: Sequence[str] = ("shadow", "live"),
    control_arm: str = "null_treatment",
) -> TreatmentEffect:
    """Cure rate in the treated arms minus the randomised control arm.

    A difference of means, deliberately. The arm assignment *is* the
    randomisation, so no reweighting is needed and none is applied — reaching
    for an importance-weighted estimator here would add variance to answer a
    question that has already been answered by design.
    """
    from sqlalchemy import text

    rows = conn.execute(
        text(
            """
            SELECT (variant = :arm) AS is_control,
                   count(*)::int AS n,
                   count(*) FILTER (WHERE outcome = ANY(:cured))::int AS cured
            FROM treatment_decisions
            WHERE mode = ANY(:modes) AND outcome IS NOT NULL
            GROUP BY 1
            """
        ),
        {"arm": control_arm, "modes": list(modes), "cured": sorted(CURED)},
    ).mappings().all()

    treated = next((r for r in rows if not r["is_control"]), None)
    control = next((r for r in rows if r["is_control"]), None)
    t_n = int(treated["n"]) if treated else 0
    c_n = int(control["n"]) if control else 0
    return TreatmentEffect(
        treated_n=t_n,
        control_n=c_n,
        treated_rate=(int(treated["cured"]) / t_n) if t_n else 0.0,
        control_rate=(int(control["cured"]) / c_n) if c_n else 0.0,
    )
