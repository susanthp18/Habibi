#!/usr/bin/env python
"""File §10.4's objective-mismatch measurement, with whatever it can say today.

    .venv/Scripts/python scripts/allocator_regret.py
    .venv/Scripts/python scripts/allocator_regret.py --json

§10.4, the sixth gate on the allocator write switch:

    the offline learner should arguably be trained against the **dual-adjusted**
    objective rather than raw EV, or the two halves fight each other. Our stated
    position is that τ is fitted against the outcome and the dual price enters
    the arithmetic outside the model — the auditable arrangement, and the one a
    validator can separate — **but before the write switch is flipped we publish
    the regret of greedy-EV-plus-λ against a dual-adjusted learner on the
    gold-standard sub-book.** If they differ materially, the ordering of the
    estimator and allocator waves is wrong and the plan changes. That is a
    measurement with a date, not an assumption.

Half of that comparison is computable and half is not. Greedy-EV-plus-λ is what
this allocator does. The dual-adjusted learner does not exist — W10 refused to
fit anything for want of labels — so this files ``null`` for that arm with the
label counts behind the refusal, and the gate stays shut.

A filed refusal is a measurement with a date. A filed guess is not, which is why
this does not substitute the response prior for the learner and call the
difference regret: the response prior is not trained against either objective,
so the comparison would be between two things neither of which is the arm §10.4
names.
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

from agent_core.treatment import allocator_jobs  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("allocator_regret")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since-hours", type=int, default=allocator_jobs.DEFAULT_SINCE_HOURS)
    ap.add_argument("--include-simulated", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--no-record",
        action="store_true",
        help="print without filing — the gate counts filed measurements",
    )
    args = ap.parse_args()

    tenant = db.current_tenant()
    day = datetime.now(timezone.utc).date().isoformat()
    payload = {
        "since_hours": args.since_hours,
        "include_simulated": "1" if args.include_simulated else "0",
    }

    if args.no_record:
        with db.engine.connect() as conn:
            report = allocator_jobs.regret(
                conn,
                tenant_id=tenant,
                since_hours=args.since_hours,
                modes=["shadow", "live"]
                + (["simulated"] if args.include_simulated else []),
            )
        status = "not recorded"
    else:
        outcome = wk_batch.run_now(
            db.engine,
            job_type=wk_batch.ALLOCATOR_REGRET,
            payload=payload,
            idempotency_key=f"{wk_batch.ALLOCATOR_REGRET}:{tenant}:{day}",
        )
        report = outcome.get("result") or {}
        status = outcome["status"]
        if status != "completed":
            logger.error("regret job did not complete: %s", outcome.get("error"))
            return 1

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    book = report.get("subBook", {})
    greedy = report.get("greedyEvPlusLambda", {})
    labels = report.get("labels", {})
    print(
        f"\n  sub-book: {book.get('book', 0):,} accounts"
        f"  ({book.get('suppressed', 0)} suppressed,"
        f" {book.get('noCandidates', 0)} with nothing to offer)"
    )
    print(
        f"  greedy EV + λ:  ₹{greedy.get('objectiveInr', 0):,.2f} surplus"
        f"   ₹{greedy.get('grossValueInr', 0):,.2f} gross"
        f"   converged={greedy.get('converged')} feasible={greedy.get('feasible')}"
    )
    print(f"  prices: {greedy.get('prices')}")
    print("\n  dual-adjusted learner:  NONE")
    print(f"  regret:                 NOT MEASURABLE ({report.get('refusedBecause')})")
    if labels.get("evaluable"):
        print(
            f"\n  the panel behind that refusal: {labels.get('cases', 0)} cases,"
            f" {labels.get('customers', 0)} customers,"
            f" {labels.get('mature', 0)} mature,"
            f" {labels.get('reach', 0)} reach labels,"
            f" {labels.get('cure', 0)} cure labels"
        )
    else:
        print(f"\n  the panel behind that refusal: {labels.get('reason')}")
    for objection in report.get("corpusObjections") or []:
        print(f"    {objection}")
    print(
        f"\n  filed ({status}). §10.4's sixth gate is now measured; it is not"
        "\n  cleared, and it cannot be until an estimator is promoted."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
