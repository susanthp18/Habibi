#!/usr/bin/env python
"""Solve tomorrow's book against tomorrow's capacity, and price what is scarce.

    TREATMENT_CAPACITY_AGENT_MINUTES=24000 \\
    TREATMENT_CAPACITY_FIELD_SLOTS=60 \\
      .venv/Scripts/python scripts/solve_capacity.py

    .venv/Scripts/python scripts/solve_capacity.py --dry-run
    .venv/Scripts/python scripts/solve_capacity.py --include-simulated

Runs once a day, before the sweep. Reads the demand curve the engine has
already computed — every decision row carries the full ranked candidate list
with an expected value per action — and finds the prices at which the book's
demand for agent minutes, field slots and bot concurrency meets what the floor
actually has.

The output that matters is not the plan. It is a handful of numbers of the form
"an agent-minute is worth ₹17.50 today", written to ``capacity_duals``, which
``costs.for_action`` adds to the ledger cost of anything consuming one. From
then on the per-account decisions throttle themselves: a field visit that was
worth making on a quiet Tuesday stops being worth making when the vans are
full, and nobody had to write the threshold down.

**Reads the log rather than re-scoring.** The candidate lists were computed at
decision time against the features as they were then. Re-scoring now would
value tomorrow's plan with today's DPD, which is both slower and wrong.

**Off by default at the other end.** The prices are written whatever happens;
whether they reach the cost term is ``TREATMENT_DUAL_PRICING``. An optimiser
over estimates that have not beaten their priors on a holdout makes the same
mistake across the whole book at once, so the write and the read are separate
switches on purpose — solve first, look at the numbers, then decide.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env_loader import load_env

load_env()

import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from agent_core.treatment import allocate, config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("solve_capacity")

# The report is denominated in rupees and a Windows console defaults to cp1252,
# which cannot encode ₹ and raises rather than degrading. A capacity report that
# dies on its own currency symbol is not a report.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover - non-reconfigurable
        pass


def demands(conn: Any, *, since_hours: int, modes: list[str]) -> list[allocate.Demand]:
    """One entry per account, from the most recent decision the engine made.

    The latest decision only. Two decisions for one account are two answers to
    the same question at different times, and counting both would double that
    account's demand for every resource it wanted.
    """
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT ON (COALESCE(account_id, customer_id))
                   COALESCE(account_id, customer_id) AS key, candidates
            FROM treatment_decisions
            WHERE mode = ANY(:modes)
              AND created_at >= now() - make_interval(hours => :hours)
            ORDER BY COALESCE(account_id, customer_id), created_at DESC
            """
        ),
        {"modes": modes, "hours": since_hours},
    ).mappings().all()

    out: list[allocate.Demand] = []
    for row in rows:
        entries = row["candidates"]
        if not isinstance(entries, list):
            continue
        values = {
            str(e["action"]): float(e.get("expectedValue") or 0.0)
            for e in entries
            if isinstance(e, dict) and e.get("action") and e["action"] != "wait"
        }
        if values:
            out.append(allocate.Demand(account_id=str(row["key"]), values=values))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since-hours", type=int, default=36)
    ap.add_argument("--dry-run", action="store_true", help="solve and print, write nothing")
    ap.add_argument("--include-simulated", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    modes = ["shadow", "live"] + (["simulated"] if args.include_simulated else [])
    capacity = allocate.capacity_plan()
    if not capacity:
        logger.warning(
            "no TREATMENT_CAPACITY_* set, so nothing is scarce and every price "
            "will be zero. That is a valid answer and probably not the one you "
            "wanted — the numbers belong to whoever owns the floor roster."
        )

    with db.engine.connect() as conn:
        book = demands(conn, since_hours=args.since_hours, modes=modes)

    if not book:
        logger.error(
            "no decisions in the last %sh to allocate. Run the sweep first.",
            args.since_hours,
        )
        return 1

    # Tomorrow, because that is what is being planned. A solve at 23:50 that
    # priced today would be pricing a day nobody can act on any more.
    plan_date = (datetime.now(timezone.utc) + timedelta(days=1)).date()
    allocation = allocate.solve(
        book,
        capacity,
        plan_date=plan_date,
        floor=config.policy().min_expected_value,
    )

    if args.json:
        print(json.dumps(allocation.to_log(), indent=2))
    else:
        print(f"\n{allocation.accounts} accounts, plan for {allocation.plan_date}")
        for resource in allocate.RESOURCES:
            limit = allocation.capacity.get(resource)
            used = allocation.demand.get(resource, 0.0)
            price = allocation.prices.get(resource, 0.0)
            state = (
                "unconstrained"
                if not limit
                else f"{used:,.0f}/{limit:,.0f}"
                + ("  BINDING" if price > 0 else "")
            )
            print(f"  {resource:<24} {state:<24} ₹{price:,.2f} per unit")
        print("\n  action mix at these prices:")
        for action, n in sorted(allocation.mix.items(), key=lambda kv: -kv[1]):
            print(f"    {action:<22} {n:,}")
        if not allocation.converged:
            print(
                "\n  DID NOT CONVERGE — a resource is still oversubscribed at the"
                "\n  price ceiling, which means it is undersized rather than merely"
                "\n  scarce. The prices below it are not meaningful."
            )
        if not allocate.enabled():
            print(
                "\n  TREATMENT_DUAL_PRICING is off, so these prices are recorded"
                "\n  and ignored. Turn it on only once the estimators have beaten"
                "\n  their priors on a holdout: an optimiser amplifies estimator"
                "\n  error, it does not correct it."
            )

    if args.dry_run:
        return 0

    with db.engine.begin() as conn:
        allocate.persist(conn, allocation, tenant_id=db.current_tenant())
    allocate.reset_cache()
    logger.info("wrote %s dual prices for %s", len(allocate.RESOURCES), plan_date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
