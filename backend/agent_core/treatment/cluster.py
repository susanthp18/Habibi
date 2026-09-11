"""W7 · cluster-robust variance, and the design effect as a measurement.

Every standard error this system published before this module treated decisions
as independent observations. They are not: ``config.assign_variant`` hashes the
*customer*, so one borrower's fortnight of daily sweeps is fourteen draws of the
same coin. §8.7 requires a **cluster bootstrap on the customer**, and §8.8 adds
the constraint that makes it honest:

    Below ~40 clusters per arm the percentile bootstrap is not trustworthy, so
    the gate falls back to a wild cluster bootstrap with Rademacher weights and
    t(G-1) critical values, stated on the artifact.

Both are here. Which one ran is on every interval, with the cluster count, so a
reader can never see a number without seeing what it was computed from.

No new dependency: the resampling is `random.Random` over a per-customer index
and the normal quantiles come from `statistics.NormalDist`, which is what
``scripts/power_control_arm.py`` already uses.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, asdict
from statistics import NormalDist
from typing import Any, Callable, Mapping, Sequence

#: §8.8. Below this many clusters in an arm the percentile bootstrap's coverage
#: is not what it claims, and the wild bootstrap is used instead.
MIN_CLUSTERS = 40

#: §8.7. Two thousand replications, stated in the design rather than chosen here.
REPLICATIONS = 2000

#: Fixed so a published interval is reproducible from the same panel.
SEED = 20260907

METHOD_PERCENTILE = "cluster_percentile_bootstrap"
METHOD_WILD = "wild_cluster_bootstrap_rademacher"


@dataclass(frozen=True)
class Interval:
    """A point estimate that cannot be read without its cluster count."""

    value: float
    low: float
    high: float
    clusters: int
    observations: int
    method: str
    replications: int

    @property
    def excludes_zero(self) -> bool:
        return self.low > 0.0 or self.high < 0.0

    def as_dict(self) -> dict[str, Any]:
        out = {k: v for k, v in asdict(self).items()}
        out["value"] = round(self.value, 6)
        out["low"] = round(self.low, 6)
        out["high"] = round(self.high, 6)
        out["excludesZero"] = self.excludes_zero
        return out


def _by_cluster(
    rows: Sequence[Mapping[str, Any]], *, cluster_key: str
) -> list[list[Mapping[str, Any]]]:
    groups: dict[Any, list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row.get(cluster_key), []).append(row)
    return list(groups.values())


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def bootstrap(
    rows: Sequence[Mapping[str, Any]],
    statistic: Callable[[Sequence[Mapping[str, Any]]], float],
    *,
    cluster_key: str = "customer_id",
    alpha: float = 0.05,
    replications: int = REPLICATIONS,
    seed: int = SEED,
) -> Interval:
    """Resample **clusters** with replacement, not rows.

    ``statistic`` is applied to the resampled row set. Resampling clusters is the
    whole point: it is what stops fourteen decisions on one borrower counting as
    fourteen independent pieces of evidence about that borrower.
    """
    clusters = _by_cluster(rows, cluster_key=cluster_key)
    g = len(clusters)
    point = statistic(rows)
    if g < 2:
        # One cluster carries no between-cluster variation, so the only honest
        # interval is undefined. Return the point with a degenerate band rather
        # than a narrow one that would read as precision.
        return Interval(
            value=point,
            low=float("-inf"),
            high=float("inf"),
            clusters=g,
            observations=len(rows),
            method=METHOD_PERCENTILE if g >= MIN_CLUSTERS else METHOD_WILD,
            replications=0,
        )

    if g >= MIN_CLUSTERS:
        rng = random.Random(seed)
        draws: list[float] = []
        for _ in range(replications):
            sample: list[Mapping[str, Any]] = []
            for _ in range(g):
                sample.extend(clusters[rng.randrange(g)])
            draws.append(statistic(sample))
        draws.sort()
        lo = draws[int((alpha / 2.0) * (len(draws) - 1))]
        hi = draws[int((1.0 - alpha / 2.0) * (len(draws) - 1))]
        return Interval(
            value=point,
            low=lo,
            high=hi,
            clusters=g,
            observations=len(rows),
            method=METHOD_PERCENTILE,
            replications=replications,
        )

    # Wild cluster bootstrap. Each cluster's contribution is flipped by a
    # Rademacher weight (+1/-1 with equal probability), which preserves the
    # within-cluster correlation structure while resampling the sign of the
    # cluster's deviation from the overall statistic. The critical value is
    # t(G-1), not the normal quantile, because with few clusters the difference
    # is exactly the coverage the percentile bootstrap fails to deliver.
    rng = random.Random(seed)
    cluster_means = [statistic(c) for c in clusters]
    deviations = [m - point for m in cluster_means]
    draws = []
    for _ in range(replications):
        flipped = [d * (1.0 if rng.random() < 0.5 else -1.0) for d in deviations]
        draws.append(_mean(flipped))
    spread = _mean([d * d for d in draws]) ** 0.5
    crit = _t_critical(g - 1, alpha)
    return Interval(
        value=point,
        low=point - crit * spread,
        high=point + crit * spread,
        clusters=g,
        observations=len(rows),
        method=METHOD_WILD,
        replications=replications,
    )


#: Two-sided t critical values at alpha=0.05 for the small degrees of freedom the
#: wild bootstrap actually runs at. A table rather than a special-function
#: implementation: below 40 clusters the df are small and enumerable, and above
#: it the percentile bootstrap runs instead so this is never consulted.
_T95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056,
    27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042, 31: 2.040, 32: 2.037,
    33: 2.035, 34: 2.032, 35: 2.030, 36: 2.028, 37: 2.026, 38: 2.024,
    39: 2.023,
}


def _t_critical(df: int, alpha: float) -> float:
    if alpha != 0.05:
        # Only the 95% band is tabulated; anything else falls back to the normal
        # quantile, which is anti-conservative at small df and says so here.
        return NormalDist().inv_cdf(1.0 - alpha / 2.0)
    return _T95.get(max(1, df), NormalDist().inv_cdf(0.975))


def icc(
    rows: Sequence[Mapping[str, Any]],
    *,
    value_key: str,
    cluster_key: str = "customer_id",
) -> float:
    """One-way random-effects intraclass correlation, measured from the panel.

    ``ICC = s_between / (s_between + s_within)``. This is the second input to the
    design effect and §8.7 forbids assuming it: its plausible range spans 1.0 to
    12.8 on the design effect, which is a factor of three on the minimum
    detectable effect in an unknown direction.
    """
    clusters = [
        [float(r.get(value_key) or 0.0) for r in group]
        for group in _by_cluster(rows, cluster_key=cluster_key)
    ]
    clusters = [c for c in clusters if c]
    n_total = sum(len(c) for c in clusters)
    g = len(clusters)
    if g < 2 or n_total <= g:
        return 0.0
    grand = sum(sum(c) for c in clusters) / n_total
    ms_between = sum(len(c) * (_mean(c) - grand) ** 2 for c in clusters) / (g - 1)
    ms_within = sum(
        sum((v - _mean(c)) ** 2 for v in c) for c in clusters
    ) / (n_total - g)
    # Average cluster size, corrected for unequal sizes -- the standard n0.
    n0 = (
        n_total - sum(len(c) ** 2 for c in clusters) / n_total
    ) / (g - 1)
    if n0 <= 0:
        return 0.0
    var_between = (ms_between - ms_within) / n0
    denom = var_between + ms_within
    if denom <= 0:
        return 0.0
    return max(0.0, min(1.0, var_between / denom))


def design_effect(cases_per_customer: float, intraclass: float) -> float:
    """``1 + (m - 1) * ICC`` — §8.7, and the one place it is written.

    ``scripts/power_control_arm.py`` applies the same formula to size a control
    arm; this is what the serving and evaluation path reads, which §8.7 records
    as the thing nothing did before.
    """
    return max(1.0, 1.0 + (max(1.0, cases_per_customer) - 1.0) * max(0.0, intraclass))


#: §8.10 rung 3's multiplicity control. 0.10 rather than 0.05 because this is a
#: false *discovery* rate over an exploratory partition, not a family-wise error
#: rate over a confirmatory one: the cost of wrongly promoting a segment is a
#: model that shrinks back toward the pool, and the cost of wrongly rejecting one
#: is never finding heterogeneity that is there. Benjamini & Hochberg's own
#: worked examples use 0.10 for exactly this shape of screen.
DEFAULT_FDR = 0.10


def bh_reject(pvalues: Sequence[float], *, fdr: float = DEFAULT_FDR) -> list[bool]:
    """Benjamini-Hochberg step-up. One boolean per input, in input order.

    Replaces the Bonferroni correction the granularity ladder used to apply.
    Bonferroni controls the probability of **any** false positive across the
    family; with thirty candidate strata that means each one is tested at
    0.05/30 = 0.0017, which on a corpus of this size means nothing is ever found
    — and §8.10's ladder is built to climb *down* to homogeneity, not to be
    unable to climb at all. BH instead controls the expected *share* of the
    promotions that are false, which is the quantity a validator asking "how
    many of these six segments are real?" is actually asking about.

    The procedure: sort ascending, find the largest rank ``i`` where
    ``p_(i) <= i/m * fdr``, and reject every hypothesis at or below it —
    including ones whose own p-value exceeds their own critical value, which is
    the step-up part and the part that gets reimplemented wrongly.

    Ties are handled by rank rather than by value, which is conservative in the
    direction that matters: two identical p-values straddling the cutoff are
    both rejected, because the larger rank is the one that sets the threshold.
    """
    m = len(pvalues)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvalues[i])
    cutoff_rank = 0
    for rank, idx in enumerate(order, start=1):
        if pvalues[idx] <= (rank / m) * fdr:
            cutoff_rank = rank
    rejected = [False] * m
    for rank, idx in enumerate(order, start=1):
        if rank <= cutoff_rank:
            rejected[idx] = True
    return rejected


def bh_critical(rank: int, tested: int, *, fdr: float = DEFAULT_FDR) -> float:
    """The threshold BH assigns to one rank, for the report.

    Published per cell so a refusal is readable: "this segment's p was 0.031
    against a critical value of 0.017 at rank 5 of 30" is a finding somebody can
    check. A refusal that says only "rejected" is a refusal nobody can audit.
    """
    if tested <= 0:
        return 0.0
    return (max(1, rank) / tested) * fdr
