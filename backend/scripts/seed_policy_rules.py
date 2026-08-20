#!/usr/bin/env python
"""Publish the statutory rule sets the contact gate resolves against.

    .venv/Scripts/python scripts/seed_policy_rules.py
    .venv/Scripts/python scripts/seed_policy_rules.py --show

Until these rows exist, ``policy_rules.resolve`` returns ``EMPTY``, every caller
falls back to the module constants it used before the table existed, and
``treatment_decisions.policy_version`` is NULL. That is a correct and safe
state — it is what makes the resolver deployable ahead of its data — but it is
not the state the design is for, because a NULL version cannot answer *"under
which rules?"*.

Two sets are published, not one, and that is the whole point of the exercise:

* **v1**, in force from the beginning of the corpus. What the code did before
  rules were data — an 08:00–19:00 voice window and the operational caps.
* **v2**, effective 2027-01-01, carrying the tightened obligations of the
  amendment described in the design note (RBI/2026-27/230): the calling window
  applied without a general-recovery exception, six-month recording retention,
  and prior intimation before a field visit.

With both rows present, a decision made in 2026 stamps ``policy_version=1`` and
one made in 2027 stamps 2 — from the same code, with no deploy in between. That
is the property the whole table exists for: a rule change becomes a backfill
rather than a fresh start, and "why did you dial at 19:15 last March?" has an
answer that is not "our current code says we wouldn't have".

**The dates and obligations in v2 come from the design note, not from this
script's own reading of the circular.** They are seed data, and a deployment
should have compliance confirm them against the gazetted text before relying on
them — which is exactly why they are rows a lawyer can read rather than
constants in a scorer.

**Only what genuinely binds from outside is published here.** The daily and
weekly contact caps and the cooling-off period are deliberately absent: they are
operational settings this platform chose, not obligations a regulator imposed,
and they stay in the environment where an operator can raise them. Seeding them
as statutory would have been worse than untidy — a published rule is a *ceiling*
in ``contact_policy``, so a fabricated statutory cap of 3 would have silently
clamped every deployment that set ``CONTACT_DAILY_CAP`` higher, and the operator
would have had no way to see why. A rule set is a claim about the law; nothing
belongs in one that could not be defended to the regulator who wrote it.

Idempotent: re-running updates the rules in place rather than publishing a third
set. Never destructive — it does not touch rule sets it did not create.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env_loader import load_env

load_env()

import db  # noqa: E402
import policy_rules  # noqa: E402
from sqlalchemy import text  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed_policy_rules")

# Stable ids so re-running updates rather than duplicates. A UUID here would
# make the script publish a fresh overlapping set on every run, and the
# resolver's "latest effective_from wins" tie-break would hide it.
V1_ID = "PRS-STATUTORY-V1"
V2_ID = "PRS-STATUTORY-V2"

V1_FROM = datetime(2020, 1, 1, tzinfo=timezone.utc)
V2_FROM = datetime(2027, 1, 1, tzinfo=timezone.utc)

RULE_SETS: list[dict[str, Any]] = [
    {
        "id": V1_ID,
        "version": 1,
        "label": "RBI DOR.ORG.REC.65/21.04.158/2022-23 (outsourcing of recovery)",
        "effective_from": V1_FROM,
        "effective_to": V2_FROM,
        "notes": (
            "The rules this codebase implemented as module constants before "
            "policy became data. Published so decisions made under them can say so."
        ),
        "rules": [
            # Voice only. Digital is bound by the borrower's consented window
            # rather than by a statutory one, which is why there is no
            # calling_window row for sms or whatsapp — and why the absence has
            # to be deliberate: a row saying 00:00-24:00 and no row at all mean
            # the same thing to the resolver but very different things to a
            # reader.
            ("calling_window", "voice", {"startHour": 8, "endHour": 19}),
            (
                "mandate_return_action",
                None,
                {
                    "byReason": {
                        "insufficient_funds": "allow",
                        "technical": "allow",
                        "unknown": "allow",
                        "mandate_expired": "veto",
                        "account_closed": "veto",
                    }
                },
            ),
        ],
    },
    {
        "id": V2_ID,
        "version": 2,
        "label": "RBI/2026-27/230 DOR.MCS.REC.No.199/01-01-039/2026-27",
        "effective_from": V2_FROM,
        "effective_to": None,
        "notes": (
            "Amendment to the RBI (NBFC - Responsible Business Conduct) Directions, "
            "2025, as described in decision-intelligence-engine.md. Seed data - "
            "confirm against the gazetted text before relying on it in production."
        ),
        "rules": [
            # The window itself is unchanged in hours. What changes is that it
            # no longer carries a general-recovery exception, so it now binds
            # every outbound voice contact rather than most of them. The
            # resolver cannot express "no exception" as anything but the window
            # applying, which is precisely what it now does.
            ("calling_window", "voice", {"startHour": 8, "endHour": 19}),
            ("recording_retention", None, {"months": 6}),
            ("visit_intimation", None, {"hours": 24}),
            (
                "mandate_return_action",
                None,
                {
                    "byReason": {
                        "insufficient_funds": "allow",
                        "technical": "allow",
                        "unknown": "allow",
                        "mandate_expired": "veto",
                        "account_closed": "veto",
                    }
                },
            ),
        ],
    },
]


def publish(conn: Any) -> None:
    for spec in RULE_SETS:
        conn.execute(
            text(
                """
                INSERT INTO policy_rule_sets (
                  id, tenant_id, scope, product_id, version, label,
                  effective_from, effective_to, notes
                ) VALUES (
                  :id, NULL, 'statutory', NULL, :version, :label,
                  :effective_from, :effective_to, :notes
                )
                ON CONFLICT (id) DO UPDATE SET
                  version = EXCLUDED.version,
                  label = EXCLUDED.label,
                  effective_from = EXCLUDED.effective_from,
                  effective_to = EXCLUDED.effective_to,
                  notes = EXCLUDED.notes,
                  updated_at = now()
                """
            ),
            {
                "id": spec["id"],
                "version": spec["version"],
                "label": spec["label"],
                "effective_from": spec["effective_from"],
                "effective_to": spec["effective_to"],
                "notes": spec["notes"],
            },
        )
        for kind, channel, params in spec["rules"]:
            conn.execute(
                text(
                    """
                    INSERT INTO policy_rules (id, rule_set_id, kind, channel, params)
                    VALUES (:id, :set_id, :kind, :channel, CAST(:params AS jsonb))
                    ON CONFLICT (rule_set_id, kind, COALESCE(channel,'')) DO UPDATE
                      SET params = EXCLUDED.params, updated_at = now()
                    """
                ),
                {
                    "id": f"{spec['id']}-{kind}-{channel or 'all'}",
                    "set_id": spec["id"],
                    "kind": kind,
                    "channel": channel,
                    "params": json.dumps(params),
                },
            )
        logger.info("published %s v%s (%s)", spec["id"], spec["version"], spec["label"])


def show(conn: Any) -> None:
    """Resolve at two instants and print what each one sees."""
    for label, at in (
        ("today", datetime.now(timezone.utc)),
        ("2027-06-01", datetime(2027, 6, 1, tzinfo=timezone.utc)),
    ):
        policy_rules.reset_cache()
        resolved = policy_rules.resolve(conn, tenant_id=db.current_tenant(), at=at)
        logger.info(
            "%s -> version=%s window(voice)=%s daily_cap=%s retention=%s",
            label,
            resolved.version,
            resolved.calling_window("voice"),
            resolved.daily_cap(),
            resolved.recording_retention_months(),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--show",
        action="store_true",
        help="resolve and print instead of publishing",
    )
    args = parser.parse_args()

    if args.show:
        with db.engine.connect() as conn:
            show(conn)
        return

    with db.engine.begin() as conn:
        publish(conn)
    policy_rules.reset_cache()
    with db.engine.connect() as conn:
        show(conn)


if __name__ == "__main__":
    main()
