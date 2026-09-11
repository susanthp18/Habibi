#!/usr/bin/env python
"""Solve tomorrow's book against tomorrow's capacity, and price what is scarce.

    .venv/Scripts/python scripts/solve_capacity.py --dry-run
    .venv/Scripts/python scripts/solve_capacity.py
    .venv/Scripts/python scripts/solve_capacity.py --json --include-simulated

Reads the demand curve the engine has already computed — every decision row
carries the full ranked candidate list with an expected value per action — and
finds the prices at which the book's demand for agent minutes, field slots and
bot concurrency meets what the floor actually has.

The output that matters is not the plan. It is a handful of numbers of the form
"an agent-minute is worth ₹17.50 today", written to ``capacity_duals``, which
``costs.for_action`` adds to the ledger cost of anything consuming one.

**Capacity comes from the C9 feed where there is one.** ``bank_capacity``,
landed by W5 and read by nothing until W13; ``TREATMENT_CAPACITY_*`` survives as
§10.2's documented fallback and the source is recorded on every row, because "we
have sixty field slots" and "nobody told us, so we assumed sixty" are different
claims.

**Reads the log rather than re-scoring.** The candidate lists were computed at
decision time against the features as they were then. Re-scoring now would value
tomorrow's plan with today's DPD, which is both slower and wrong.

**Off by default at the other end.** The prices are written whatever happens;
whether they reach the cost term is §10.4's six gates, which
``--gates`` prints. An optimiser over estimates that have not beaten their
priors on a holdout makes the same mistake across the whole book at once, so the
write and the read are separate switches on purpose — solve first, look at the
numbers, then measure the gates.

This is the same code path the ``w13.capacity_solve`` batch job runs; the script
exists so a human can run it and read the answer, not as a second implementation.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env_loader import load_env

load_env()

import db  # noqa: E402

from agent_core.treatment import allocate, allocator_jobs  # noqa: E402

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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since-hours", type=int, default=allocator_jobs.DEFAULT_SINCE_HOURS)
    ap.add_argument("--dry-run", action="store_true", help="solve and print, write nothing")
    ap.add_argument("--include-simulated", action="store_true")
    ap.add_argument("--gates", action="store_true", help="print §10.4's write-switch gates and stop")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    tenant = db.current_tenant()

    if args.gates:
        with db.engine.connect() as conn:
            objections = allocate.write_switch_objections(conn, tenant_id=tenant)
            resources = allocate.resource_report(conn, tenant_id=tenant)
        payload = {"objections": objections, "resources": resources}
        if args.json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            print("\n§10.4 gates on the allocator write switch:")
            if objections:
                for objection in objections:
                    print(f"  REFUSED  {objection}")
                print(
                    "\n  The prices are still solved, persisted and published."
                    "\n  Nothing consumes them while any line above stands."
                )
            else:
                print("  all six clear — dual pricing may be switched on")
            print("\n  resources this tree declines to price:")
            for resource, reason in resources["refused"].items():
                print(f"    {resource:<26} {reason}")
            budget = resources.get("returnBudget") or {}
            if budget.get("evaluable"):
                print(
                    f"\n  NACH return ratio: {budget['ratio']:.1%} "
                    f"({budget['returned']} returned / "
                    f"{budget['returned'] + budget['confirmed']} presented, "
                    f"{budget['excludedRejects']} rejects excluded)"
                )
            else:
                print(f"\n  NACH return ratio: not evaluable ({budget.get('reason')})")
        return 0

    modes = ["shadow", "live"] + (["simulated"] if args.include_simulated else [])
    plan_date = (datetime.now(timezone.utc) + timedelta(days=1)).date()

    # A solve writes one row per resource and nothing else, so it runs in one
    # transaction. `begin()` rather than `connect()` even for --dry-run: the
    # capacity read and the demand read must see the same snapshot.
    with db.engine.begin() as conn:
        result = allocator_jobs.solve_book(
            conn,
            tenant_id=tenant,
            plan_date=plan_date,
            since_hours=args.since_hours,
            modes=modes,
            persist=not args.dry_run,
        )

    census = result["census"]
    allocation = result["allocation"]
    if not census["book"]:
        logger.error(
            "no unsuppressed decisions in the last %sh to allocate (%s accounts "
            "seen, %s suppressed). Run the sweep first.",
            args.since_hours,
            census["accounts"],
            census["suppressed"],
        )
        return 1

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0

    print(
        f"\n{census['book']} accounts, plan for {allocation['planDate']}"
        f"  ({census['suppressed']} suppressed and excluded,"
        f" {census['noCandidates']} with nothing to offer)"
    )
    for resource in allocate.RESOURCES:
        limit = allocation["capacity"].get(resource)
        source = allocation["capacitySource"].get(resource, "unset")
        used = allocation["demand"].get(resource, 0.0)
        price = allocation["prices"].get(resource, 0.0)
        if limit is None:
            state = "unconfigured"
        else:
            state = f"{used:,.0f}/{limit:,.0f}" + ("  BINDING" if price > 0 else "")
        print(f"  {resource:<24} {state:<24} ₹{price:,.2f} per unit  [{source}]")

    print("\n  action mix at these prices:")
    for action, n in sorted(allocation["mix"].items(), key=lambda kv: -kv[1]):
        print(f"    {action:<22} {n:,}")

    print(
        f"\n  dual bound ₹{allocation['dualBound']:,.2f}"
        f"  primal ₹{allocation['primalValue']:,.2f}"
        f"  gap {allocation['dualityGap']:.3%}"
        f"  in {allocation['iterations']} iterations"
    )

    if allocation["refusals"]:
        print(
            "\n  REFUSED — " + ", ".join(allocation["refusals"]) + "."
            "\n  Nothing was written. Yesterday's prices stand, which is the"
            "\n  degradation §10.1 asks for by name rather than a price the"
            "\n  solver itself does not believe."
        )
    elif not args.dry_run:
        written = result.get("persisted", {})
        print(
            f"\n  wrote {written.get('written', 0)} prices, damped at "
            f"α = {written.get('damping')} against the previous solve"
        )

    if not allocate.enabled():
        print(
            "\n  Dual pricing is gated OFF, so these prices are recorded and"
            "\n  ignored. Run with --gates to see which of §10.4's six gates"
            "\n  are refusing."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
