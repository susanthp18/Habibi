#!/usr/bin/env python
"""File and sign a pre-registration — §8.12 gates 14 and 15.

    # BEFORE the challenger runs:
    python scripts/pre_register.py file --target uplift \
        --endpoint "cure within the primary horizon" --horizon-days 90 \
        --estimator "delta-OPE, empirical-Bernstein CS lower bound" \
        --threshold 0.0 --threshold-basis "0.05 x measured per-borrower recovery SD" \
        --family-size 12 --alpha-spending "none; the CS is anytime-valid" \
        --stopping-rule "promote at the first look whose lower bound clears the margin" \
        --author alice

    # THEN the evaluation, naming it:
    python scripts/evaluate_policy.py --pre-registration TPR-... --artifact models/x.json

    # AFTER, by somebody who is not the author:
    python scripts/pre_register.py sign --id TPR-... --validator bob --note "..."

    python scripts/pre_register.py list --target uplift

The ordering is the gate. A pre-registration filed after the evaluation ran is
refused, and the comparison is against a ``computed_at`` sealed under
``TREATMENT_EVALUATION_KEY`` — so backdating the evaluation breaks Gate 2 before
it reaches Gate 14. There is no flag here that relaxes that: §8.12's own words
are that "a gate with a documented bypass is worse than no gate, because it will
be cited as evidence that the property was tested."
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env_loader import load_env

load_env()

import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from agent_core.treatment import prereg, registry, schema_ready  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("pre_register")


def _print(record: dict) -> None:
    print(json.dumps({k: str(v) for k, v in record.items()}, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    f = sub.add_parser("file", help="file a pre-registration, before the challenger runs")
    f.add_argument("--target", required=True, choices=registry.TARGETS)
    f.add_argument("--endpoint", required=True, help="the primary endpoint, in words")
    f.add_argument("--horizon-days", type=int, required=True)
    f.add_argument("--estimator", required=True)
    f.add_argument("--threshold", type=float, required=True)
    f.add_argument("--threshold-basis", required=True, help="how that number was arrived at")
    f.add_argument("--family-size", type=int, required=True)
    f.add_argument("--alpha-spending", required=True)
    f.add_argument("--stopping-rule", required=True)
    f.add_argument("--author", required=True, help="who built the challenger")

    s = sub.add_parser("sign", help="record gate 15's independent sign-off")
    s.add_argument("--id", required=True)
    s.add_argument("--validator", required=True, help="who did NOT build the challenger")
    s.add_argument("--note", default="")

    ls = sub.add_parser("list", help="what has been filed")
    ls.add_argument("--target", default=None, choices=registry.TARGETS)

    args = ap.parse_args()
    tenant = db.current_tenant()

    with db.engine.begin() as conn:
        if not schema_ready.w11_ready(conn):
            logger.error(
                "`treatment_pre_registrations` is absent on this database. Apply "
                "sql/31_promotion_gate.sql (fresh install) or migration "
                "20260910_0120 — and not against the running database."
            )
            return 1

        if args.command == "file":
            record = prereg.declare(
                conn,
                tenant_id=tenant,
                target=args.target,
                primary_endpoint=args.endpoint,
                horizon_days=args.horizon_days,
                estimator=args.estimator,
                threshold=args.threshold,
                threshold_basis=args.threshold_basis,
                family_size=args.family_size,
                alpha_spending=args.alpha_spending,
                stopping_rule=args.stopping_rule,
                author=args.author,
            )
            # The margin the gate will actually apply, printed now rather than
            # discovered at promotion: a threshold filed below the book's own
            # measured dispersion is a threshold that will be refused, and
            # finding that out here costs nothing.
            margin, basis = registry.value_margin(conn, tenant_id=tenant)
            if margin is None:
                logger.warning("gate 7's margin cannot be measured yet: %s", basis)
            elif args.threshold < margin:
                logger.warning(
                    "filed threshold %.4f is below the measured margin %.4f (%s) — "
                    "the gate applies the larger of the two",
                    args.threshold, margin, basis,
                )
            _print(record)
            return 0

        if args.command == "sign":
            try:
                _print(prereg.sign(
                    conn, pre_registration_id=args.id, validator=args.validator, note=args.note
                ))
            except prereg.PreRegistrationRefused as exc:
                logger.error("%s", exc)
                return 1
            return 0

        rows = conn.execute(
            text(
                """
                SELECT id, target, primary_endpoint, horizon_days, estimator,
                       threshold, family_size, author, validator, validated_at,
                       filed_at
                FROM treatment_pre_registrations
                WHERE tenant_id = :tenant
                  AND (CAST(:target AS TEXT) IS NULL OR target = CAST(:target AS TEXT))
                ORDER BY filed_at DESC
                LIMIT 50
                """
            ),
            {"tenant": tenant, "target": args.target},
        ).mappings().all()
        for row in rows:
            signed = f"signed by {row['validator']}" if row["validator"] else "UNSIGNED"
            print(
                f"{row['id']}  {row['target']:<7} {row['estimator'][:32]:<32} "
                f"thr {float(row['threshold']):+.4f}  family {row['family_size']:<4} "
                f"author {row['author']:<12} {signed}  filed {row['filed_at']}"
            )
        if not rows:
            print("nothing filed — every promotion will be refused by gate 14")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
