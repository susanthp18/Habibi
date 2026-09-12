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
from typing import Any, Callable, Mapping, Sequence

from agent_core.treatment import cluster, scoring, sequence

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
#:
#: **The share is of borrowers, not of rows.** §8.9 Tier 0: ESS is "computed on
#: customer-aggregated weights with the cluster count printed beside it". The
#: row figure is still reported, because the two differing by an order of
#: magnitude is itself the diagnostic — measured on this corpus 2026-09-10, the
#: row ESS is 97.3 of 124 (0.78, comfortably past this floor) while the
#: customer ESS is 9.45 of 10 borrowers. The first number is the one that used
#: to gate and it describes a precision the estimate does not have.
MIN_ESS_FRACTION = 0.10

#: Above this share of unsupported decisions the estimate is describing a
#: different population from the one the policy would act on.
MAX_UNSUPPORTED_FRACTION = 0.35

#: The largest share of total importance weight one borrower may contribute
#: before a gate evaluation is refused.
#:
#: §8.3: "cap and report single-row and single-customer leverage, refusing any
#: gate evaluation where one customer contributes more than a stated share."
#: A quarter is that stated share. It is a governance number rather than a
#: derived one — the point is that *somebody's* opinion decided a promotion and
#: the gate can say whose — and the leverage itself is published either way, so
#: a refusal at 26% and a pass at 24% are both legible.
MAX_CUSTOMER_LEVERAGE = 0.25

#: The logging contract a row must carry to be evaluable.
#:
#: ``sql/05_collections.sql``: "Pre-cutover rows keep logging_contract_version
#: = 1 and are excluded from OPE." Contract-1 rows fuse P(arm) and P(action|arm)
#: into one column, so an importance weight built from them is weighted by the
#: inverse of its arm share as well — a correction for a comparison nobody is
#: making. The schema said so from W2 and nothing enforced it, which is why
#: :func:`observations` reads all 278 live rows on `collections` today and every
#: one of them is contract 1.
MIN_LOGGING_CONTRACT = 2


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
    #: The cluster. Arm membership is randomised per customer (§8.7), so this is
    #: the unit every standard error below must be computed over. Its absence is
    #: what made every interval this module published treat one borrower's
    #: fortnight of daily sweeps as fourteen independent observations.
    customer_id: str | None = None


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
    #: Distinct borrowers behind the estimate. §8.8: below ~40 clusters an
    #: interval's coverage is not what it claims, so this is published beside
    #: every number and gates promotion alongside ESS.
    clusters: int = 0
    #: The logged policy's own average reward, for comparison. Computing it here
    #: rather than leaving it to the caller means the two numbers always come
    #: from exactly the same rows.
    baseline: float = 0.0
    #: ESS over weights summed **within each borrower** — §8.9 Tier 0, and the
    #: one that gates. ``ess`` above is the row figure, kept and reported so the
    #: gap between them is visible rather than merely corrected.
    ess_customers: float = 0.0
    #: The largest borrower's share of total weight. §8.3's leverage cap.
    max_customer_share: float = 0.0

    @property
    def ess_fraction(self) -> float:
        """Customer ESS over borrowers. The share §8.9 means."""
        return self.ess_customers / self.clusters if self.clusters else 0.0

    @property
    def row_ess_fraction(self) -> float:
        """Row ESS over rows — what this used to gate on, kept for the contrast."""
        return self.ess / self.n if self.n else 0.0

    @property
    def unsupported_fraction(self) -> float:
        return self.unsupported / self.n if self.n else 0.0

    @property
    def lift(self) -> float:
        return self.value - self.baseline

    @property
    def objections(self) -> list[str]:
        """Every reason this estimate may not promote anything, with its number.

        Returned rather than reduced to a boolean, because "untrustworthy" sends
        an operator looking and "9.45 effective borrowers out of 10" tells them
        what to do about it. The failures here are what make off-policy
        evaluation dangerous rather than merely uncertain: an estimate can be
        precise, plausible and computed from four borrowers. The cluster floor
        catches that last case — four hundred decisions on four borrowers passes
        every row-count check ever written — and the leverage cap catches the
        case underneath it, where forty borrowers are present and one of them
        decides the answer.
        """
        out: list[str] = []
        if self.n <= 0:
            return ["no evaluable observations"]
        if self.clusters < cluster.MIN_CLUSTERS:
            out.append(
                f"{self.clusters} borrowers against the {cluster.MIN_CLUSTERS} the "
                "cluster bootstrap needs (§8.12 gate 8)"
            )
        if self.ess_fraction < MIN_ESS_FRACTION:
            out.append(
                f"effective sample size is {self.ess_customers:.2f} borrowers of "
                f"{self.clusters} ({self.ess_fraction:.1%}), below the "
                f"{MIN_ESS_FRACTION:.0%} floor (§8.9 tier 0)"
            )
        if self.max_customer_share > MAX_CUSTOMER_LEVERAGE:
            out.append(
                f"one borrower carries {self.max_customer_share:.1%} of the total "
                f"weight, above the {MAX_CUSTOMER_LEVERAGE:.0%} leverage cap (§8.3)"
            )
        if self.unsupported_fraction > MAX_UNSUPPORTED_FRACTION:
            out.append(
                f"{self.unsupported} of {self.n} decisions are unsupported "
                f"({self.unsupported_fraction:.1%}), above the "
                f"{MAX_UNSUPPORTED_FRACTION:.0%} ceiling — the estimate describes a "
                "different population from the one the policy would act on"
            )
        return out

    @property
    def trustworthy(self) -> bool:
        """Whether this estimate should be allowed to promote anything."""
        return not self.objections

    def to_log(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "value": round(self.value, 4),
            "baseline": round(self.baseline, 4),
            "lift": round(self.lift, 4),
            "stderr": round(self.stderr, 4),
            "n": self.n,
            # Both, always. §8.9 asks for the customer figure and the row figure
            # is what a reader will assume they are looking at otherwise.
            "ess": round(self.ess, 1),
            "rowEssFraction": round(self.row_ess_fraction, 3),
            "essCustomers": round(self.ess_customers, 2),
            "essFraction": round(self.ess_fraction, 3),
            "maxCustomerShare": round(self.max_customer_share, 4),
            "unsupported": self.unsupported,
            "clipped": self.clipped,
            "clusters": self.clusters,
            "trustworthy": self.trustworthy,
            "objections": self.objections,
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


def _clusters(observations: Sequence[Observation]) -> int:
    return len({o.customer_id for o in observations if o.customer_id})


def _by_customer(
    observations: Sequence[Observation], weights: Sequence[float]
) -> dict[str, float]:
    """Total importance weight per borrower. The unit every diagnostic uses."""
    totals: dict[str, float] = {}
    for obs, w in zip(observations, weights):
        key = obs.customer_id or obs.decision_id
        totals[key] = totals.get(key, 0.0) + w
    return totals


def _diagnostics(
    observations: Sequence[Observation], weights: Sequence[float]
) -> dict[str, Any]:
    """§8.9 Tier 0's diagnostics, computed once and passed to every estimator.

    The row ESS and the customer ESS are both here deliberately. Reporting only
    the corrected one would leave nobody able to see how far off the old number
    was, and on this book it was off by a factor of ten.
    """
    per_customer = _by_customer(observations, weights)
    total = sum(per_customer.values())
    return {
        "ess": _ess(weights),
        "ess_customers": _ess(list(per_customer.values())),
        "max_customer_share": (max(per_customer.values()) / total) if total > 0 else 0.0,
        "clusters": _clusters(observations),
    }


def _clustered_stderr(
    observations: Sequence[Observation], terms: Sequence[float]
) -> float:
    """Cluster-robust standard error of the mean of ``terms``, on the customer.

    ``sqrt(variance / n)`` assumes the terms are independent draws. They are not:
    arm membership is randomised per customer (§8.7), so the residuals of one
    borrower's decisions move together and the i.i.d. formula understates the
    error by roughly ``sqrt(1 + (m-1)*ICC)`` -- a factor of 1.8 at the design
    effect measured on this book.

    The estimator is the standard CR0 sandwich for a mean: sum the residuals
    *within* each cluster first, square the cluster totals, and apply the
    finite-cluster correction ``G/(G-1)``. With one observation per cluster it
    reduces exactly to the i.i.d. form, so nothing that was already independent
    changes.
    """
    n = len(terms)
    if n == 0:
        return 0.0
    mean = sum(terms) / n
    totals: dict[str, float] = {}
    for obs, term in zip(observations, terms):
        key = obs.customer_id or obs.decision_id
        totals[key] = totals.get(key, 0.0) + (term - mean)
    g = len(totals)
    if g < 2:
        variance = sum((t - mean) ** 2 for t in terms) / max(1, n - 1)
        return math.sqrt(variance / n)
    meat = sum(v * v for v in totals.values())
    return math.sqrt(meat * (g / (g - 1.0))) / n


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
    return Estimate(
        method="ips",
        value=value,
        stderr=_clustered_stderr(observations, terms),
        n=n,
        clipped=clipped,
        unsupported=unsupported,
        baseline=_baseline(observations),
        **_diagnostics(observations, weights),
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
        # Keyword arguments, because the eighth positional slot is ``clusters``
        # and the baseline used to land in it — an empty corpus reporting a
        # cluster count of 0.42.
        return Estimate(
            method="snips",
            value=0.0,
            stderr=0.0,
            n=n,
            ess=0.0,
            clipped=clipped,
            unsupported=unsupported,
            baseline=_baseline(observations),
        )

    value = sum(w * r for w, r in zip(weights, rewards)) / total
    # Variance of a ratio estimator, first-order. Good enough to tell "this is
    # a real difference" from "this is noise", which is the only question being
    # asked of it.
    # Ratio estimator, first-order: the influence term of row i is
    # w_i * (r_i - value) / (total / n), and the cluster-robust error is that
    # term's CR0 sandwich. Good enough to tell "this is a real difference" from
    # "this is noise", which is the only question being asked of it.
    scale = n / total
    influence = [w * (r - value) * scale for w, r in zip(weights, rewards)]
    return Estimate(
        method="snips",
        value=value,
        stderr=_clustered_stderr(observations, influence),
        n=n,
        clipped=clipped,
        unsupported=unsupported,
        baseline=_baseline(observations),
        **_diagnostics(observations, weights),
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
    return Estimate(
        method="dr",
        value=value,
        stderr=_clustered_stderr(observations, terms),
        n=n,
        clipped=clipped,
        unsupported=unsupported,
        baseline=_baseline(observations),
        **_diagnostics(observations, weights),
    )


# ---------------------------------------------------------------------------
# Δ-OPE — the difference, estimated directly, on the rows that carry it
# ---------------------------------------------------------------------------

#: Fewest rows on which the champion and the challenger must actually disagree
#: before their difference may be gated on.
#:
#: §8.9: Δ-OPE's variance reduction "comes from *agreement* — which is the
#: problem as well as the benefit, because on the **disagreement set**, the only
#: rows carrying information about the difference between the policies, the
#: estimator is ordinary IPS with the same weights." Two policies that agree
#: everywhere have a Δ of exactly zero with an interval of exactly zero width,
#: and that is not evidence they are equivalent.
MIN_DISAGREEMENT_ROWS = 100

#: And as a share, because a hundred disagreements out of a million is a
#: challenger that changes nothing and a hundred out of two hundred is a
#: different policy.
MIN_DISAGREEMENT_FRACTION = 0.01

#: Effective borrowers *within* the disagreement set. The same floor
#: :data:`MIN_ESS_FRACTION` applies to a whole corpus, restated here because
#: §8.9 asks for "a minimum disagreement mass **and** a minimum ESS within it"
#: and the second is the one an agreement-heavy corpus fails.
MIN_DISAGREEMENT_ESS = 10.0


@dataclass(frozen=True)
class DeltaEstimate:
    """Challenger minus champion, estimated directly (Jeunen & Ustimenko, RecSys '24).

    Estimating the *difference* rather than differencing two estimates cancels
    the variance the two policies share, which on a corpus where they mostly
    agree is nearly all of it. The catch is in the same sentence: what cancels
    is the agreement, so the entire evidential content of the number lives on
    the rows where they disagree, and there the estimator is plain IPS.

    §8.9, verbatim, because it is the failure this class is shaped to prevent:
    *"A gate that certifies on the agreement set and deploys on 100% of the book
    is an interval trap arriving through the front door."* So the interval that
    gates is :attr:`interval`, computed on the disagreement set alone, and
    :attr:`value` — the book-wide difference, which is what actually ships — is
    reported beside it rather than instead of it.
    """

    #: Mean Δ per decision across the whole evaluable corpus. What shipping the
    #: challenger would be worth, in the reward's units.
    value: float
    #: Mean Δ per decision restricted to the disagreement set. Larger in
    #: magnitude than :attr:`value` by construction, and the quantity the
    #: interval and the bound below are about.
    disagreement_value: float
    #: Cluster bootstrap on the disagreement set (W7's ``cluster.bootstrap`` —
    #: percentile at ≥40 clusters, wild-Rademacher below).
    interval: cluster.Interval
    #: The anytime-valid lower bound on :attr:`disagreement_value`. This is
    #: ``EV_lcb``, and §8.12 gate 7 promotes on it.
    lcb: sequence.Bound
    #: The one-shot Logarithmic-Smoothing bound on the challenger's own value
    #: over the same rows. Corroboration; never gates (§8.9 tier 2).
    ls: sequence.Bound
    n: int
    disagreement_n: int
    disagreement_clusters: int
    ess_customers: float
    max_customer_share: float
    clipped: int
    #: The direct-method and importance-weighted halves of the difference, so a
    #: validator can see how much of it is model and how much is data. Both zero
    #: when no reward model was supplied, and ``dm_share`` says so.
    dm: float = 0.0
    ips: float = 0.0
    has_reward_model: bool = False

    @property
    def disagreement_fraction(self) -> float:
        return self.disagreement_n / self.n if self.n else 0.0

    @property
    def objections(self) -> list[str]:
        """Why this difference may not be gated on. Empty means it may."""
        out: list[str] = []
        if self.n <= 0:
            return ["no evaluable observations"]
        if self.disagreement_n < MIN_DISAGREEMENT_ROWS:
            out.append(
                f"the policies disagree on {self.disagreement_n} of {self.n} decisions, "
                f"below the {MIN_DISAGREEMENT_ROWS}-row minimum disagreement mass — "
                "agreement is what Δ-OPE cancels, so it carries no information "
                "about the difference (§8.9)"
            )
        if self.disagreement_fraction < MIN_DISAGREEMENT_FRACTION:
            out.append(
                f"the disagreement rate is {self.disagreement_fraction:.2%}, below "
                f"{MIN_DISAGREEMENT_FRACTION:.0%} — this challenger changes almost nothing"
            )
        if self.disagreement_clusters < cluster.MIN_CLUSTERS:
            out.append(
                f"{self.disagreement_clusters} borrowers in the disagreement set against "
                f"the {cluster.MIN_CLUSTERS} the cluster bootstrap needs (§8.12 gate 8)"
            )
        if self.ess_customers < MIN_DISAGREEMENT_ESS:
            out.append(
                f"effective sample size within the disagreement set is "
                f"{self.ess_customers:.2f} borrowers, below {MIN_DISAGREEMENT_ESS:.0f} (§8.9)"
            )
        if self.max_customer_share > MAX_CUSTOMER_LEVERAGE:
            out.append(
                f"one borrower carries {self.max_customer_share:.1%} of the disagreement "
                f"set's weight, above the {MAX_CUSTOMER_LEVERAGE:.0%} cap (§8.3)"
            )
        if self.lcb.refusal:
            out.append(f"the confidence sequence could not be computed: {self.lcb.refusal}")
        return out

    @property
    def evaluable(self) -> bool:
        return not self.objections

    def to_log(self) -> dict[str, Any]:
        return {
            "method": "delta_ope",
            "value": round(self.value, 6),
            "disagreementValue": round(self.disagreement_value, 6),
            "interval": self.interval.as_dict(),
            "lcb": self.lcb.as_dict(),
            "logarithmicSmoothing": self.ls.as_dict(),
            "n": self.n,
            "disagreementN": self.disagreement_n,
            "disagreementFraction": round(self.disagreement_fraction, 4),
            "disagreementClusters": self.disagreement_clusters,
            "essCustomers": round(self.ess_customers, 2),
            "maxCustomerShare": round(self.max_customer_share, 4),
            "clipped": self.clipped,
            "dm": round(self.dm, 6),
            "ips": round(self.ips, 6),
            "hasRewardModel": self.has_reward_model,
            "evaluable": self.evaluable,
            "objections": self.objections,
        }


def _mass(distribution: Mapping[str, float], action: str) -> float:
    return float(distribution.get(action, 0.0))


def _disagree(champion: Mapping[str, float], challenger: Mapping[str, float]) -> bool:
    """Whether the two policies put mass anywhere differently.

    Compared over the union of both supports, so a challenger that merely adds a
    second action at low probability counts as disagreeing — it is a different
    policy and the rows where it acts differently are the ones that say by how
    much.
    """
    return any(
        abs(_mass(champion, a) - _mass(challenger, a)) > 1e-12
        for a in set(champion) | set(challenger)
    )


def delta(
    observations: Sequence[Observation],
    champion: Policy,
    challenger: Policy,
    *,
    reward_model: RewardModel | None = None,
    alpha: float = sequence.DEFAULT_ALPHA,
    reward_range: tuple[float, float] = (0.0, 1.0),
) -> DeltaEstimate:
    """Δ-OPE: what the challenger is worth over the champion, and on what evidence.

    ``reward_range`` is the declared range of the logged reward — ``(0, 1)`` for
    the cure indicator :func:`scan` produces. It is what bounds the per-row Δ
    term and therefore what the confidence sequence is entitled to assume, so it
    is a parameter rather than a measurement (see :mod:`agent_core.treatment.sequence`).
    """
    n = len(observations)
    r_lo, r_hi = reward_range
    span = max(abs(r_lo), abs(r_hi))

    terms: list[float] = []
    rows: list[dict[str, Any]] = []
    dis_obs: list[Observation] = []
    dis_terms: list[float] = []
    dis_leverage: list[float] = []
    dis_weights: list[float] = []
    dis_rewards: list[float] = []
    dm_total = 0.0
    ips_total = 0.0
    clipped = 0

    for obs in observations:
        p_log = float(obs.propensity)
        target = challenger(obs.candidates)
        base = champion(obs.candidates)
        if p_log <= 0:
            terms.append(0.0)
            continue
        weight = (_mass(target, obs.action) - _mass(base, obs.action)) / p_log
        if abs(weight) > MAX_WEIGHT:
            weight = math.copysign(MAX_WEIGHT, weight)
            clipped += 1
        term = weight * obs.reward
        terms.append(term)

        if not _disagree(base, target):
            continue
        dis_obs.append(obs)
        dis_terms.append(term)
        # The importance weight of the *difference*, which is what the ESS and
        # the leverage share are about. Using the weighted reward instead would
        # make every zero-reward row weightless and report the effective sample
        # size of the positives rather than of the corpus.
        dis_leverage.append(abs(weight))
        rows.append({"customer_id": obs.customer_id or obs.decision_id, "term": term})
        # The challenger's own weight, for the LS bound, which is stated for
        # non-negative weights and cannot take the signed difference.
        w_target = min(MAX_WEIGHT, _mass(target, obs.action) / p_log)
        dis_weights.append(w_target)
        dis_rewards.append(obs.reward)
        if reward_model is not None:
            modelled_target = sum(
                prob * reward_model(obs.candidates, action)
                for action, prob in target.items()
                if prob > 0
            )
            modelled_base = sum(
                prob * reward_model(obs.candidates, action)
                for action, prob in base.items()
                if prob > 0
            )
            taken = reward_model(obs.candidates, obs.action)
            dm_total += modelled_target - modelled_base
            ips_total += weight * (obs.reward - taken)

    dis_n = len(dis_terms)
    per_customer = _by_customer(dis_obs, dis_leverage)
    total_weight = sum(per_customer.values())

    # One value per borrower — the mean of that borrower's Δ terms — because the
    # borrower is the unit (§8.7) and the confidence sequence bounds a mean of
    # independent observations.
    by_customer_terms: dict[str, list[float]] = {}
    for obs, term in zip(dis_obs, dis_terms):
        by_customer_terms.setdefault(obs.customer_id or obs.decision_id, []).append(term)
    borrower_values = [sum(v) / len(v) for v in by_customer_terms.values()]

    interval = cluster.bootstrap(
        rows,
        lambda sample: (
            sum(float(r["term"]) for r in sample) / len(sample) if sample else 0.0
        ),
        cluster_key="customer_id",
    )
    lcb = sequence.lower_bound(
        borrower_values,
        lo=-MAX_WEIGHT * span,
        hi=MAX_WEIGHT * span,
        alpha=alpha,
    )
    ls = sequence.logarithmic_smoothing(dis_weights, dis_rewards, alpha=alpha)

    denominator = dis_n or 1
    return DeltaEstimate(
        value=(sum(terms) / n) if n else 0.0,
        disagreement_value=sum(dis_terms) / denominator,
        interval=interval,
        lcb=lcb,
        ls=ls,
        n=n,
        disagreement_n=dis_n,
        disagreement_clusters=len(by_customer_terms),
        ess_customers=_ess(list(per_customer.values())),
        max_customer_share=(
            (max(per_customer.values()) / total_weight) if total_weight > 0 else 0.0
        ),
        clipped=clipped,
        dm=dm_total / denominator,
        ips=ips_total / denominator,
        has_reward_model=reward_model is not None,
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
        # §8.9's fourth repair: "score the challenger that would actually ship,
        # because today the evaluation drops VALUE_HORIZON and both clamps".
        # ``value_at_stake`` is what ``scoring.rupees_given_cure`` wrote at
        # decision time -- capped_exposure x recovery_fraction x
        # VALUE_HORIZON[action] -- so reading it back is the only way to score
        # the same rupees the engine scored. Re-deriving the product here is how
        # the horizon and the mandate ceiling went missing in the first place.
        rupees = components.get("value_at_stake")
        if rupees is None:
            # Pre-W10a rows, which logged exposure and not the value. The
            # horizon is unrecoverable for them, so the fallback is stated
            # rather than silently applied at 1.0.
            rupees = float(components.get("exposure") or 0.0) * recovery_fraction
        return scoring.expected_value(
            p_reach=scoring.clamp(p_reach),
            p_resolve=scoring.clamp(tau),
            rupees=float(rupees),
            decay=scoring.clamp(decay),
            cost=float(entry.get("cost") or 0.0),
            fatigue=-float(components.get("fatigue") or 0.0),
        )

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

#: The columns the equivalence class is defined over, in the order §8.9 names
#: them: "filter on the support-equivalence class, ``recommender_version``,
#: ``feature_schema_version``, ``label_definition_version`` **and
#: ``lambda_bucket``** — λ is re-solved daily and enters the served score, so it
#: changes the argmax and therefore the logging policy, leaving the corpus an
#: undocumented mixture over dual prices."
#:
#: Deliberately *not* ``policy_binding_hash``. §8.9: a binding hash changes on
#: every publication, and filtering on it partitions the corpus into slivers, so
#: a mid-window rule publication destroys the promotion evidence. Two rule sets
#: are equivalent for an action when they induce the same support for it, and
#: the support set is logged per row — which is the filter that survives.
CLASS_COLUMNS = (
    "recommender_version",
    "feature_schema_version",
    "label_definition_version",
    "lambda_bucket",
)


@dataclass(frozen=True)
class CorpusScope:
    """What was read, what was dropped, and why — with a count against each.

    §8.12 makes an unevaluable gate a refusal. An empty observation list is the
    most unevaluable a gate can be, and until this existed it was indistinguishable
    from a corpus that simply had nothing in it. "0 of 278 rows are on logging
    contract 2" is the sentence an operator needs; "no evaluable decisions" sent
    them to lower ``TREATMENT_GREEDINESS`` on a corpus where exploration was
    already running at δ = 0.10.
    """

    considered: int
    #: reason → rows dropped for it. Ordered by the order they were applied.
    excluded: dict[str, int] = field(default_factory=dict)
    #: Suppressed rows that made it in. §8.9's first repair, as a number.
    suppressed_included: int = 0
    #: Rows whose rupees came from ``exposure`` because they predate
    #: ``value_at_stake``. The horizon is unrecoverable for these.
    pre_value_rows: int = 0
    evaluable: int = 0

    def to_log(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "evaluable": self.evaluable,
            "excluded": dict(self.excluded),
            "suppressedIncluded": self.suppressed_included,
            "preValueRows": self.pre_value_rows,
        }

    @property
    def objections(self) -> list[str]:
        """Why this corpus cannot be evaluated, if it cannot. Empty means it can."""
        if self.evaluable > 0:
            return []
        if not self.considered:
            return ["the corpus holds no decisions in the requested modes at all"]
        biggest = sorted(self.excluded.items(), key=lambda kv: -kv[1])
        detail = "; ".join(f"{count} {reason}" for reason, count in biggest if count)
        return [
            f"0 of {self.considered} decisions are evaluable — {detail}"
            if detail
            else f"0 of {self.considered} decisions are evaluable"
        ]


@dataclass(frozen=True)
class Corpus:
    """Observations and the account of how they were arrived at, together."""

    observations: list[Observation]
    scope: CorpusScope


def scan(
    conn: Any,
    *,
    modes: Sequence[str] = ("shadow", "live"),
    variant: str | None = None,
    exclude_variants: Sequence[str] = ("null_treatment", "holdout"),
    limit: int | None = None,
    contract_min: int = MIN_LOGGING_CONTRACT,
    equivalence_class: Mapping[str, str] | None = None,
    include_suppressed: bool = True,
) -> Corpus:
    """Read the corpus into evaluable observations, and account for the rest.

    Untreated arms are excluded by default. They are not a different ranking of
    the same actions — they are the absence of one — so importance-weighting
    them against a policy that acts would be comparing a policy with a
    condition. Their job is the difference of means in :func:`treatment_effect`.

    ``contract_min`` is the logging contract floor. It defaults to
    :data:`MIN_LOGGING_CONTRACT` because that is what the schema has said since
    W2; pass 1 to see what the older rows would have said, and read the answer
    as a diagnostic rather than as evidence.

    ``equivalence_class`` pins any of :data:`CLASS_COLUMNS` to one value. Pinning
    none pools every class, which is what happened before this argument existed
    and is legitimate only when the corpus holds one of each.

    ``include_suppressed`` keeps the rows where the veto stack chose ``wait``.
    They are the negative class, they carry a logged propensity, and dropping
    them scored every policy against the population the engine had already
    decided to act on.

    ponytail: the class filter runs in Python rather than SQL so each exclusion
    can be counted by reason. At 278 rows that is free; past a few hundred
    thousand, push the pinned columns into the WHERE clause and keep the counts
    from a GROUP BY.
    """
    from sqlalchemy import text
    from agent_core.treatment import schema_ready

    clauses = ["mode = ANY(:modes)", "outcome IS NOT NULL", "propensity IS NOT NULL"]
    params: dict[str, Any] = {"modes": list(modes)}
    if variant:
        clauses.append("variant = :variant")
        params["variant"] = variant
    elif exclude_variants:
        clauses.append("(variant IS NULL OR variant <> ALL(:excluded))")
        params["excluded"] = list(exclude_variants)

    columns = [
        "id", "customer_id", "chosen_action", "outcome", "propensity",
        "variant", "candidates", "suppression_reason",
    ]
    # Every column below arrived in a later wave, and this reads databases that
    # do not carry them — the abort cascade W8a shipped was exactly a read of a
    # not-yet-migrated table on a lent connection.
    optional = [
        c
        for c in ("logging_contract_version", "action_propensity", *CLASS_COLUMNS)
        if schema_ready.has_column(conn, "treatment_decisions", c)
    ]

    sql = f"""
        SELECT {', '.join(columns + optional)}
        FROM treatment_decisions
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at ASC
    """
    if limit:
        sql += " LIMIT :limit"
        params["limit"] = int(limit)

    rows = conn.execute(text(sql), params).mappings().all()

    pinned = {k: v for k, v in (equivalence_class or {}).items() if v is not None}
    unknown = sorted(set(pinned) - set(CLASS_COLUMNS))
    if unknown:
        raise ValueError(f"not equivalence-class columns: {unknown}")

    excluded: dict[str, int] = {}

    def _drop(reason: str) -> None:
        excluded[reason] = excluded.get(reason, 0) + 1

    out: list[Observation] = []
    suppressed_in = 0
    for row in rows:
        contract = int(row.get("logging_contract_version") or 1)
        if contract < contract_min:
            _drop(f"on logging contract {contract}, below the contract-{contract_min} floor")
            continue

        mismatched = [c for c, want in pinned.items() if str(row.get(c) or "") != want]
        if mismatched:
            _drop(f"outside the pinned equivalence class on {', '.join(sorted(mismatched))}")
            continue

        entries = row["candidates"]
        by_action = (
            {
                str(e.get("action")): e
                for e in entries
                if isinstance(e, Mapping) and e.get("action")
            }
            if isinstance(entries, list)
            else {}
        )
        support = {
            action: float(entry["propensity"])
            for action, entry in by_action.items()
            if entry.get("propensity") is not None
        }
        chosen = str(row["chosen_action"] or "")
        suppressed = bool(row.get("suppression_reason"))

        # Within-arm propensity. The top-level ``propensity`` column carries the
        # arm factor too, and using it here would weight every row by the
        # inverse of its arm share — a correction for a comparison nobody is
        # making. ``action_propensity`` is the same quantity split out at write
        # time, which is what W2 delivered it for.
        p_log = support.get(chosen)
        if p_log is None and suppressed:
            # §8.9's first repair. The veto stack chose `wait`, the candidate
            # list does not price it, and the row still carries the probability
            # with which that happened. Its support is that one action: nothing
            # else was reachable, which is a structural zero rather than a gap
            # in the log (§8.3).
            p_log = row.get("action_propensity")
            if p_log is None and contract_min <= 1:
                p_log = row.get("propensity")
            if p_log is not None and float(p_log) > 0:
                support = {chosen: float(p_log)}
                suppressed_in += 1
        if p_log is None or float(p_log) <= 0:
            _drop(
                "carries no within-arm propensity for the action it took"
                if not suppressed
                else "is suppressed and carries no recoverable propensity"
            )
            continue
        if not include_suppressed and suppressed:
            _drop("is a suppressed decision and suppressed rows were excluded")
            continue

        out.append(
            Observation(
                decision_id=str(row["id"]),
                action=chosen,
                reward=1.0 if str(row["outcome"]) in CURED else 0.0,
                propensity=float(p_log),
                support=support,
                candidates=by_action,
                variant=row["variant"],
                customer_id=str(row["customer_id"]),
            )
        )

    pre_value = sum(
        1
        for o in out
        if not any(
            isinstance(e, Mapping) and (e.get("components") or {}).get("value_at_stake")
            is not None
            for e in o.candidates.values()
        )
    )
    return Corpus(
        observations=out,
        scope=CorpusScope(
            considered=len(rows),
            excluded=excluded,
            suppressed_included=suppressed_in,
            pre_value_rows=pre_value,
            evaluable=len(out),
        ),
    )


def observations(conn: Any, **kwargs: Any) -> list[Observation]:
    """:func:`scan`, for a caller that wants the rows and not the account."""
    return scan(conn, **kwargs).observations


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
