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
independent per-account argmaxes again. Solve for the λ that makes demand meet
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
it. The estimators have to beat their priors on a holdout before this is allowed
to act on them, which is why :func:`enabled` is off by default and why
``costs.for_action`` reads the prices only when it is on.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import text

from agent_core.treatment import actions as A

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
    # Rail submissions. Cheap, but a sponsor bank's file has a size.
    "mandate_presentations": {A.REPRESENT_MANDATE: 1.0},
}

RESOURCES: tuple[str, ...] = tuple(USAGE)

#: Ceiling on any dual price. A resource whose demand never falls to capacity
#: however high the price — because the actions consuming it are worth more than
#: this per unit — would otherwise bisect upward forever. Hitting the cap is
#: reported as ``converged=False`` rather than hidden, because it means the
#: capacity is not merely scarce but badly undersized.
MAX_PRICE = 100_000.0

#: Bisection steps per resource. Twenty halvings take the bracket from the cap
#: to under a rupee, which is finer than the cost inputs are known to.
BISECT_STEPS = 20

#: Sweeps over the resource set. Resources interact — pricing agent minutes
#: pushes demand onto field slots — so one pass per resource is not enough and
#: a fixed handful is plenty.
MAX_SWEEPS = 6

#: Demand within this fraction of capacity counts as met. Chasing an exact
#: match wastes iterations on a number whose inputs are planning figures.
TOLERANCE = 0.02


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
    capacity: Mapping[str, float]
    accounts: int
    sweeps: int
    converged: bool
    #: action -> how many accounts it was assigned. The plan itself, which is
    #: mostly useful for eyeballing whether the prices produced something sane.
    mix: Mapping[str, int] = field(default_factory=dict)

    def binding(self) -> list[str]:
        """Resources actually constraining the plan. A zero price is not one."""
        return sorted(r for r, p in self.prices.items() if p > 0)

    def to_log(self) -> dict[str, Any]:
        return {
            "planDate": self.plan_date.isoformat(),
            "accounts": self.accounts,
            "sweeps": self.sweeps,
            "converged": self.converged,
            "binding": self.binding(),
            "prices": {r: round(p, 4) for r, p in self.prices.items()},
            "demand": {r: round(d, 2) for r, d in self.demand.items()},
            "capacity": dict(self.capacity),
            "mix": dict(self.mix),
        }


# ---------------------------------------------------------------------------
# The solve
# ---------------------------------------------------------------------------


def _adjusted_choice(
    values: Mapping[str, float], prices: Mapping[str, float], floor: float
) -> tuple[str | None, dict[str, float]]:
    """The best action for one account at these prices, and what it consumes.

    ``None`` when nothing clears the floor once capacity is priced in — which
    is the mechanism, not a failure. An action that was worth ₹40 when agents
    were idle is worth ₹40 minus six minutes of a scarce agent's time when they
    are not, and falling below the floor is how the ladder throttles itself.
    """
    best: str | None = None
    best_value = floor
    # Sorted so ties break deterministically. Two solves of the same book must
    # not disagree, or the dual prices wander and nobody can tell scarcity from
    # numerical noise.
    for action in sorted(values):
        cost = sum(
            prices.get(resource, 0.0) * usage.get(action, 0.0)
            for resource, usage in USAGE.items()
        )
        value = values[action] - cost
        if value > best_value:
            best, best_value = action, value

    if best is None:
        return None, {}
    return best, {
        resource: usage[best]
        for resource, usage in USAGE.items()
        if usage.get(best)
    }


def _demand_at(
    demands: Sequence[Demand], prices: Mapping[str, float], floor: float
) -> tuple[dict[str, float], dict[str, int]]:
    totals = {resource: 0.0 for resource in USAGE}
    mix: dict[str, int] = {}
    for demand in demands:
        action, usage = _adjusted_choice(demand.values, prices, floor)
        if action is None:
            continue
        mix[action] = mix.get(action, 0) + 1
        for resource, amount in usage.items():
            totals[resource] += amount
    return totals, mix


def solve(
    demands: Sequence[Demand],
    capacity: Mapping[str, float],
    *,
    plan_date: date | None = None,
    floor: float = 0.0,
) -> Allocation:
    """Find the prices at which demand meets capacity.

    Coordinate descent over resources, bisection within each. Not the fastest
    method available and deliberately the most legible one: every intermediate
    state is a set of prices and a set of demands, both of which a collections
    head can read, and a solver whose behaviour cannot be explained is a solver
    nobody will let near a book.
    """
    prices = {resource: 0.0 for resource in USAGE}
    if not demands:
        return Allocation(
            plan_date=plan_date or datetime.now(timezone.utc).date(),
            prices=prices,
            demand={r: 0.0 for r in USAGE},
            capacity=dict(capacity),
            accounts=0,
            sweeps=0,
            converged=True,
        )

    sweeps = 0
    for sweep in range(MAX_SWEEPS):
        sweeps = sweep + 1
        moved = False
        for resource in RESOURCES:
            limit = capacity.get(resource)
            if limit is None or limit <= 0:
                # Unmeasured or unlimited. Priced at zero rather than at
                # infinity: a constraint nobody configured must not throttle
                # the book, and a constraint of zero should be expressed by
                # removing the action from the bucket policy, where a
                # compliance officer can see it.
                continue

            # Is this resource binding *at all*? Asked at a price of zero for
            # it, holding the others where they are.
            #
            # Asking at the current price would be circular, and was: a
            # resource is under capacity precisely *because* it is being
            # charged for, so testing it at its own price says "not scarce",
            # zeroes the price, and demand floods back. With two interacting
            # resources that oscillates — pricing field slots pushes work onto
            # agents, which un-prices agents, which pulls work back off
            # field slots — and the solve terminates with one of them silently
            # unpriced and oversubscribed.
            free = {**prices, resource: 0.0}
            totals, _ = _demand_at(demands, free, floor)
            if totals[resource] <= limit * (1 + TOLERANCE):
                if prices[resource] > 0:
                    prices[resource] = 0.0
                    moved = True
                continue

            lo, hi = 0.0, MAX_PRICE
            for _ in range(BISECT_STEPS):
                mid = (lo + hi) / 2.0
                trial = {**prices, resource: mid}
                totals, _ = _demand_at(demands, trial, floor)
                if totals[resource] > limit:
                    lo = mid  # still oversubscribed — charge more
                else:
                    hi = mid
            if abs(hi - prices[resource]) > 1e-6:
                moved = True
            prices[resource] = hi

        if not moved:
            break

    totals, mix = _demand_at(demands, prices, floor)
    converged = all(
        capacity.get(r) is None
        or capacity.get(r, 0) <= 0
        or totals[r] <= capacity[r] * (1 + TOLERANCE)
        for r in RESOURCES
    ) and all(p < MAX_PRICE for p in prices.values())

    if not converged:
        logger.warning(
            "capacity solve did not converge: prices=%s demand=%s capacity=%s. "
            "A resource still oversubscribed at the price ceiling is undersized "
            "rather than merely scarce.",
            prices,
            totals,
            dict(capacity),
        )

    return Allocation(
        plan_date=plan_date or datetime.now(timezone.utc).date(),
        prices=prices,
        demand=totals,
        capacity=dict(capacity),
        accounts=len(demands),
        sweeps=sweeps,
        converged=converged,
        mix=mix,
    )


# ---------------------------------------------------------------------------
# Capacity, and the prices that come back
# ---------------------------------------------------------------------------


def capacity_plan() -> dict[str, float]:
    """Today's capacity, per resource.

    Environment-driven, and the design note flags whose numbers these are as an
    open question — agent hours and field slots belong to a floor manager, not
    to this repository. Unset means unconstrained, which prices at zero and
    changes nothing.
    """
    out: dict[str, float] = {}
    for resource in RESOURCES:
        raw = (os.getenv(f"TREATMENT_CAPACITY_{resource.upper()}") or "").strip()
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            logger.warning(
                "TREATMENT_CAPACITY_%s=%r is not a number — treating as unconstrained",
                resource.upper(),
                raw,
            )
            continue
        if value > 0:
            out[resource] = value
    return out


def enabled() -> bool:
    """Whether dual prices reach the cost term.

    Off by default, and this is the gate the design note is emphatic about: an
    optimiser over estimates that have not proved themselves makes the same
    mistake across the whole book at once. Until the estimators beat their
    priors on a holdout, simple daily quotas per channel are sufficient and
    safe.
    """
    return (os.getenv("TREATMENT_DUAL_PRICING") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def persist(conn: Any, allocation: Allocation, *, tenant_id: str) -> None:
    """Write today's prices. One row per resource, replacing any earlier solve."""
    for resource in RESOURCES:
        conn.execute(
            text(
                """
                INSERT INTO capacity_duals (
                  id, tenant_id, plan_date, resource, capacity, demand,
                  dual_price, accounts, converged, iterations
                ) VALUES (
                  :id, :tenant, :plan_date, :resource, :capacity, :demand,
                  :price, :accounts, :converged, :sweeps
                )
                ON CONFLICT (tenant_id, plan_date, resource) DO UPDATE SET
                  capacity = EXCLUDED.capacity,
                  demand = EXCLUDED.demand,
                  dual_price = EXCLUDED.dual_price,
                  accounts = EXCLUDED.accounts,
                  converged = EXCLUDED.converged,
                  iterations = EXCLUDED.iterations,
                  solved_at = now()
                """
            ),
            {
                "id": f"CD-{uuid.uuid4().hex[:12].upper()}",
                "tenant": tenant_id,
                "plan_date": allocation.plan_date,
                "resource": resource,
                "capacity": allocation.capacity.get(resource, 0.0),
                "demand": allocation.demand.get(resource, 0.0),
                "price": allocation.prices.get(resource, 0.0),
                "accounts": allocation.accounts,
                "converged": allocation.converged,
                "sweeps": allocation.sweeps,
            },
        )


def price_for_action(action: str) -> float:
    """Today's capacity surcharge on one action, in rupees.

    Zero when dual pricing is off, when no solve has run, or when nothing is
    scarce — which are three different situations that all correctly produce
    the same answer, because in all three the ledger cost is the whole cost.

    Never raises. This sits inside ``costs.for_action``, which sits inside the
    scorer, which sits on the path that decides whether a borrower is contacted
    at all; a missing table must cost accuracy, not availability.
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
    """Read the day's prices, cached briefly.

    A per-decision query for a number that changes once a day would be one
    round trip per account per sweep. The TTL is short enough that a re-solve
    takes effect within the same run.
    """
    import time

    global _CACHE
    now = time.monotonic()
    if _CACHE and now - _CACHE[0] < _CACHE_TTL:
        return _CACHE[1]

    try:
        import db as dbmod

        with dbmod.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT resource, dual_price
                    FROM capacity_duals
                    WHERE tenant_id = :tenant AND plan_date = CURRENT_DATE
                    """
                ),
                {"tenant": dbmod.current_tenant()},
            ).mappings().all()
        prices = {str(r["resource"]): float(r["dual_price"] or 0.0) for r in rows}
    except Exception:
        logger.exception("capacity dual price read failed — treating as unconstrained")
        prices = {}

    _CACHE = (now, prices)
    return prices


_CACHE_TTL = 60.0
_CACHE: tuple[float, dict[str, float]] | None = None


def reset_cache() -> None:
    """Test hook, and what to call after a solve."""
    global _CACHE
    _CACHE = None
