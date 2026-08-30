#!/usr/bin/env python
"""Promote a challenger to champion, or find out why not. §15's gate, operated.

    .venv/Scripts/python scripts/promote_model.py --list
    .venv/Scripts/python scripts/promote_model.py --verify
    .venv/Scripts/python scripts/promote_model.py --target uplift --check
    .venv/Scripts/python scripts/promote_model.py --target uplift \\
        --artifact models/candidates/treatment_uplift_202608.json \\
        --evaluation report.json --by susanth.p --reason "SNIPS +0.031, ESS 62%"

The last step of the learning loop, and until now the one that was a person
copying a file. Everything before it existed — the corpus, the trainers, the
off-policy estimators — and the decision at the end left no trace, which meant
"why is this model deciding whether to call people?" had no answer a compliance
committee could read.

**Refusal is the default and every rule is a reason to say no.** There is no
positive test. A challenger is promoted when nothing objects, because the cost
of not promoting a good model is some foregone lift and the cost of promoting a
bad one is a book's worth of decisions made confidently wrong.

**--check is the same gate without the transaction.** Run it in CI, run it
before asking anyone to approve anything, and read the objections rather than
looking for a pass. The objections are more useful than the verdict: "control
arm holds 312 observations" tells you what to do next, and "refused" does not.

**--evaluation takes the JSON from evaluate_policy.py.** Promotion without one
is refused outright — an artifact with good training metrics and no holdout is
precisely the thing the gate exists to stop, and it is also the easiest thing in
the world to produce by accident.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env_loader import load_env

load_env()

import db  # noqa: E402

from agent_core.treatment import registry  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("promote_model")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover
        pass


def _load_evaluation(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("--evaluation must be a JSON object")
    # evaluate_policy's --json report is the expected input, and it carries a
    # ``promotion`` block holding the best challenger's SNIPS estimate plus the
    # measured ATE. A bare estimate object is accepted too, so a report produced
    # some other way is not rejected for its shape.
    if isinstance(raw.get("promotion"), dict):
        return raw["promotion"]
    if "lift" in raw:
        return raw
    raise SystemExit(
        "--evaluation has neither a 'promotion' block nor a top-level 'lift'. "
        "Produce it with: scripts/evaluate_policy.py --json > report.json"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", choices=registry.TARGETS)
    ap.add_argument("--artifact", help="path to the challenger artifact")
    ap.add_argument("--evaluation", help="path to the evaluate_policy JSON report")
    ap.add_argument("--by", default="", help="who is promoting this, for the ledger")
    ap.add_argument("--reason", default="", help="one line, for the ledger")
    ap.add_argument("--check", action="store_true", help="run the gate, change nothing")
    ap.add_argument("--register", action="store_true", help="record as challenger only")
    ap.add_argument("--list", action="store_true", help="show the ledger")
    ap.add_argument("--verify", action="store_true", help="does serving match promoted?")
    ap.add_argument(
        "--allow-simulated",
        action="store_true",
        help=(
            "promote a model fitted on the synthetic book. Only ever correct for "
            "exercising this pipeline; it puts a model of a book that does not "
            "exist in front of borrowers who do."
        ),
    )
    args = ap.parse_args()

    tenant = db.current_tenant()

    if args.list or args.verify:
        with db.engine.connect() as conn:
            if args.verify:
                for row in registry.verify(conn, tenant_id=tenant):
                    mark = {"ok": "  ", "drifted": "!!", "missing": "!!"}.get(row["state"], "??")
                    print(f"{mark} {row['target']:<8} {row['state']:<13} {row['detail']}")
                return 0
            rows = registry.history(conn, tenant_id=tenant, target=args.target)
            if not rows:
                print("nothing registered — the EV priors are answering every decision")
                return 0
            for r in rows:
                print(
                    f"{r['status']:<11} {r['target']:<8} {r['version']:<14}"
                    f" n={r['n_samples']:<7} control={r['control_n']:<7}"
                    f" segments={r['segments_promoted']:<3} {r['corpus']:<10}"
                    f" {r['reason'] or ''}"
                )
            return 0

    if not args.target or not args.artifact:
        ap.error("--target and --artifact are required unless --list/--verify")

    evaluation = _load_evaluation(args.evaluation)

    if args.check:
        with db.engine.connect() as conn:
            objections = registry.check(
                conn,
                tenant_id=tenant,
                target=args.target,
                path=args.artifact,
                evaluation=evaluation,
                allow_simulated=args.allow_simulated,
            )
        if not objections:
            print(f"PASS — {args.artifact} may be promoted as {args.target} champion")
            return 0
        print(f"REFUSED — {len(objections)} objection(s):")
        for o in objections:
            print(f"  - {o}")
        return 1

    if args.register:
        with db.engine.begin() as conn:
            out = registry.register(
                conn,
                tenant_id=tenant,
                target=args.target,
                path=args.artifact,
                evaluation=evaluation,
            )
        print(f"registered challenger {out['target']} {out['version']} ({out['sha'][:12]})")
        return 0

    if not args.by:
        ap.error("--by is required to promote: the ledger records who decided")

    try:
        with db.engine.begin() as conn:
            out = registry.promote(
                conn,
                tenant_id=tenant,
                target=args.target,
                path=args.artifact,
                evaluation=evaluation,
                promoted_by=args.by,
                reason=args.reason,
                allow_simulated=args.allow_simulated,
            )
    except registry.PromotionRefused as exc:
        print("REFUSED")
        for objection in str(exc).split("; "):
            print(f"  - {objection}")
        return 1

    print(
        f"promoted {out['target']} {out['version']} -> {out['servingPath']}"
        + (f" (retired {out['retired']})" if out["retired"] else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
