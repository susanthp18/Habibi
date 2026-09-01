#!/usr/bin/env python
"""Take the QA leftovers off the Agent Studio roster.

    .venv/Scripts/python scripts/prune_probe_cards.py            # report only
    .venv/Scripts/python scripts/prune_probe_cards.py --apply    # do it

Nine cards render on the fleet index and five are the product. The other four
were minted at runtime by ``POST /agent-studio/cards/clone`` during QA and E2E
runs -- ``clone.py`` builds the id as ``f"{slug}-{uuid4().hex[:6]}"``, which is
where the six-hex suffixes come from -- and they appear in no seed file, no
fixture and no migration. A fresh database has never had them. Only this one
does, and it is the one being demonstrated.

Two more are seeded: ``collectionsbot-v2-4`` and ``webchatbot``. They are not
deleted, here or in the seed. They are ``bots`` rows with no prompt version and
no deployment, and they exist to own history: 98 seeded rows across
interactions, interaction_participants, violations, qa_scorecards, promises and
activity_events name one of them as the handler, and ``db.bot_analytics``
groups its per-card table on ``handler_bot_id``. Deleting them would empty two
of the three rows on the Bot analytics page to tidy a different page. They are
archived instead, which is what they are: retired scaffolds that took no
traffic.

**audit_log is never touched.** ``entity_id`` carries no foreign key, so the
two ``agent.archive`` entries for the probe cards survive the delete and go on
naming a bot that no longer exists. That is correct for an audit log -- it
records what happened, not what still exists -- and the alternative is worse:
the entries are hash-chained, so removing them would break the chain and light
up ``audit chain broken`` on the very page this is meant to clean.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

import db  # noqa: E402

#: Runtime clone residue. Every one of these was created by an API call during
#: a test run; none is reproducible from the repo.
PRUNE = (
    "sweep-probe-001-f562be",
    "qa-probe-clone-fd7ebd",
    "e2e-audit-card-8216c4",
    "clerk-2ccb9c",
)

#: Seeded scaffolds. Retired, not removed -- see the module docstring.
RETIRE = (
    "collectionsbot-v2-4",
    "webchatbot",
)

#: Deleting one of these would take a working card off the roster. The script
#: refuses rather than trusting the list above to stay right: PRUNE is edited
#: by hand, and the cost of a typo is a published agent.
PROTECTED = frozenset({"kaia-v2-4", "intake-v1", "insurance-v1", "supervisor-brief"})


def _counts(conn, bot_id: str) -> dict[str, int]:
    """Every row that would go with the card, so --apply is not a surprise."""
    out: dict[str, int] = {}
    for label, sql in (
        ("prompt_versions", "SELECT count(*) AS n FROM prompt_versions WHERE bot_id = :b"),
        ("bot_deployments", "SELECT count(*) AS n FROM bot_deployments WHERE bot_id = :b"),
        (
            "skill_attachments",
            """SELECT count(*) AS n FROM skill_attachments sa
                 JOIN prompt_versions pv ON pv.id = sa.prompt_version_id
                WHERE pv.bot_id = :b""",
        ),
        (
            "deployment_experiments",
            "SELECT count(*) AS n FROM deployment_experiments WHERE bot_id = :b",
        ),
        ("eval_reports", "SELECT count(*) AS n FROM eval_reports WHERE bot_id = :b"),
        ("interactions", "SELECT count(*) AS n FROM interactions WHERE handler_bot_id = :b"),
        ("audit_log", "SELECT count(*) AS n FROM audit_log WHERE entity_type='bot' AND entity_id = :b"),
    ):
        out[label] = int(db._one(conn.execute(text(sql), {"b": bot_id}))["n"])
    return out


def _delete_card(conn, bot_id: str) -> None:
    """Children first: ``prompt_versions.bot_id`` has no ON DELETE, so the
    ``bots`` row cannot go until nothing references it."""
    conn.execute(
        text(
            """DELETE FROM skill_attachments
                WHERE prompt_version_id IN (SELECT id FROM prompt_versions WHERE bot_id = :b)"""
        ),
        {"b": bot_id},
    )
    # Order is forced by the foreign keys: experiments point at deployments,
    # deployments at a prompt_version and at an eval_report, and
    # skill_attachments at a prompt_version. Nothing may outlive what it names.
    conn.execute(text("DELETE FROM deployment_experiments WHERE bot_id = :b"), {"b": bot_id})
    conn.execute(text("DELETE FROM bot_deployments WHERE bot_id = :b"), {"b": bot_id})
    conn.execute(text("DELETE FROM eval_reports WHERE bot_id = :b"), {"b": bot_id})
    conn.execute(text("DELETE FROM prompt_versions WHERE bot_id = :b"), {"b": bot_id})
    conn.execute(text("DELETE FROM bots WHERE id = :b"), {"b": bot_id})


def run(apply: bool) -> int:
    with db.engine.connect() as conn:
        present = {
            r["id"]: r
            for r in db._rows(
                conn.execute(
                    text("SELECT id, name, archived_at FROM bots WHERE id = ANY(:ids)"),
                    {"ids": list(PRUNE + RETIRE)},
                )
            )
        }
        plan: list[tuple[str, dict[str, int]]] = []
        for bot_id in PRUNE:
            if bot_id in PROTECTED:
                print(f"REFUSED  {bot_id} is a first-party card")
                return 2
            if bot_id not in present:
                print(f"absent   {bot_id} (already gone)")
                continue
            counts = _counts(conn, bot_id)
            plan.append((bot_id, counts))
            print(
                f"delete   {bot_id:24} "
                + " ".join(f"{k}={v}" for k, v in counts.items() if v or k == "audit_log")
            )
            if counts["interactions"]:
                # A card that handled a real conversation is not residue,
                # whatever its name suggests. Nothing else here is a refusal:
                # eval reports and experiments describe the card itself and
                # mean nothing once it is gone, and the FK to `bots` would
                # block the delete if they were left behind anyway. Only
                # customer-facing history earns a stop.
                print(f"REFUSED  {bot_id} handled {counts['interactions']} interaction(s)")
                return 2

        retire: list[str] = []
        for bot_id in RETIRE:
            row = present.get(bot_id)
            if row is None:
                print(f"absent   {bot_id}")
            elif row["archived_at"]:
                print(f"already  {bot_id} archived {row['archived_at']}")
            else:
                retire.append(bot_id)
                print(f"archive  {bot_id:24} interactions={_counts(conn, bot_id)['interactions']}")

    if not apply:
        print("\n(report only — pass --apply to write)")
        return 0

    with db.engine.begin() as conn:
        for bot_id, _ in plan:
            _delete_card(conn, bot_id)
        if retire:
            conn.execute(
                text(
                    """UPDATE bots SET archived_at = now(), updated_at = now()
                        WHERE id = ANY(:ids) AND archived_at IS NULL"""
                ),
                {"ids": retire},
            )
    print(f"\napplied: {len(plan)} deleted, {len(retire)} archived")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the changes")
    return run(ap.parse_args().apply)


if __name__ == "__main__":
    raise SystemExit(main())
