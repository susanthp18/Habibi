#!/usr/bin/env python
"""Solve a sub-book both ways and assert the cheap one got the same answer.

    .venv/Scripts/python scripts/allocator_gold_standard.py
    .venv/Scripts/python scripts/allocator_gold_standard.py --json --sample 50000

§10.4's second gate on the allocator write switch, verbatim:

    on a 50k-200k sampled sub-book, solve the monolithic LP with HiGHS IPM
    (≈14 s at 50k) and assert the allocator's objective is within **0.1%** and
    its λ within **1e-3** of the LP duals — **green 10 consecutive nights**

"Green ten consecutive nights" is a count of rows in ``work_runtime_jobs``
rather than a promise, which is why this writes one whether it passes or fails.

**This is a reference, not a fallback.** The monolithic formulation is eighteen
million columns at book scale, and §10.1 measured dual simplex failing to finish
in 795 s at two hundred thousand accounts — that is why the Lagrangian allocator
exists. Sampling is what makes the reference affordable.

The two failure modes worth knowing apart, because they are printed differently:
an objective that disagrees means the repair lost money the LP did not, and a λ
that disagrees means the dual loop stopped while the price was still moving.
Only the second one changes who gets contacted.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env_loader import load_env

load_env()

import db  # noqa: E402
import wk_batch  # noqa: E402

from agent_core.treatment import allocate, allocator_jobs  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("allocator_gold_standard")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since-hours", type=int, default=allocator_jobs.DEFAULT_SINCE_HOURS)
    ap.add_argument("--sample", type=int, default=allocate.GOLD_SAMPLE)
    ap.add_argument("--include-simulated", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--no-record",
        action="store_true",
        help="print the comparison without writing a job row — so a dry run "
        "cannot advance the ten-night count",
    )
    args = ap.parse_args()

    tenant = db.current_tenant()
    day = datetime.now(timezone.utc).date().isoformat()
    payload = {
        "since_hours": args.since_hours,
        "include_simulated": "1" if args.include_simulated else "0",
        "sample": args.sample,
    }

    if args.no_record:
        with db.engine.connect() as conn:
            report = allocator_jobs.gold_standard(
                conn,
                tenant_id=tenant,
                since_hours=args.since_hours,
                modes=["shadow", "live"]
                + (["simulated"] if args.include_simulated else []),
                sample=args.sample,
            )
        status = "not recorded"
    else:
        outcome = wk_batch.run_now(
            db.engine,
            job_type=wk_batch.ALLOCATOR_GOLD,
            payload=payload,
            idempotency_key=f"{wk_batch.ALLOCATOR_GOLD}:{tenant}:{day}",
        )
        report = outcome.get("result") or {"evaluable": False, "reason": outcome.get("error")}
        status = outcome["status"]

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0 if report.get("agrees") else 1

    if not report.get("evaluable"):
        print(f"\n  NOT EVALUABLE — {report.get('reason')}")
        print(
            "  §8.12 makes an unevaluable gate a refusal, so this counts as a"
            "\n  night that was not green rather than as a night that passed."
        )
        return 1

    print(
        f"\n  {report['accounts']:,} accounts × {report['actions']} actions"
        f" = {report['variables']:,} LP columns"
    )
    print(
        f"  objective   LP ₹{report['lpObjective']:,.2f}"
        f"   allocator ₹{report['allocatorObjective']:,.2f}"
        f"   error {report['objectiveError']:.4%}"
        f"  (ceiling {report['objectiveTolerance']:.1%})"
    )
    print("  prices:")
    for resource, lp in report["lpPrices"].items():
        ours = report["allocatorPrices"].get(resource, 0.0)
        err = report["priceError"].get(resource, 0.0)
        flag = "  OUT" if err > report["priceTolerance"] else ""
        print(f"    {resource:<24} LP ₹{lp:<12,.6f} ours ₹{ours:<12,.6f} Δ {err:.2e}{flag}")
    print(
        f"\n  {'AGREES' if report['agrees'] else 'DISAGREES'}"
        f"   (job row: {status})"
    )
    return 0 if report.get("agrees") else 1


if __name__ == "__main__":
    raise SystemExit(main())
