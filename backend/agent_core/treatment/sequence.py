"""Anytime-valid lower bounds — §8.9's Tier 3, and the Tier 2 that corroborates it.

The gate promotes on a *lower bound*, never on a point estimate, and the choice
of bound is not a taste question. A challenger is re-evaluated every time it is
retrained, which at a weekly cadence is thirteen looks a quarter. A fixed-sample
concentration bound is valid at **one** look chosen in advance; evaluated at
thirteen it is thirteen chances to cross, and the first crossing is the one that
gets shipped. That is the whole reason §8.9 makes the confidence *sequence* the
instrument that gates:

    "the CS is the object that licenses continuous monitoring and optional
    stopping. If a validator insists the LS bound must gate, alpha is spent
    across looks explicitly and the spending schedule is recorded in the
    pre-registration."

So :func:`lower_bound` may be read after every new borrower, forever, and its
coverage guarantee holds *uniformly over time* — that is what "anytime-valid"
buys, and it is the only property that makes a weekly retrain cadence honest.
:func:`logarithmic_smoothing` is the one-shot corroboration, reported at the
same instant and never gating on its own.

**The construction.** Predictable-mixture empirical-Bernstein (Waudby-Smith &
Ramdas, *Estimating means of bounded random variables by betting*, JRSS-B 2024;
arXiv:2010.09686). Empirical-Bernstein rather than Hoeffding because the
quantity bounded here is a mean of importance-weighted rewards whose variance is
far below its range: a corpus where champion and challenger mostly agree
contributes near-zero terms, and a Hoeffding bound pays the full range for every
one of them. On a corpus of mostly-agreeing rows that is the difference between
a usable bound and a bound that refuses everything.

**The unit is the borrower.** §8.7: arm membership is randomised per customer,
so fourteen decisions on one borrower are one observation, not fourteen. Every
function here takes values already aggregated to the customer — aggregating is
the caller's job, because only the caller knows which weights belong together,
and doing it here would hide the cluster count from the number beside it.

**The range is declared, not measured.** A concentration bound for bounded
variables needs the bounds *before* it sees the data; deriving ``[lo, hi]`` from
the sample would make the guarantee circular. So the caller states the range —
for a clipped importance-weighted reward it is a known constant,
``MAX_WEIGHT × reward_range`` — and a value outside it is a refusal rather than
a clamp, because a clamp would silently restore the guarantee by discarding the
observation that broke it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

#: The largest bet the empirical-Bernstein martingale is allowed to place.
#:
#: :func:`psi_e` diverges as λ → 1, so λ must stay strictly below it. Three
#: quarters is the value the original paper uses, and it bounds the *bet* rather
#: than the estimate: capping it costs a little tightness on a very short
#: sequence and buys a finite ψ at every step.
MAX_BET = 0.75

#: One-sided by default. The gate asks whether the challenger is better, which
#: is one question and one tail; spending α on an upper bound would widen the
#: lower one for a number nobody reads.
DEFAULT_ALPHA = 0.05

METHOD_CS = "empirical_bernstein_cs"
METHOD_LS = "logarithmic_smoothing"


@dataclass(frozen=True)
class Bound:
    """A lower bound, and everything needed to know whether to believe it."""

    #: The bound itself, in the units of the values passed in. ``-inf`` when the
    #: sequence carries too little information to say anything at all — a
    #: refusal, not a very negative number.
    lower: float
    #: The sample mean, so a reader can see what the bound cost.
    mean: float
    #: Observations — borrowers, not decisions.
    n: int
    alpha: float
    method: str
    #: Non-empty when the bound could not be computed, and then ``lower`` is
    #: ``-inf``. §8.12 makes an unevaluable gate a refusal, so the reason travels
    #: with the number rather than being logged somewhere else.
    refusal: str = ""

    @property
    def clears_zero(self) -> bool:
        return math.isfinite(self.lower) and self.lower > 0.0

    def clears(self, margin: float) -> bool:
        """Whether the bound clears a pre-registered margin (§8.12 gate 7)."""
        return math.isfinite(self.lower) and self.lower > margin

    def as_dict(self) -> dict[str, object]:
        return {
            "lower": None if not math.isfinite(self.lower) else round(self.lower, 6),
            "mean": round(self.mean, 6),
            "n": self.n,
            "alpha": self.alpha,
            "method": self.method,
            "clearsZero": self.clears_zero,
            "refusal": self.refusal,
        }


def psi_e(bet: float) -> float:
    """The empirical-Bernstein exponent, ``(-log(1-λ) - λ) / 4``.

    Undefined at λ = 1 and negative below 0, which is what :data:`MAX_BET` is
    for.
    """
    if not 0.0 <= bet < 1.0:
        raise ValueError(f"bet {bet} outside [0, 1)")
    return (-math.log1p(-bet) - bet) / 4.0


def _refused(
    reason: str, *, n: int, alpha: float, mean: float = 0.0, method: str = METHOD_CS
) -> Bound:
    return Bound(
        lower=float("-inf"), mean=mean, n=n, alpha=alpha, method=method, refusal=reason
    )


def lower_bound(
    values: Sequence[float],
    *,
    lo: float,
    hi: float,
    alpha: float = DEFAULT_ALPHA,
) -> Bound:
    """The anytime-valid lower bound on the mean of ``values``.

    ``values`` are already one per borrower. ``[lo, hi]`` is the declared range
    they live in — stated in advance, never read off the sample.

    The sequence is order-dependent by construction: each bet λ_i is chosen from
    the first ``i-1`` observations only, which is what makes the product a
    martingale. A caller wanting a reproducible number sorts its input; a caller
    wanting the tightest one feeds it in the order it arrived. Neither is more
    valid, and the difference is small on any sequence long enough to gate with.
    """
    n = len(values)
    if n == 0:
        return _refused("no observations", n=0, alpha=alpha)
    if not 0.0 < alpha < 1.0:
        return _refused(f"alpha {alpha} outside (0, 1)", n=n, alpha=alpha)
    if not (hi > lo) or not math.isfinite(hi - lo):
        return _refused(f"declared range [{lo}, {hi}] is empty", n=n, alpha=alpha)
    if not all(math.isfinite(v) for v in values):
        return _refused("a value is not finite", n=n, alpha=alpha)

    mean = sum(values) / n
    outside = [v for v in values if v < lo or v > hi]
    if outside:
        # Not clamped. A bound whose declared range the data escaped is not a
        # bound, and quietly pulling the offender back inside would restore the
        # guarantee by deleting the evidence against it.
        return _refused(
            f"{len(outside)} of {n} values fall outside the declared range "
            f"[{lo}, {hi}] — that range is the bound's own assumption, so this "
            "is a refusal rather than a clamp",
            n=n,
            alpha=alpha,
            mean=mean,
        )

    span = hi - lo
    log_inv_alpha = math.log(1.0 / alpha)

    # Predictable running mean and variance, each using only what came before.
    # The 1/2 and 1/4 are the paper's priors; without them the first bet divides
    # by a zero variance.
    running_sum = 0.5
    running_sq = 0.25
    seen = 0
    numerator = 0.0
    denominator = 0.0

    for raw in values:
        value = (raw - lo) / span
        mu_prev = running_sum / (1 + seen)
        sigma_prev = running_sq / (1 + seen)
        step = seen + 1
        # The predictable mixture. The denominator grows as i·log(1+i) rather
        # than with a declared horizon n, which is exactly what lets the bound
        # be read at every look instead of at one chosen in advance.
        scale = sigma_prev * step * math.log1p(step)
        bet = min(MAX_BET, math.sqrt(2.0 * log_inv_alpha / scale)) if scale > 0 else MAX_BET

        numerator += bet * value - 4.0 * (value - mu_prev) ** 2 * psi_e(bet)
        denominator += bet

        running_sum += value
        seen += 1
        running_sq += (value - running_sum / (1 + seen)) ** 2

    if denominator <= 0:  # pragma: no cover - MAX_BET is positive
        return _refused("every bet was zero", n=n, alpha=alpha, mean=mean)

    return Bound(
        lower=lo + span * ((numerator - log_inv_alpha) / denominator),
        mean=mean,
        n=n,
        alpha=alpha,
        method=METHOD_CS,
    )


def logarithmic_smoothing(
    weights: Sequence[float],
    rewards: Sequence[float],
    *,
    bet: float = 1.0,
    alpha: float = DEFAULT_ALPHA,
) -> Bound:
    """The Tier 2 one-shot pessimistic bound (arXiv:2405.14335).

    ``(1/nλ) Σ log(1 + λ·w_i·r_i) − log(1/α)/(nλ)`` — a lower bound on the
    target policy's value holding with probability 1−α **at a single look**, for
    non-negative weights and rewards.

    Reported beside the confidence sequence and never instead of it. Its job is
    corroboration: two bounds built on different principles agreeing is worth
    something to a validator, and the CS clearing while this one does not is a
    fact worth seeing rather than one worth hiding. Reading it at thirteen looks
    a quarter is exactly the misuse §8.9 describes, so nothing here lets it gate.
    """
    n = len(weights)
    if n == 0:
        return _refused("no observations", n=0, alpha=alpha, method=METHOD_LS)
    if n != len(rewards):
        return _refused(
            "weights and rewards differ in length", n=n, alpha=alpha, method=METHOD_LS
        )
    if bet <= 0 or not math.isfinite(bet):
        return _refused(f"bet {bet} must be positive", n=n, alpha=alpha, method=METHOD_LS)
    bad = sum(
        1
        for w, r in zip(weights, rewards)
        if not (math.isfinite(w) and math.isfinite(r)) or w < 0 or r < 0
    )
    if bad:
        return _refused(
            f"{bad} of {n} rows carry a negative or non-finite weight or reward — "
            "the bound is stated for non-negative rewards",
            n=n,
            alpha=alpha,
            method=METHOD_LS,
        )

    mean = sum(w * r for w, r in zip(weights, rewards)) / n
    estimate = sum(math.log1p(bet * w * r) for w, r in zip(weights, rewards)) / (n * bet)
    return Bound(
        lower=estimate - math.log(1.0 / alpha) / (n * bet),
        mean=mean,
        n=n,
        alpha=alpha,
        method=METHOD_LS,
    )
