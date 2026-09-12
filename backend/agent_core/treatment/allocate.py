"""Layer 3 — the book, not the borrower.

Per-account argmax answers "what is best for this person". The question a
collections floor actually has is "given two million delinquent accounts, four
hundred agent-hours, sixty field slots and a per-borrower regulatory cap, what
is the best plan for tomorrow". That is a constrained assignment problem and it
does not decompose into two million independent decisions — the moment one
resource is scarce, every account's best action depends on every other
account's.

**Not an LP.** Two million accounts by nine actions is eighteen million
variables, and a simplex over that is a batch job nobody runs daily. Lagrangian
decomposition instead: attach a price λ to each scarce resource, subtract
λ × usage from every action's value, and the problem falls apart into
independent per-account argmaxes. Solve for the λ that makes demand meet
capacity and the per-account answers are jointly optimal. One pass is O(n), it
parallelises trivially, and it is the same arithmetic the engine already does.

**The dual prices are the point, not the assignment.** The solver's output that
matters is not "call these forty thousand people" — that plan is stale by
morning. It is *what an agent-hour is worth today*, in rupees. Feed that back
into ``costs.for_action`` and every local decision becomes globally optimal
without anybody writing a threshold down:

    agent capacity abundant   ->  contact stays cheap
    agent capacity scarce     ->  contact becomes expensive
    field capacity exhausted  ->  field falls below the floor by itself

Nobody has to decide that field visits stop below ₹900 of expected value. The
optimiser discovers the number, daily, and it is different on a Tuesday.

**Why this is gated on the estimators.** An optimiser does not correct estimator
error — it amplifies it. A global solve over bad uplift estimates makes the same
mistake two million times, efficiently, with a confident dual price attached to
it. So §10.4 puts six gates on the write switch and :func:`enabled` consults all
six; ``TREATMENT_DUAL_PRICING`` can only ever turn the price *off*. §8.12: a
gate with a documented bypass is worse than no gate.

**W13 — what changed, and why the shape of this module is what it is.**

Until W13 the solve was coordinate descent with a bisection inside it: six
sweeps over four resources, twenty-one demand evaluations each, five hundred and
four passes over the book to produce a price with no bound attached to it.
``converged`` meant "nothing is over capacity and no price hit the ceiling"
measured at the final prices — so nothing in the system could say how far from
optimal the answer was, and §10.4's gate ("the allocator's objective within 0.1%
and its λ within 1e-3 of the LP duals") had nothing to compare against.

It is now the algorithm §10.1's benchmark table actually measured: a cutting
plane over the Lagrangian dual, one vectorised O(n) pass per iteration, a master
LP of R+1 variables solved with the same HiGHS the benchmark used, and a swap
repair that turns the fractional relaxation into a feasible plan. Measured on
this project's hardware at 2M × 9: 39.43 s, duality gap 0.0028% at 1M, and every
λ component within ±0.03 of HiGHS's exact duals at 50k.

**numpy is imported inside :func:`solve`, never at module scope, and this is
load-bearing.** ``config.Costs.for_action`` imports this module, and that sits
inside the scorer, which sits on the path that decides whether a borrower is
contacted at all. Measured 2026-09-11: ``collections_api`` and both batch
workers have no numpy; only the voice image does. A module-level import would
take the API down to add a price it does not solve for. The read path
(:func:`price_for_action`) is pure SQL and stays that way.
"""

from __future__ import annotations

import logging
import math
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Sequence

from sqlalchemy import text

from agent_core.treatment import actions as A
from env_utils import env_bool
from agent_core.clock import utc_now

logger = logging.getLogger(__name__)

#: What each action consumes, per unit of the named resource.
#:
#: Derived from the action specs where the specs say enough — ``human_effort``
#: is what makes something compete for floor capacity — and stated explicitly
#: where they do not, because "a field visit costs forty-five minutes of
#: somebody's day and a dial costs six" is an operational fact rather than
#: something inferable from an intrusiveness score.
#:
#: A resource nothing consumes is not listed. A resource with no capacity
#: configured is not scarce and prices at zero, which is the correct default:
#: an unmeasured constraint must not silently throttle the book.
USAGE: dict[str, dict[str, float]] = {
    # Minutes of a salaried person's day.
    "agent_minutes": {A.HUMAN_CALL: 6.0, A.FIELD_VISIT: 45.0},
    # Doorstep visits. Separate from agent minutes because the binding
    # constraint is usually the van and the geography, not the hour.
    "field_slots": {A.FIELD_VISIT: 1.0},
    # Bot concurrency, in minutes of audio.
    "bot_minutes": {A.VOICE_BOT: 3.0},
    # Rail submissions. Cheap, but a sponsor bank's file has a size. NOT the
    # NACH return budget — see :data:`REFUSED_RESOURCES`.
    "mandate_presentations": {A.REPRESENT_MANDATE: 1.0},
}

RESOURCES: tuple[str, ...] = tuple(USAGE)

#: Resources §10.2 requires and this tree cannot price, each with the reason.
#:
#: They are named rather than silently absent because §10.2's complaint is that
#: "the resource set omits every constraint that actually binds in an Indian
#: NBFC", and a resource list that does not say what is missing from it reads as
#: a claim that nothing is. An entry here is a refusal with a date on it, not a
#: TODO: each needs a number or a model that does not exist yet, and inventing a
#: consumption coefficient to fill the row would produce a λ a floor manager
#: would act on.
REFUSED_RESOURCES: dict[str, str] = {
    # §10.2: consumption by a candidate presentation is P(return | x, rail,
    # date, amount), and the bucket key is (utility_code, sponsor_bank) —
    # neither of which exists. See :func:`return_budget`.
    "nach_return_budget": "no_return_model_and_no_sponsor_bank_key",
    "dlt_template_throughput": "no_dlt_registration_feed",
    "sms_header_caps": "no_per_header_capacity_in_c9",
    "whatsapp_bsp_tier": "no_bsp_tier_feed",
    # §10.4 rides the challenger reservation on this machinery, but exploration
    # runs at greediness 1.0 and δ_t = 0, so the reservation would withhold
    # capacity for a challenger that cannot be drawn.
    "challenger_reservation": "exploration_schedule_not_signed",
}

#: Ceiling on any dual price. A resource whose demand never falls to capacity
#: however high the price — because the actions consuming it are worth more than
#: this per unit — would otherwise be priced upward forever. Hitting the cap is
#: reported as ``converged=False`` rather than hidden, because it means the
#: capacity is not merely scarce but badly undersized.
MAX_PRICE = 100_000.0

#: Cutting-plane iterations. §10.1: "the solve converges tightly (1e-6, ~80
#: iterations, still under 30 s at 2M)".
MAX_ITERATIONS = 80

#: Relative gap on the dual OBJECTIVE at which the loop may stop.
DUAL_TOLERANCE = 1e-8

#: Movement of λ itself, between iterations, at which the loop may stop.
#:
#: This is the load-bearing half of the stopping rule and §10.1 defect 3 is why:
#: "at tol = 1e-4 the dual objective was within 0.002% of optimal while
#: individual λ_r drifted by up to 1.4 (18.02 against 19.37)". λ is more weakly
#: identified than the objective it comes from, so a rule that watches the
#: objective stops while the published price is still moving. Both must hold.
#:
#: Measured on synthetic books of 200 and 5,000 accounts against HiGHS's exact
#: duals: stopping on the objective alone at 1e-6 left λ 8.4e-3 out; adding this
#: rule brought it to 5.8e-7 and 6.5e-6 for six to ten more iterations — inside
#: §10.4's 1e-3 by three orders of magnitude, which is what makes the
#: gold-standard gate a gate that can pass rather than a deletion.
PRICE_TOLERANCE = 1e-5

#: How much of the master's proposal is taken each iteration after the third.
#: Kelley's cutting plane overshoots badly on early cuts, so the first three
#: iterations are undamped to escape λ = 0 and the rest are averaged.
MASTER_WEIGHT = 0.9

#: End-to-end gap above which the repaired plan is refused rather than served.
#:
#: The gap between the dual bound and the INTEGRAL primal is never zero — one
#: account takes one action, and the relaxation does not have to. §10.1 measured
#: 0.0033% at 50k with the swap repair and **0.37-1.06% with the naive one**, so
#: this ceiling is set where it separates those two: a wide gap here means the
#: repair failed, not that integrality is expensive.
REPAIR_GAP_CEILING = 0.01

#: Rounds of swap repair. §10.1 defect 1: the naive "drop the lowest-surplus
#: accounts to wait" repair gave gaps of 0.37-1.06%; the swap repair cut it to
#: 0.003%. Twelve rounds is the prototype's number and it converged in far
#: fewer; a repair still infeasible after twelve is reported as infeasible
#: rather than run longer.
REPAIR_ROUNDS = 12

#: Demand within this fraction of capacity counts as met, for the *report*.
#: Feasibility itself is exact — see :func:`solve`.
TOLERANCE = 0.02

#: How much of today's solve enters tomorrow's published price.
#:
#: §10.3 publishes λ as a business-facing price — "an agent-minute is worth ₹19
#: today" — and §10.1 defect 3 measures λ as more weakly identified than the
#: objective it comes from. An undamped price moves for numerical reasons and a
#: floor manager cannot tell that from a capacity change. Both numbers are
#: stored: ``dual_price`` is damped and served, ``dual_price_raw`` is what the
#: solve alone said, so a stability claim can be made on the undamped series.
DEFAULT_DAMPING = 0.5

#: How long :func:`enabled` caches the six-gate verdict. The gates read the
#: database and ``enabled()`` is called once per action per decision.
_GATE_TTL = 300.0

#: How long a served price is cached. Short enough that a re-solve takes effect
#: within the same run.
_CACHE_TTL = 60.0


@dataclass(frozen=True)
class Capacity:
    """Units of one resource available for one plan date, and where from.

    ``source`` is on the row because "we have sixty field slots" and "nobody
    told us how many field slots there are so we assumed sixty" are different
    claims, and until W13 they arrived in ``capacity_duals`` as the same number.
    """

    units: float
    #: ``feed`` — the C9 bank_capacity feed. ``env`` — TREATMENT_CAPACITY_*,
    #: §10.2's documented fallback.
    source: str


@dataclass(frozen=True)
class Demand:
    """One account's options, as the scorer valued them."""

    account_id: str
    #: action -> expected value in rupees, before any capacity price.
    values: Mapping[str, float]


@dataclass(frozen=True)
class Allocation:
    """The solved prices, and enough context to tell whether to believe them."""

    plan_date: date
    prices: Mapping[str, float]
    demand: Mapping[str, float]
    #: resource -> units, or ``None`` where no capacity was configured. NOT
    #: zero: see :func:`capacity_plan`.
    capacity: Mapping[str, float | None]
    capacity_source: Mapping[str, str]
    accounts: int
    iterations: int
    converged: bool
    #: The primal repair reached ``usage_r <= K_r`` for every configured
    #: resource. §10.1 defect 2 — never ship an allocator that silently
    #: over-books the field team.
    feasible: bool
    #: Best Lagrangian bound seen. An upper bound on the optimum.
    dual_bound: float = 0.0
    #: Objective of the repaired, feasible plan. A lower bound on the optimum.
    primal_value: float = 0.0
    #: ``(dual_bound - primal_value) / max(|dual_bound|, 1)``. The honest
    #: distance from optimal, end to end, repair included.
    duality_gap: float = 0.0
    #: Rupees of expected value the plan delivers, before the floor is netted
    #: off. ``primal_value`` is the surplus over the floor, which is what the
    #: LP maximises; this is the number a collections head reads.
    gross_value: float = 0.0
    #: action -> how many accounts it was assigned. The plan itself, which is
    #: mostly useful for eyeballing whether the prices produced something sane.
    mix: Mapping[str, int] = field(default_factory=dict)
    #: Why the solve could not be believed, if it could not.
    refusals: tuple[str, ...] = ()

    def binding(self) -> list[str]:
        """Resources actually constraining the plan. A zero price is not one."""
        return sorted(r for r, p in self.prices.items() if p > 0)

    def servable(self) -> bool:
        """Whether these prices may reach a cost term at all."""
        return self.converged and self.feasible and not self.refusals

    def to_log(self) -> dict[str, Any]:
        return {
            "planDate": self.plan_date.isoformat(),
            "accounts": self.accounts,
            "iterations": self.iterations,
            "converged": self.converged,
            "feasible": self.feasible,
            "binding": self.binding(),
            "prices": {r: round(p, 4) for r, p in self.prices.items()},
            "demand": {r: round(d, 2) for r, d in self.demand.items()},
            "capacity": {
                r: (None if v is None else round(float(v), 2))
                for r, v in self.capacity.items()
            },
            "capacitySource": dict(self.capacity_source),
            "dualBound": round(self.dual_bound, 2),
            "primalValue": round(self.primal_value, 2),
            "dualityGap": round(self.duality_gap, 10),
            "grossValueInr": round(self.gross_value, 2),
            "mix": dict(self.mix),
            "refusals": list(self.refusals),
        }


# ---------------------------------------------------------------------------
# Capacity — three states, and `unset` is not `0`
# ---------------------------------------------------------------------------


def capacity_plan(
    conn: Any | None = None,
    *,
    tenant_id: str | None = None,
    plan_date: date | None = None,
) -> dict[str, Capacity]:
    """Today's capacity per resource, from the feed where there is one.

    Resolution order, and the order is the point:

    1. ``bank_capacity`` for this ``(tenant_id, plan_date, resource)`` — the C9
       feed, landed by 05:00 so the 06:10 solve can consume it (§10.2). W5 built
       it and until W13 nothing read it.
    2. ``TREATMENT_CAPACITY_<RESOURCE>`` — §10.2's documented fallback, kept
       because agent hours and field slots belong to a floor manager and a
       deployment without a feed still has to run.
    3. Absent from the returned mapping entirely.

    A resource absent from the mapping is *unconfigured*, not zero-capacity.
    Until W13 those two arrived in ``capacity_duals`` as the same number, and
    the one row the table held on 2026-09-11 read ``capacity = 0.00,
    demand = 486.00, converged = t`` — which is not a resource that is 486 units
    oversubscribed but a resource nobody ever configured.

    A configured zero *is* honoured: the resource is real and its budget is
    nothing, so every action consuming it drops out of the plan and its price
    rises to the ceiling, which reports as non-convergence.
    """
    out: dict[str, Capacity] = {}
    if conn is not None and tenant_id:
        for resource, units in _feed_capacity(
            conn, tenant_id=tenant_id, plan_date=plan_date
        ).items():
            out[resource] = Capacity(units=units, source="feed")

    for resource in RESOURCES:
        if resource in out:
            continue
        raw = (os.getenv(f"TREATMENT_CAPACITY_{resource.upper()}") or "").strip()
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            logger.warning(
                "TREATMENT_CAPACITY_%s=%r is not a number — treating as unconfigured",
                resource.upper(),
                raw,
            )
            continue
        if value >= 0:
            out[resource] = Capacity(units=value, source="env")
    return out


def _feed_capacity(
    conn: Any, *, tenant_id: str, plan_date: date | None
) -> dict[str, float]:
    """C9's numbers, or nothing. Never raises: a missing feed is unconfigured."""
    from agent_core.treatment import schema_ready

    try:
        if not schema_ready.has_table(conn, "bank_capacity"):
            return {}
        rows = conn.execute(
            text(
                """
                SELECT resource, capacity_units
                FROM bank_capacity
                WHERE tenant_id = :tenant
                  AND plan_date = COALESCE(:plan_date, CURRENT_DATE)
                """
            ),
            {"tenant": tenant_id, "plan_date": plan_date},
        ).mappings().all()
    except Exception:
        logger.exception("bank_capacity read failed — falling back to configuration")
        return {}
    return {
        str(r["resource"]): float(r["capacity_units"])
        for r in rows
        if str(r["resource"]) in USAGE and r["capacity_units"] is not None
    }


def _normalise(capacity: Mapping[str, Any]) -> dict[str, Capacity]:
    """Accept a bare ``{resource: units}`` as well as resolved capacities.

    The bare form is what every caller used before W13 and what a test writes;
    it is recorded as ``env`` because a number handed to the solver directly has
    the same provenance as one read out of an environment variable — somebody
    typed it.
    """
    out: dict[str, Capacity] = {}
    for resource, value in capacity.items():
        if value is None:
            continue
        if isinstance(value, Capacity):
            out[resource] = value
        else:
            out[resource] = Capacity(units=float(value), source="env")
    return out


# ---------------------------------------------------------------------------
# The solve
# ---------------------------------------------------------------------------


def _matrices(demands: Sequence[Demand], floor: float, resources: Sequence[str]):
    """Build the value and usage matrices, with a null action appended.

    The null action — "do nothing for this account" — is column ``A`` with value
    ``floor`` and zero usage. That one column is what makes the floor part of
    the linear program rather than a branch outside it: the account's
    contribution to the Lagrangian is ``max(floor, max_a red_a) - floor``, which
    is zero exactly when nothing clears the floor, and is a max of affine
    functions of λ either way, so the dual stays convex and the subgradient
    stays ``K - usage``.

    Actions an account was not offered are ``-inf``, so they can never be chosen
    and never enter the usage.
    """
    import numpy as np

    actions = sorted({a for d in demands for a in d.values})
    index = {a: i for i, a in enumerate(actions)}
    n, m = len(demands), len(actions)

    values = np.full((n, m + 1), -np.inf, dtype=np.float64)
    values[:, m] = floor
    for row, demand in enumerate(demands):
        for action, value in demand.values.items():
            values[row, index[action]] = float(value)

    usage = np.zeros((m + 1, len(resources)), dtype=np.float64)
    for col, resource in enumerate(resources):
        per_action = USAGE.get(resource, {})
        for action, amount in per_action.items():
            if action in index:
                usage[index[action], col] = float(amount)

    return values, usage, actions


def _master(cuts, r: int):
    """Kelley's cutting-plane master: minimise θ subject to the cuts so far.

    ``g`` is the Lagrangian dual value at λ and ``s = K - usage`` its
    subgradient, so each iteration contributes the affine underestimate
    ``θ >= g_k + s_k·(λ - λ_k)``. Solved with the same HiGHS §10.1's benchmark
    used, reached through scipy rather than through ``highspy`` — R+1 variables
    and at most eighty rows, so the master is free beside the O(n) pass.
    """
    import numpy as np
    from scipy.optimize import linprog

    a_ub = np.zeros((len(cuts), r + 1), dtype=np.float64)
    b_ub = np.zeros(len(cuts), dtype=np.float64)
    for k, (g, s, lam) in enumerate(cuts):
        a_ub[k, :r] = s
        a_ub[k, r] = -1.0
        b_ub[k] = float(s @ lam) - g

    objective = np.zeros(r + 1, dtype=np.float64)
    objective[r] = 1.0
    bounds = [(0.0, MAX_PRICE)] * r + [(None, None)]
    result = linprog(objective, A_ub=a_ub, b_ub=b_ub, bounds=bounds, method="highs")
    if not result.success:
        return None, -math.inf
    return np.maximum(result.x[:r], 0.0), float(result.x[r])


def _repair(values, usage, limits, best, reduced):
    """Turn the relaxed argmax into a plan that fits, losing as little as possible.

    §10.1 defect 1, measured: dropping the lowest-surplus accounts to ``wait``
    gave gaps of 0.37-1.06%; moving the marginal account to its best alternative
    action that does not use the tight resource, **ordered by rupees lost per
    unit freed**, gave 0.003%. At two million accounts that difference is real
    money, so the repair deserves as much care as the dual loop.

    Returns the repaired assignment and whether it actually fits. §10.1 defect 2
    is that the prototype terminated at 2M with an overshoot still present:
    that is reported, never rounded away.
    """
    import numpy as np

    n, m = reduced.shape
    order = np.argsort(-reduced, axis=1)
    best = best.copy()
    rows = np.arange(n)

    for _ in range(REPAIR_ROUNDS):
        counts = np.bincount(best, minlength=m).astype(np.float64)
        over = counts @ usage - limits
        # An unconfigured resource is +inf capacity and can never be over.
        if not np.any(over > 1e-9):
            break
        for r in np.nonzero(over > 1e-9)[0]:
            on_resource = np.nonzero(usage[best, r] > 0)[0]
            if on_resource.size == 0:
                continue
            # The best alternative that does not touch this resource. The null
            # action is the last column and always qualifies, so `alt` is always
            # defined — there is no account the repair cannot move.
            alt = np.full(on_resource.size, m - 1, dtype=np.int64)
            found = np.zeros(on_resource.size, dtype=bool)
            for rank in range(1, m):
                candidate = order[on_resource, rank]
                fresh = (~found) & (usage[candidate, r] <= 0)
                alt = np.where(fresh, candidate, alt)
                found |= fresh
                if found.all():
                    break
            freed = usage[best[on_resource], r] - usage[alt, r]
            movable = freed > 1e-12
            if not np.any(movable):
                continue
            idx = on_resource[movable]
            alt = alt[movable]
            freed = freed[movable]
            loss = reduced[idx, best[idx]] - reduced[idx, alt]
            cheapest = np.argsort(loss / freed)
            taken = int(np.searchsorted(np.cumsum(freed[cheapest]), over[r]) + 1)
            switch = cheapest[:taken]
            best[idx[switch]] = alt[switch]

    counts = np.bincount(best, minlength=m).astype(np.float64)
    fits = bool(np.all(counts @ usage <= limits + 1e-6))
    return best, fits, rows


def solve(
    demands: Sequence[Demand],
    capacity: Mapping[str, Any],
    *,
    plan_date: date | None = None,
    floor: float = 0.0,
    tolerance: float = DUAL_TOLERANCE,
    price_tolerance: float = PRICE_TOLERANCE,
    max_iterations: int = MAX_ITERATIONS,
) -> Allocation:
    """Find the prices at which demand meets capacity, and say how sure it is.

    A cutting plane over the Lagrangian dual. Each iteration is one vectorised
    pass over the book — reduced value, argmax, usage — and one master LP of
    ``R + 1`` variables. The dual value at λ is an upper bound on the optimum
    and the master's optimum is a lower bound on the dual, so the loop always
    knows how far from optimal it is, which coordinate descent never did.

    The reduced value is computed in **float64 even where the values are not**,
    because differencing expected values of order 10² against λ·usage of similar
    magnitude near the threshold is exactly where float32 loses the comparison
    the assignment depends on (§10.1).

    The loop stops when the dual objective has converged **and λ itself has
    stopped moving** — see :data:`PRICE_TOLERANCE`. Two different numbers come
    back and they must not be confused: ``converged`` is about the solve, and
    ``duality_gap`` is the distance between the relaxation's bound and the
    integral plan the repair produced, which is never zero because one account
    takes one action and the relaxation does not have to.

    Returns an allocation carrying its own refusals rather than raising: a
    caller that cannot solve still has a report to file, and §8.12 makes an
    unevaluable gate a refusal rather than an exception.
    """
    day = plan_date or utc_now().date()
    resolved = _normalise(capacity)
    sources = {r: resolved[r].source if r in resolved else "unset" for r in RESOURCES}
    reported_capacity: dict[str, float | None] = {
        r: (resolved[r].units if r in resolved else None) for r in RESOURCES
    }

    def _empty(refusals: tuple[str, ...], converged: bool, feasible: bool) -> Allocation:
        return Allocation(
            plan_date=day,
            prices={r: 0.0 for r in RESOURCES},
            demand={r: 0.0 for r in RESOURCES},
            capacity=reported_capacity,
            capacity_source=sources,
            accounts=len(demands),
            iterations=0,
            converged=converged,
            feasible=feasible,
            refusals=refusals,
        )

    if not demands:
        return _empty((), True, True)

    try:
        import numpy as np  # noqa: F401
        import scipy.optimize  # noqa: F401
    except ImportError:
        # Not a crash and not a silent fallback to the old algorithm: two
        # solvers in one file is the bypass §8.12 forbids. The deployment that
        # cannot import numpy does not solve; it also does not serve a price,
        # because `persist` refuses a solve carrying refusals.
        logger.warning(
            "numpy/scipy unavailable — the allocator cannot solve. The served "
            "price is unaffected: it is read from capacity_duals in SQL."
        )
        return _empty(("numpy_unavailable",), False, False)

    import numpy as np

    resources = RESOURCES
    values, usage, actions = _matrices(demands, floor, resources)
    n, m = values.shape
    limits = np.array(
        [resolved[r].units if r in resolved else np.inf for r in resources],
        dtype=np.float64,
    )
    # An unconfigured resource is not scarce, prices at zero, and must not enter
    # the dual — a subgradient of `inf - usage` is not a number.
    active = np.nonzero(np.isfinite(limits))[0]

    lam = np.zeros(len(resources), dtype=np.float64)
    rows = np.arange(n)
    cuts: list[tuple[float, Any, Any]] = []
    best_bound = math.inf
    iterations = 0
    dual_converged = active.size == 0

    if active.size:
        caps = limits[active]
        usage_active = usage[:, active]
        lam_active = np.zeros(active.size, dtype=np.float64)
        for iteration in range(max_iterations):
            iterations = iteration + 1
            reduced = values - usage_active @ lam_active
            choice = reduced.argmax(axis=1)
            counts = np.bincount(choice, minlength=m).astype(np.float64)
            used = counts @ usage_active
            # g(λ) = Σ (max(floor, max_a red) - floor) + λ·K, convex in λ, with
            # subgradient K - usage.
            g = float(reduced[rows, choice].sum() - floor * n + lam_active @ caps)
            best_bound = min(best_bound, g)
            cuts.append((g, caps - used, lam_active.copy()))
            proposal, lower = _master(cuts, active.size)
            if proposal is None:
                break
            gap = (best_bound - lower) / max(abs(best_bound), 1.0)
            previous = lam_active
            weight = 1.0 if iteration < 3 else MASTER_WEIGHT
            lam_active = (1.0 - weight) * lam_active + weight * proposal
            moved = float(np.max(np.abs(lam_active - previous)))
            if gap <= tolerance and moved <= price_tolerance:
                dual_converged = True
                break
        lam[active] = lam_active

    reduced = values - usage @ lam
    relaxed = reduced.argmax(axis=1)
    if active.size:
        # The bound at the price actually served, folded in: it is as valid an
        # upper bound as any the loop saw, and it is the one this plan is
        # measured against.
        best_bound = min(
            best_bound,
            float(
                reduced[rows, relaxed].sum()
                - floor * n
                + lam[active] @ limits[active]
            ),
        )
    choice, fits, rows = _repair(values, usage, limits, relaxed, reduced)

    counts = np.bincount(choice, minlength=m).astype(np.float64)
    used = counts @ usage
    taken = choice != m - 1
    gross = float(np.where(taken, values[rows, choice], 0.0).sum())
    primal = float(np.where(taken, values[rows, choice] - floor, 0.0).sum())
    bound = best_bound if math.isfinite(best_bound) else primal
    gap = (bound - primal) / max(abs(bound), 1.0)

    mix: dict[str, int] = {}
    for action_index in np.nonzero(counts[: m - 1])[0]:
        mix[actions[int(action_index)]] = int(counts[action_index])

    at_ceiling = bool(np.any(lam >= MAX_PRICE - 1e-6))
    converged = bool(dual_converged) and not at_ceiling
    prices = {r: float(lam[i]) for i, r in enumerate(resources)}
    refusals: list[str] = []
    if at_ceiling:
        refusals.append("price_at_ceiling")
    elif not dual_converged:
        refusals.append("dual_did_not_converge")
    if not fits:
        refusals.append("capacity_overshoot")
    if gap > REPAIR_GAP_CEILING:
        refusals.append("integrality_gap_wide")

    if refusals:
        logger.warning(
            "capacity solve refused: %s. prices=%s demand=%s capacity=%s gap=%.3e",
            ",".join(refusals),
            prices,
            dict(zip(resources, used.tolist())),
            {r: reported_capacity[r] for r in resources},
            gap,
        )

    return Allocation(
        plan_date=day,
        prices=prices,
        demand={r: float(used[i]) for i, r in enumerate(resources)},
        capacity=reported_capacity,
        capacity_source=sources,
        accounts=n,
        iterations=iterations,
        converged=converged,
        feasible=fits,
        dual_bound=bound,
        primal_value=primal,
        duality_gap=gap,
        gross_value=gross,
        mix=mix,
        refusals=tuple(refusals),
    )


def shock_report(
    demands: Sequence[Demand],
    capacity: Mapping[str, Any],
    *,
    pct: float = 0.05,
    floor: float = 0.0,
) -> dict[str, Any]:
    """W13's first exit criterion, as a number: |Δλ|/λ under a capacity shock.

    §15.2: "**|Δλ|/λ < 0.15** day over day under a synthetic 5% capacity shock".
    A price that moves 40% when capacity moves 5% is not a price, it is the
    solver's numerical state leaking into a cost term that decides whether a
    borrower is contacted.

    Measured on the **undamped** prices of two solves of the same book, because
    damping is what a published series gets and a stability claim measured on a
    damped series is a claim about the damping.
    """
    base = solve(demands, capacity, floor=floor)
    shocked = solve(
        demands,
        {
            r: Capacity(units=c.units * (1.0 - pct), source=c.source)
            for r, c in _normalise(capacity).items()
        },
        floor=floor,
    )
    moves: dict[str, float | None] = {}
    for resource in RESOURCES:
        before = base.prices.get(resource, 0.0)
        after = shocked.prices.get(resource, 0.0)
        moves[resource] = None if before <= 0 else abs(after - before) / before
    measured = [v for v in moves.values() if v is not None]
    return {
        "pct": pct,
        "relativeMove": {r: (None if v is None else round(v, 6)) for r, v in moves.items()},
        "worst": max(measured) if measured else None,
        "threshold": 0.15,
        "clears": bool(measured) and max(measured) < 0.15,
        # An unpriced book cannot fail a stability test, and reading that as a
        # pass is how a gate becomes decorative.
        "evaluable": bool(measured),
        "base": base.to_log(),
        "shocked": shocked.to_log(),
    }


# ---------------------------------------------------------------------------
# The gold standard — the LP this is allowed to be an approximation of
# ---------------------------------------------------------------------------

#: §10.4's agreement thresholds, verbatim: "assert the allocator's objective is
#: within **0.1%** and its λ within **1e-3** of the LP duals".
GOLD_OBJECTIVE_TOLERANCE = 0.001
GOLD_PRICE_TOLERANCE = 1e-3

#: Accounts sampled for the reference solve. §10.4 says "a 50k-200k sampled
#: sub-book"; HiGHS IPM took 13.79 s at 50k and dual simplex 226.57 s, so the
#: low end is the nightly one.
GOLD_SAMPLE = 50_000


def gold_standard(
    demands: Sequence[Demand],
    capacity: Mapping[str, Any],
    *,
    floor: float = 0.0,
    sample: int = GOLD_SAMPLE,
) -> dict[str, Any]:
    """Solve the monolithic LP and check the allocator against it.

    The Lagrangian solve is not approximating the answer — §10.1 measured it
    computing the same shadow prices by a cheaper route, every component within
    ±0.03 of HiGHS's exact duals on prices of ₹11-19. This is the assertion that
    keeps being true: the same sub-book, solved both ways, nightly, with the
    disagreement reported as a number rather than assumed away.

    It is a *reference*, not a fallback. The monolithic formulation is eighteen
    million columns at book scale and dual simplex did not finish in 795 s at
    200,000 accounts; that is why the allocator exists. Sampling is what makes
    the reference affordable, and the sample is deterministic so two nights of
    "green" are two comparisons of the same thing.
    """
    try:
        import numpy as np
        from scipy.optimize import linprog
        from scipy.sparse import csr_matrix
    except ImportError:
        return {"evaluable": False, "reason": "numpy_unavailable"}

    book = list(demands)[:sample]
    if not book:
        return {"evaluable": False, "reason": "empty_book"}
    resolved = _normalise(capacity)
    active = [r for r in RESOURCES if r in resolved]
    if not active:
        return {"evaluable": False, "reason": "no_capacity_configured"}

    ours = solve(book, capacity, floor=floor)

    values, usage, actions = _matrices(book, floor, active)
    n, m = values.shape
    # Drop the null column: "assign nothing" is the slack in the per-account
    # row, not a variable with a value.
    surplus = values[:, : m - 1] - floor
    playable = np.isfinite(surplus)
    rows, cols = np.nonzero(playable)
    k = rows.size
    if k == 0:
        return {"evaluable": False, "reason": "no_playable_actions"}

    objective = -surplus[rows, cols]
    # Capacity rows, then one row per account.
    cap_rows = np.tile(np.arange(len(active)), k)
    cap_cols = np.repeat(np.arange(k), len(active))
    cap_data = usage[cols][:, : len(active)].reshape(-1)
    acct = csr_matrix(
        (np.ones(k), (rows, np.arange(k))), shape=(n, k), dtype=np.float64
    )
    caps = csr_matrix(
        (cap_data, (cap_rows, cap_cols)), shape=(len(active), k), dtype=np.float64
    )
    from scipy.sparse import vstack

    a_ub = vstack([caps, acct], format="csr")
    b_ub = np.concatenate(
        [np.array([resolved[r].units for r in active], dtype=np.float64), np.ones(n)]
    )
    result = linprog(
        objective, A_ub=a_ub, b_ub=b_ub, bounds=(0.0, 1.0), method="highs"
    )
    if not result.success:
        return {"evaluable": False, "reason": f"lp_failed:{result.status}"}

    lp_objective = float(-result.fun)
    # linprog minimises, so the marginals on `A_ub x <= b` are non-positive and
    # the shadow price of a unit of capacity is their negation.
    lp_prices = {
        r: float(max(0.0, -result.ineqlin.marginals[i])) for i, r in enumerate(active)
    }

    denominator = max(abs(lp_objective), 1.0)
    objective_error = abs(ours.primal_value - lp_objective) / denominator
    price_error = {
        r: abs(ours.prices.get(r, 0.0) - lp_prices[r]) for r in active
    }
    worst_price = max(price_error.values()) if price_error else 0.0
    agrees = (
        ours.servable()
        and objective_error <= GOLD_OBJECTIVE_TOLERANCE
        and worst_price <= GOLD_PRICE_TOLERANCE
    )
    return {
        "evaluable": True,
        "accounts": n,
        "actions": len(actions) - 1,
        "variables": int(k),
        "lpObjective": round(lp_objective, 2),
        "allocatorObjective": round(ours.primal_value, 2),
        "objectiveError": objective_error,
        "objectiveTolerance": GOLD_OBJECTIVE_TOLERANCE,
        "lpPrices": {r: round(v, 6) for r, v in lp_prices.items()},
        "allocatorPrices": {r: round(ours.prices.get(r, 0.0), 6) for r in active},
        "priceError": {r: round(v, 8) for r, v in price_error.items()},
        "worstPriceError": worst_price,
        "priceTolerance": GOLD_PRICE_TOLERANCE,
        # The flag `write_switch_objections` counts nights on. A solve that
        # could not be believed cannot agree with anything.
        "agrees": bool(agrees),
        "allocation": ours.to_log(),
    }


# ---------------------------------------------------------------------------
# The NACH return budget — measured, and refused
# ---------------------------------------------------------------------------


def return_budget(conn: Any, *, tenant_id: str, days: int = 90) -> dict[str, Any]:
    """Today's NACH return ratio, and why it cannot become a price here.

    §10.2 calls this "the only capacity constraint in the rails layer that a
    human cannot exploit by hand". A creditor whose return ratio exceeds **50%**
    pays ₹5 per return on the excess and, since **1 October 2024**, is barred
    from registering new mandates until the ratio falls back under 50% — phased
    ₹1 from 1 Apr 2024, ₹5 from 1 Jul 2024, the registration bar from 1 Oct
    2024, across NPCI circulars NACH/007 → /012 → /014. The ratio is
    ``returned / (confirmed + returned)``, **excluding rejects**, and the dual is
    effectively infinite above ~45% to leave headroom for in-flight files.

    Note the direction of the incentive, which is why no human works this
    constraint by hand: because the denominator includes *confirmed* debits,
    presenting many high-probability-of-success debits **buys** return budget.

    Two things stop this becoming a resource with a λ, and both are structural
    rather than a matter of effort:

    * **The bucket key does not exist.** §10.2 is explicit that it is keyed on
      ``(utility_code, sponsor_bank)`` and "never on the utility code alone: the
      same code presented through two sponsor banks is two buckets, and one
      relationship can be barred while the other is not". Neither column is in
      this schema. The ratio below is therefore tenant-wide, which is the
      aggregate of buckets that can be independently barred — useful as a
      warning, wrong as a constraint.
    * **The consumption coefficient is a model.** A candidate presentation
      consumes ``P(return | x, rail, date, amount)``, not 1.0. No estimator in
      this tree produces it; W10 refused for want of labels.

    So this reports and refuses. The ratio is worth having anyway: it is the one
    number here that a regulator can check.
    """
    from agent_core.treatment import schema_ready

    out: dict[str, Any] = {
        "windowDays": days,
        "ceiling": 0.50,
        "prudentCeiling": 0.45,
        "refusedBecause": [
            "no_sponsor_bank_key",
            "no_return_model",
        ],
        "keyedOn": None,
    }
    try:
        if not schema_ready.has_table(conn, "mandate_presentations"):
            out["evaluable"] = False
            out["reason"] = "no_mandate_presentations_table"
            return out
        row = conn.execute(
            text(
                """
                SELECT
                  count(*) FILTER (WHERE status = 'success')::int  AS confirmed,
                  count(*) FILTER (WHERE status = 'returned')::int AS returned,
                  count(*) FILTER (WHERE status = 'cancelled')::int AS excluded_rejects
                FROM mandate_presentations
                WHERE tenant_id = :tenant
                  AND presented_at >= now() - make_interval(days => :days)
                """
            ),
            {"tenant": tenant_id, "days": days},
        ).mappings().first()
    except Exception:
        logger.exception("return ratio read failed")
        out["evaluable"] = False
        out["reason"] = "read_failed"
        return out

    confirmed = int((row or {}).get("confirmed") or 0)
    returned = int((row or {}).get("returned") or 0)
    denominator = confirmed + returned
    out["confirmed"] = confirmed
    out["returned"] = returned
    out["excludedRejects"] = int((row or {}).get("excluded_rejects") or 0)
    out["evaluable"] = denominator > 0
    if not denominator:
        # Not "the ratio is zero". Nothing has been presented and settled in
        # the window, so there is no ratio -- and a creditor reading 0% would
        # read maximum headroom off an absence of evidence.
        out["reason"] = "no_settled_presentations_in_window"
    out["ratio"] = (returned / denominator) if denominator else None
    out["headroomPresentations"] = (
        # Confirmed debits this many more would have to be, at today's mix, to
        # keep the ratio under the prudent ceiling.
        None
        if not denominator
        else max(0.0, returned / 0.45 - denominator)
    )
    return out


# ---------------------------------------------------------------------------
# The write switch — six gates, and no way round them
# ---------------------------------------------------------------------------

#: Consecutive green gold-standard runs §10.4 requires before the write switch.
GOLD_STANDARD_NIGHTS = 10

#: The batch job names the gold standard and the solve record themselves under.
JOB_CAPACITY_SOLVE = "w13.capacity_solve"
JOB_ALLOCATOR_GOLD = "w13.allocator_gold"
JOB_ALLOCATOR_REGRET = "w13.allocator_regret"


def _last_result(conn: Any, *, tenant_id: str, job: str) -> dict[str, Any] | None:
    """The newest completed run of this job, or ``None`` if it never ran.

    ``work_runtime_jobs`` is the ledger rather than a new table: §10.5 asks for
    a ``job_runs`` and this repository already has two job ledgers. A third
    would be the fourth contact-window restatement in a different costume.
    """
    from agent_core.treatment import schema_ready

    if not schema_ready.has_table(conn, "work_runtime_jobs"):
        return None
    row = conn.execute(
        text(
            """
            SELECT result FROM work_runtime_jobs
            WHERE tenant_id = :tenant AND workflow_type = :job
              AND status = 'completed'
            ORDER BY updated_at DESC
            LIMIT 1
            """
        ),
        {"tenant": tenant_id, "job": job},
    ).mappings().first()
    if row is None:
        return None
    return row["result"] if isinstance(row["result"], dict) else {}


def write_switch_objections(conn: Any, *, tenant_id: str) -> list[str]:
    """§10.4's six gates on the allocator write switch, each as a measurement.

    "An LP does not correct estimator error; it amplifies it — it makes the same
    mistake two million times with a confident dual price attached." So the
    prices are solved, persisted and published, and **nothing consumes them**
    until every one of these clears.

    An empty list is the only thing that opens the switch, and there is no
    override: §8.12 makes a gate with a documented bypass worse than no gate,
    and ``TREATMENT_DUAL_PRICING`` can only ever turn the price off.

    Raises nothing, and an unreadable gate is an objection rather than a pass —
    the fail-closed direction, because the thing being gated changes who gets
    contacted.
    """
    from agent_core.treatment import registry

    objections: list[str] = []

    def guarded(label: str, read):
        """Run one gate's read inside a savepoint.

        W8a shipped a transaction-abort cascade this shape: a read of a table
        the database does not have yet fails, and the failure aborts the
        CALLER's transaction rather than the read. These gates run inside a
        decision, and `db.engine.connect()` is a lent connection under test, so
        "my own connection" is not. A gate that cannot be read is an objection;
        it is not an outage for whatever was using the transaction.
        """
        try:
            savepoint = conn.begin_nested()
        except Exception:
            savepoint = None
        try:
            value = read()
        except Exception:
            if savepoint is not None:
                savepoint.rollback()
            logger.exception("write-switch gate %s unreadable", label)
            objections.append(f"{label}_unreadable")
            return None
        if savepoint is not None:
            savepoint.close()
        return value

    # 1. A learned estimator is serving, promoted through §8.12. "The hazard at
    #    minimum." Everything else on this list is arithmetic about a number
    #    this one says nobody should trust yet.
    # "the hazard at minimum" (§10.4). In this tree the payment-timing hazard is
    # registered under the `timing` target — §8.2's "fixed half-life the
    # payment-timing hazard is meant to replace".
    marker = object()
    champion = guarded(
        "estimator_registry",
        lambda: registry.champion(conn, tenant_id=tenant_id, target="timing") or marker,
    )
    if champion is marker:
        objections.append("no_promoted_estimator")

    # 2. Nightly gold-standard agreement, green ten consecutive nights.
    nights = guarded(
        "gold_standard", lambda: _gold_standard_streak(conn, tenant_id=tenant_id)
    )
    if nights is not None and nights < GOLD_STANDARD_NIGHTS:
        objections.append(f"gold_standard_nights={nights}")

    # 3/4. Price stability under shock, and capacity conservation. Both are
    #      properties of the last solve, and a solve that never happened is not
    #      a solve that passed.
    last = guarded("last_solve", lambda: _last_solve(conn, tenant_id=tenant_id))
    if last is None:
        objections.append("no_solve_on_record")
    else:
        if not last["feasible"]:
            objections.append("last_solve_infeasible")
        if not last["converged"]:
            objections.append("last_solve_not_converged")
        if last["stale_days"] is not None and last["stale_days"] > 1:
            objections.append(f"last_solve_stale_days={last['stale_days']}")
        if not last["all_fed"]:
            # 5. The capacity feed: C9 arriving daily with real agent-minutes,
            #    field slots and bot concurrency. A price solved against an
            #    environment variable prices somebody's guess.
            objections.append("capacity_not_from_feed")

    # 6. Objective-mismatch regret measured. §10.4: "before the write switch is
    #    flipped we publish the regret of greedy-EV-plus-λ against a
    #    dual-adjusted learner on the gold-standard sub-book … That is a
    #    measurement with a date, not an assumption."
    filed = guarded(
        "regret",
        lambda: _last_result(conn, tenant_id=tenant_id, job=JOB_ALLOCATOR_REGRET)
        or marker,
    )
    if filed is marker:
        objections.append("regret_not_measured")
    elif filed is not None and filed.get("regretInr") is None:
        # Filed, and it says the comparison cannot be made. That satisfies "a
        # measurement with a date" and does NOT open the gate: a null regret
        # does not answer §10.4's question ("if they differ materially, the
        # ordering of the estimator and allocator waves is wrong"). It becomes
        # answerable exactly when gate 1 does, which is why these two gates are
        # not independent.
        reason = filed.get("refusedBecause") or "unknown"
        objections.append(f"regret_not_measurable:{reason}")

    return objections


def _gold_standard_streak(conn: Any, *, tenant_id: str) -> int:
    """Consecutive completed gold-standard runs, newest first, stopping at a failure."""
    from agent_core.treatment import schema_ready

    if not schema_ready.has_table(conn, "work_runtime_jobs"):
        return 0
    rows = conn.execute(
        text(
            """
            SELECT status, result
            FROM work_runtime_jobs
            WHERE tenant_id = :tenant AND workflow_type = :job
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant": tenant_id, "job": JOB_ALLOCATOR_GOLD, "limit": GOLD_STANDARD_NIGHTS},
    ).mappings().all()
    streak = 0
    for row in rows:
        result = row["result"] if isinstance(row["result"], dict) else {}
        if row["status"] != "completed" or not result.get("agrees"):
            break
        streak += 1
    return streak


def _last_solve(conn: Any, *, tenant_id: str) -> dict[str, Any] | None:
    from agent_core.treatment import schema_ready

    if not schema_ready.has_column(conn, "capacity_duals", "feasible"):
        return None
    row = conn.execute(
        text(
            """
            SELECT bool_and(converged) AS converged,
                   bool_and(feasible)  AS feasible,
                   max(plan_date)      AS plan_date,
                   bool_and(capacity_source = 'feed') AS all_fed,
                   (CURRENT_DATE - max(plan_date))::int AS stale_days
            FROM capacity_duals
            WHERE tenant_id = :tenant
              AND plan_date = (
                SELECT max(plan_date) FROM capacity_duals WHERE tenant_id = :tenant
              )
            """
        ),
        {"tenant": tenant_id},
    ).mappings().first()
    if not row or row["plan_date"] is None:
        return None
    return {
        "converged": bool(row["converged"]),
        "feasible": bool(row["feasible"]),
        "all_fed": bool(row["all_fed"]),
        "stale_days": None if row["stale_days"] is None else int(row["stale_days"]),
    }


def enabled() -> bool:
    """Whether dual prices reach the cost term.

    Off by default, and off regardless of the environment variable until every
    one of §10.4's six gates clears — see :func:`write_switch_objections`. An
    optimiser over estimates that have not proved themselves makes the same
    mistake across the whole book at once; until then simple daily quotas per
    channel are sufficient and safe.

    Fails closed. An unreadable gate disables the price, because the alternative
    is a cost term that changes who gets contacted on the strength of a query
    that did not run.
    """
    if not env_bool("TREATMENT_DUAL_PRICING"):
        return False
    return not _cached_objections()


def _cached_objections() -> list[str]:
    global _GATE_CACHE
    try:
        import db as dbmod

        tenant = dbmod.current_tenant()
    except Exception:
        return ["tenant_unresolvable"]

    now = time.monotonic()
    cached = _GATE_CACHE.get(tenant)
    if cached and now - cached[0] < _GATE_TTL:
        return cached[1]
    try:
        with dbmod.engine.connect() as conn:
            objections = write_switch_objections(conn, tenant_id=tenant)
    except Exception:
        logger.exception("write-switch gate unreadable — dual pricing stays off")
        objections = ["gate_unreadable"]
    _GATE_CACHE[tenant] = (now, objections)
    return objections


# ---------------------------------------------------------------------------
# Persisting, and the price that comes back
# ---------------------------------------------------------------------------


def damping() -> float:
    raw = (os.getenv("ALLOCATOR_DAMPING") or "").strip()
    if not raw:
        return DEFAULT_DAMPING
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_DAMPING
    return min(1.0, max(0.0, value))


def persist(conn: Any, allocation: Allocation, *, tenant_id: str) -> dict[str, Any]:
    """Write today's prices — unless the solve cannot be believed.

    §10.1 defect 4: ``allocate.py`` used to write a dual the solver had declared
    meaningless straight into every cost term, where one mistyped capacity
    produces a ₹4.5m field-visit price. A non-converged or infeasible solve now
    **refuses to persist**: the previous day's damped price stands, and the
    degradation is named in the return value rather than logged and forgotten.

    What is written is the **damped** price, ``(1-α)·yesterday + α·today``,
    beside the solver's own number. §10.3 publishes λ as a business price and
    §10.1 defect 3 measured λ as more weakly identified than the objective it
    comes from, so a published series that moves with the solver's numerical
    state would have a floor manager hiring against noise.
    """
    from agent_core.treatment import schema_ready

    if not schema_ready.w13_ready(conn):
        # Writing the price without the columns that say whether to believe it
        # is how §10.1 defect 4 happened. On a database behind sql/33 the
        # honest outcome is no price at all, and `price_for_action` already
        # reads zero there.
        logger.warning(
            "capacity_duals is behind migration 0122 \u2014 refusing to write a "
            "price whose feasibility this schema cannot record."
        )
        return {"written": 0, "refused": ["schema_not_ready"]}
    if not allocation.servable():
        reasons = list(allocation.refusals) or ["not_converged"]
        logger.warning(
            "refusing to persist capacity duals for %s: %s. Yesterday's prices stand.",
            allocation.plan_date,
            ",".join(reasons),
        )
        return {"written": 0, "refused": reasons}

    alpha = damping()
    previous = _previous_prices(conn, tenant_id=tenant_id, before=allocation.plan_date)
    written = 0
    for resource in RESOURCES:
        raw = float(allocation.prices.get(resource, 0.0))
        prior = previous.get(resource)
        served = raw if prior is None else (1.0 - alpha) * prior + alpha * raw
        conn.execute(
            text(
                """
                INSERT INTO capacity_duals (
                  id, tenant_id, plan_date, resource, capacity, capacity_source,
                  demand, dual_price, dual_price_raw, accounts, converged,
                  feasible, iterations, dual_bound, primal_value, duality_gap,
                  damping
                ) VALUES (
                  :id, :tenant, :plan_date, :resource, :capacity, :source,
                  :demand, :price, :price_raw, :accounts, :converged,
                  :feasible, :iterations, :dual_bound, :primal, :gap,
                  :damping
                )
                ON CONFLICT (tenant_id, plan_date, resource) DO UPDATE SET
                  capacity = EXCLUDED.capacity,
                  capacity_source = EXCLUDED.capacity_source,
                  demand = EXCLUDED.demand,
                  dual_price = EXCLUDED.dual_price,
                  dual_price_raw = EXCLUDED.dual_price_raw,
                  accounts = EXCLUDED.accounts,
                  converged = EXCLUDED.converged,
                  feasible = EXCLUDED.feasible,
                  iterations = EXCLUDED.iterations,
                  dual_bound = EXCLUDED.dual_bound,
                  primal_value = EXCLUDED.primal_value,
                  duality_gap = EXCLUDED.duality_gap,
                  damping = EXCLUDED.damping,
                  solved_at = now()
                """
            ),
            {
                "id": f"CD-{uuid.uuid4().hex[:12].upper()}",
                "tenant": tenant_id,
                "plan_date": allocation.plan_date,
                "resource": resource,
                # NULL, not 0.0: unconfigured is not a budget of nothing.
                "capacity": allocation.capacity.get(resource),
                "source": allocation.capacity_source.get(resource, "unset"),
                "demand": allocation.demand.get(resource, 0.0),
                "price": served,
                "price_raw": raw,
                "accounts": allocation.accounts,
                "converged": allocation.converged,
                "feasible": allocation.feasible,
                "iterations": allocation.iterations,
                "dual_bound": allocation.dual_bound,
                "primal": allocation.primal_value,
                "gap": allocation.duality_gap,
                "damping": alpha if previous else None,
            },
        )
        written += 1
    return {"written": written, "refused": [], "damping": alpha}


def _previous_prices(conn: Any, *, tenant_id: str, before: date) -> dict[str, float]:
    """The last served price per resource strictly before this plan date."""
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT ON (resource) resource, dual_price
            FROM capacity_duals
            WHERE tenant_id = :tenant AND plan_date < :before
              AND converged AND feasible
            ORDER BY resource, plan_date DESC
            """
        ),
        {"tenant": tenant_id, "before": before},
    ).mappings().all()
    return {str(r["resource"]): float(r["dual_price"] or 0.0) for r in rows}


def price_for_action(action: str) -> float:
    """Today's capacity surcharge on one action, in rupees.

    Zero when dual pricing is gated off, when no solve has run, or when nothing
    is scarce — which are three different situations that all correctly produce
    the same answer, because in all three the ledger cost is the whole cost.

    Never raises, and never imports numpy. This sits inside ``costs.for_action``,
    which sits inside the scorer, which sits on the path that decides whether a
    borrower is contacted at all; a missing table must cost accuracy, not
    availability, and an image without a solver must still serve.
    """
    if not enabled():
        return 0.0
    surcharge = 0.0
    prices = _todays_prices()
    for resource, usage in USAGE.items():
        per_unit = usage.get(action)
        if per_unit:
            surcharge += prices.get(resource, 0.0) * per_unit
    return surcharge


def _todays_prices() -> dict[str, float]:
    """Read the day's prices, cached briefly, **per tenant**.

    The cache was one process-global tuple until W13 while the query it caches
    is tenant-scoped, so for up to a minute after any tenant's first read every
    other tenant was served that tenant's prices — capacity, scarcity and a
    number that changes who gets contacted, crossing a boundary the rest of this
    system enforces in the database.

    Only a solve that converged **and** reached feasibility is servable, which
    is the second half of §10.1 defect 4: refusing to persist is not enough if a
    row written by an older build is still readable.
    """
    global _CACHE

    try:
        import db as dbmod

        tenant = dbmod.current_tenant()
    except Exception:
        logger.exception("tenant unresolvable — treating capacity as unconstrained")
        return {}

    now = time.monotonic()
    cached = _CACHE.get(tenant)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    try:
        with dbmod.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT resource, dual_price
                    FROM capacity_duals
                    WHERE tenant_id = :tenant AND plan_date = CURRENT_DATE
                      AND converged AND feasible
                    """
                ),
                {"tenant": tenant},
            ).mappings().all()
        prices = {str(r["resource"]): float(r["dual_price"] or 0.0) for r in rows}
    except Exception:
        logger.exception("capacity dual price read failed — treating as unconstrained")
        prices = {}

    _CACHE[tenant] = (now, prices)
    return prices


_CACHE: dict[str, tuple[float, dict[str, float]]] = {}
_GATE_CACHE: dict[str, tuple[float, list[str]]] = {}


def reset_cache() -> None:
    """Test hook, and what to call after a solve."""
    _CACHE.clear()
    _GATE_CACHE.clear()


def resource_report(conn: Any | None = None, *, tenant_id: str | None = None) -> dict[str, Any]:
    """What is priced, what is unconfigured, and what is refused outright.

    §10.2's complaint is that the resource set "omits every constraint that
    actually binds in an Indian NBFC". This is the answer to that in one object:
    the four resources with a consumption coefficient, the state of each one's
    capacity, and the five §10.2 names that this tree declines to invent numbers
    for.
    """
    resolved = capacity_plan(conn, tenant_id=tenant_id) if conn is not None else capacity_plan()
    out: dict[str, Any] = {
        "priced": {
            resource: {
                "actions": sorted(USAGE[resource]),
                "capacity": resolved[resource].units if resource in resolved else None,
                "source": resolved[resource].source if resource in resolved else "unset",
            }
            for resource in RESOURCES
        },
        "refused": dict(REFUSED_RESOURCES),
    }
    if conn is not None and tenant_id:
        out["returnBudget"] = return_budget(conn, tenant_id=tenant_id)
    return out
