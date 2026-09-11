#!/usr/bin/env python
"""Copy the legacy offer log into the absorbed one — §15.4, W12.

    python scripts/absorb_offer_decisions.py                  # measures, writes nothing
    python scripts/absorb_offer_decisions.py --apply

`--dry-run` is the default and `--apply` is the flag, deliberately. This is a
backfill, and a backfill measured after it has run is not a measurement.

**Why this is a script and not a line in migration 0121.** The house rule is
that a backfill in a migration must be measured against real data before it is
written; the corollary is that the measurement has to be somewhere a reviewer
can see it. Measured read-only against `collections` on 2026-09-10 the offer log
held **16 rows: 9 live, 7 shadow, all on `logging_contract_version = 1`, none
carrying a propensity, and zero recording a response in the log's entire
history**. Rows like that can never be read by an off-policy estimator and carry
no label — so copying them inside DDL would put permanently unusable rows into
the treatment log in the one place nobody would ever see the count.

The copies keep their original contract version rather than being stamped
current. That is the whole point: W11a's equivalence-class filter excludes
contract-1 rows from OPE, and it must keep excluding these. A backfill that
"fixed" the version would make sixteen rows with no propensity look like sixteen
rows an estimator may divide by.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env_loader import load_env  # noqa: E402

load_env()

import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from agent_core.reco.decisions import DEFERRED_PROMOTIONAL, MIRROR_TRIGGER  # noqa: E402
from agent_core.treatment import schema_ready  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("absorb_offer_decisions")

_MEASURE = """
SELECT count(*)::int                                                   AS rows,
       count(*) FILTER (WHERE mode = 'live')::int                      AS live,
       count(*) FILTER (WHERE mode = 'shadow')::int                    AS shadow,
       count(*) FILTER (WHERE mode = 'simulated')::int                 AS simulated,
       count(response)::int                                            AS responses,
       count(arm_propensity)::int                                      AS propensities,
       count(*) FILTER (WHERE logging_contract_version = 2)::int        AS contract2,
       count(*) FILTER (WHERE chosen_product_id IS NOT NULL)::int      AS with_product
FROM offer_decisions
"""

# `id` is shared by construction -- the mirror writes the same `OD-...` -- so
# ON CONFLICT DO NOTHING makes a second run a no-op rather than a duplicate, and
# makes this safe to run after the dual write has already been live for a while.
_COPY = f"""
INSERT INTO treatment_decisions (
  id, tenant_id, customer_id, interaction_id, trigger_kind, trigger_ref, mode,
  variant, recommender, recommender_version, feature_schema_version,
  features, candidates, excluded, action_family, chosen_action, chosen_channel,
  product_id, suggested_amount, offer_response, responded_at, lead_id,
  presented, presented_at, propensity, arm_propensity, action_propensity,
  replay_nonce, veto_stack_version, engine_image_digest, config_version,
  lambda_bucket, logging_contract_version, suppression_reason, latency_ms,
  created_at
)
SELECT o.id, o.tenant_id, o.customer_id, o.interaction_id,
       '{MIRROR_TRIGGER}', o.interaction_id, o.mode,
       o.variant, o.recommender, o.recommender_version, o.feature_schema_version,
       o.features, o.candidates, o.excluded, 'offer',
       CASE WHEN o.chosen_product_id IS NOT NULL THEN 'offer' ELSE 'wait' END,
       CASE WHEN o.chosen_product_id IS NOT NULL
            THEN '{DEFERRED_PROMOTIONAL}' ELSE NULL END,
       o.chosen_product_id, o.suggested_amount, o.response, o.responded_at,
       o.lead_id, o.presented, o.presented_at,
       o.action_propensity, o.arm_propensity, o.action_propensity,
       o.replay_nonce, o.veto_stack_version, o.engine_image_digest,
       o.config_version, o.lambda_bucket,
       -- Kept as logged, never stamped current. See the module docstring.
       o.logging_contract_version,
       o.suppression_reason, o.latency_ms, o.created_at
FROM offer_decisions o
ON CONFLICT (id) DO NOTHING
RETURNING id
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--apply",
        action="store_true",
        help="write the copies. Without it this measures and writes nothing.",
    )
    args = ap.parse_args()

    with db.engine.begin() as conn:
        if not schema_ready.w12_ready(conn):
            print(
                "REFUSED: `treatment_decisions.action_family` is absent on this "
                "database. Apply sql/32_offer_absorption.sql (migration 0121) first."
            )
            return 2
        counts = dict(conn.execute(text(_MEASURE)).mappings().first() or {})
        already = conn.execute(
            text(
                "SELECT count(*)::int FROM treatment_decisions"
                " WHERE action_family = 'offer'"
            )
        ).scalar()

        print(f"offer_decisions rows          {counts.get('rows', 0)}")
        print(
            f"  by mode                     live={counts.get('live', 0)} "
            f"shadow={counts.get('shadow', 0)} simulated={counts.get('simulated', 0)}"
        )
        print(f"  carrying a response         {counts.get('responses', 0)}")
        print(f"  carrying a propensity       {counts.get('propensities', 0)}")
        print(f"  on logging contract 2       {counts.get('contract2', 0)}")
        print(f"  naming a product            {counts.get('with_product', 0)}")
        print(f"already in treatment_decisions {already}")

        unusable = int(counts.get("rows", 0)) - int(counts.get("contract2", 0))
        if unusable:
            print(
                f"\n{unusable} of these are on logging contract 1 and stay there. "
                "They carry no separable propensity, so no off-policy estimator "
                "may read them -- W11a's equivalence-class filter excludes them "
                "and this copy does not change that."
            )
        if not counts.get("responses"):
            print(
                f"{counts.get('rows', 0)} decisions and 0 responses: the copy "
                "brings across an unlabelled corpus. What changes that is the "
                "response route and the follow-through sweep, not this script."
            )

        if not args.apply:
            print("\ndry run. Re-run with --apply to write.")
            return 0

        copied = conn.execute(text(_COPY)).scalars().all()
        print(f"\ncopied {len(copied)} rows into treatment_decisions as action_family='offer'")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
