"""One prior hierarchy, with `k` measured rather than chosen — §8.10, W12.

The granularity ladder blends a fine estimate toward a coarse one with
``weight(n) = n / (n + k)``. `k` decides where that blend sits: at `k`
observations the segment and the pool count equally, below it the pool wins,
above it the segment does. It is the single most consequential number in the
ladder and today it is **750**, selected on `simulate_treatment_corpus.py` —
whose reported n is roughly thirty times its own information content, because
its book never changes state and one borrower contributes N near-identical rows
with independent labels. §15.3 is explicit that no number measured on that
simulator may select a hyperparameter again.

§8.10 says what to do instead: *"`k` is estimated per level as
σ²_within / σ²_between from the panel, with a named estimator and a CI,
refreshed monthly."*

**That is the intraclass correlation, rearranged.** `cluster.icc` already
measures `ICC = σ²_between / (σ²_between + σ²_within)` from the panel — it was
built in W7 for the design effect, it is the one-way random-effects estimator
with the unequal-cluster-size correction, and it is tested. Rearranging:

    k = σ²_within / σ²_between = (1 - ICC) / ICC

So there is no second estimator to write, no second set of assumptions to defend
and no second answer to reconcile. The named estimator is the one already named.

**An unmeasurable `k` is a refusal, not a fallback to 750.** Same rule §8.12
applies to gate 7's margin: an unmeasured constant is indistinguishable from no
constant. Operationally the refusal is cheap, because a `k` that does not exist
means the trainer promotes **no segments at all**, the population model answers
for every stratum, and ``weight()`` is never consulted. Measured on `collections`
on 2026-09-10 the panel holds **0 cases**, so every level refuses today.

**No borrowing across tenants.** ``LEVELS`` names ``global`` because the design
note's hierarchy does, and nothing reads it: §18.1 records cross-tenant pooling
as an open legal question under DPDP purpose limitation and §17 R9 makes
per-tenant the shipped default. A level that is enumerable but unreachable is
the honest shape for a decision somebody else has to make.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

from agent_core.treatment import cluster

logger = logging.getLogger(__name__)

#: The hierarchy, coarse to fine (§8.10). Applied to every estimator, so there
#: is one of these rather than one per model — two hierarchies is two answers to
#: "which pool does this borrower shrink toward" and no way to tell which was
#: used after the fact.
LEVELS: tuple[str, ...] = (
    "global",
    "tenant",
    "portfolio",
    "product",
    "dpd_band",
    "region",
    "borrower",
)

#: Levels this build can actually measure, because they are the ones
#: `analysis_panel` carries a column for. The rest are named by ``LEVELS`` and
#: refused by name, which is a different fact from being absent and reads
#: differently in a report.
MEASURABLE: frozenset[str] = frozenset({"tenant", "borrower"})

#: An ICC at or below this is treated as no between-cluster signal at all.
#: Below it `k` diverges — at ICC = 1e-9, `k` is a billion, which is not "shrink
#: hard toward the pool", it is arithmetic overflowing into a policy. The
#: refusal says so instead.
MIN_ICC = 1e-3

#: Clusters needed before the between-cluster variance means anything. Matches
#: `cluster.MIN_CLUSTERS`, deliberately: the same threshold that decides whether
#: a bootstrap may use percentiles decides whether a variance ratio is a number.
MIN_CLUSTERS = cluster.MIN_CLUSTERS

#: What a level's rows are keyed on. `borrower` is `customer_id`; `tenant` is
#: `tenant_id`. Everything else needs a column `analysis_panel` does not have.
_CLUSTER_KEY = {"borrower": "customer_id", "tenant": "tenant_id"}


def shrinkage_k(
    rows: Sequence[Mapping[str, Any]],
    *,
    level: str,
    value_key: str = "reward_inr",
) -> tuple[float | None, cluster.Interval | None, str]:
    """`k` for one level of the hierarchy. ``(k, interval, basis)``.

    ``k`` is ``None`` when the panel cannot measure it, and then ``basis`` says
    why in words an operator can act on. The interval is the ICC's
    cluster-bootstrap band transformed through ``k = (1 - ICC) / ICC``, which is
    monotone decreasing — so the ICC's *upper* endpoint gives `k`'s lower one and
    the two swap. Reported because §8.10 asks for a CI and because empirical
    Bayes with a point estimate of the hyperprior under-covers, and these
    intervals feed the promotion gate.
    """
    if level not in LEVELS:
        return None, None, f"{level!r} is not a level of the hierarchy: {LEVELS}"
    key = _CLUSTER_KEY.get(level)
    if key is None:
        return None, None, (
            f"level {level!r} is named by §8.10's hierarchy and `analysis_panel` "
            "carries no column for it, so its between-cluster variance cannot be "
            f"measured on this build (measurable today: {sorted(MEASURABLE)})"
        )
    usable = [r for r in rows if r.get(value_key) is not None]
    clusters = len({r.get(key) for r in usable})
    if not usable:
        return None, None, (
            f"0 panel cases carry {value_key}, so there is no variance to "
            "decompose — §8.12's rule applies and an unmeasurable hyperparameter "
            "is a refusal rather than a licence to keep the simulator's 750"
        )
    if clusters < MIN_CLUSTERS:
        return None, None, (
            f"{clusters} {level} clusters over {len(usable)} cases, below the "
            f"{MIN_CLUSTERS}-cluster floor — a between-cluster variance measured "
            "on fewer is a description of which clusters happened to be sampled"
        )

    point = cluster.icc(usable, value_key=value_key, cluster_key=key)
    if point <= MIN_ICC:
        return None, None, (
            f"the measured ICC at level {level!r} is {point:.6f}, at or below "
            f"{MIN_ICC} — there is no between-cluster variance to shrink toward, "
            "so `k` is not a large number, it is undefined"
        )

    band = cluster.bootstrap(
        usable,
        lambda sample: cluster.icc(sample, value_key=value_key, cluster_key=key),
        cluster_key=key,
    )
    return (
        _k(point),
        # k is monotone DECREASING in the ICC, so the endpoints swap. Getting
        # this backwards would publish an interval that excludes its own point
        # estimate, which is the kind of error that survives review because the
        # numbers all look plausible.
        cluster.Interval(
            value=_k(point),
            low=_k(band.high),
            high=_k(band.low),
            clusters=band.clusters,
            observations=band.observations,
            method=band.method,
            replications=band.replications,
        ),
        f"(1 - ICC) / ICC with ICC = {point:.4f}, measured over {clusters} "
        f"{level} clusters and {len(usable)} panel cases by "
        f"cluster.icc ({band.method})",
    )


def _k(icc_value: float) -> float:
    """``(1 - ICC) / ICC``, guarded at both ends.

    An ICC of 1 means every case within a cluster is identical, so the segment
    estimate is the whole story and `k` is 0. An ICC at or below
    :data:`MIN_ICC` never reaches here — :func:`shrinkage_k` refuses first —
    but a bootstrap endpoint can, and an endpoint of infinity is not an
    interval anyone can read.
    """
    if icc_value >= 1.0:
        return 0.0
    if icc_value <= MIN_ICC:
        return (1.0 - MIN_ICC) / MIN_ICC
    return (1.0 - icc_value) / icc_value


def measure(conn: Any, *, tenant_id: str | None = None) -> dict[str, Any]:
    """Every level's `k` off the panel, for a report or a model card.

    Reads inside a savepoint on a lent connection (W0), and returns refusals
    rather than raising: a hierarchy report whose unmeasurable rows are missing
    reads as a hierarchy with fewer levels.
    """
    from sqlalchemy import text

    from agent_core.treatment import schema_ready

    out: dict[str, Any] = {"levels": {}, "cases": 0}
    if conn is None or not schema_ready.has_table(conn, "analysis_panel"):
        out["refusal"] = (
            "`analysis_panel` is absent on this database (W7, sql/26), so no "
            "level of the hierarchy has a variance to decompose"
        )
        return out
    try:
        with conn.begin_nested():
            rows = [
                dict(r)
                for r in conn.execute(
                    text(
                        """
                        SELECT tenant_id, customer_id, reward_inr
                        FROM analysis_panel
                        WHERE (CAST(:tenant AS TEXT) IS NULL OR tenant_id = :tenant)
                          AND mature IS TRUE
                        """
                    ),
                    {"tenant": tenant_id},
                ).mappings()
            ]
    except Exception:
        logger.exception("hierarchy measurement failed for %s", tenant_id)
        out["refusal"] = "the panel could not be read"
        return out

    out["cases"] = len(rows)
    for level in LEVELS:
        k, band, basis = shrinkage_k(rows, level=level)
        out["levels"][level] = {
            "k": k,
            "interval": band.as_dict() if band else None,
            "basis": basis,
        }
    return out
