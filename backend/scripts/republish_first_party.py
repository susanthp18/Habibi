"""Publish the first-party cards' drafts, member before merger, gates and all.

The honest way to move a graph into production: a real publish through
``publish_prompt_version`` -- the compiler runs, a ``bot_deployments`` row is
swapped, the change log records it, the eval reports it reads are the ones
filed against the exact content being shipped. ``test_recompile_published_
bundle.py`` records why a row rewrite is the wrong shortcut.

Order matters: a member is published before the cards whose bundles merge it
(the door merges every specialist it can hand off to), so ``MEMBERS`` in
``seed_member_graphs`` is walked as written.

For each card, every required suite is run against the draft first (G7/G8
read a report keyed to the draft's content), then the draft is published.
``--dry-run`` runs the suites and compiles without publishing.

    docker compose exec -T api python scripts/republish_first_party.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.seed_member_graphs import MEMBERS, draft_for  # noqa: E402

#: Which suite satisfies which requirement, per card. `bot_id_for_suite` only
#: knows the collections family; the lapse suites are the insurance card's.
SUITES: dict[str, dict[str, str]] = {
    "insurance-v1": {"regression": "eval-regression-lapse", "redteam": "eval-redteam-lapse"},
}
DEFAULT_SUITES = {
    "regression": "eval-regression-collections",
    "redteam": "eval-redteam-collections",
    "outbound": "eval-outbound-collections",
}


def run_required_suites(bot_id: str, draft_id: str) -> list[str]:
    import db
    from agent_core.cards.schema import parse_card
    from agent_core.eval.run import run_named_suite

    version = db.get_prompt_version(draft_id) or {}
    card = parse_card(version.get("agentCard") or {})
    filed: list[str] = []
    for want in card.eval.require or []:
        suite = SUITES.get(bot_id, {}).get(want) or DEFAULT_SUITES.get(want)
        if not suite:
            print(f"  {want}: no suite of this kind; G-gate will report it")
            continue
        report = run_named_suite(suite, origin="manual", bot_id=bot_id, prompt_version_id=draft_id)
        filed.append(f"{want}={report.get('status')}")
    return filed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bot", action="append", help="only these cards (default: all four)")
    ap.add_argument("--dry-run", action="store_true", help="run suites and compile, publish nothing")
    args = ap.parse_args()
    wanted = set(args.bot or [b for b, _ in MEMBERS])

    import db_prompt_studio as dps

    rc = 0
    for bot_id, kind in MEMBERS:
        if bot_id not in wanted:
            continue
        draft = draft_for(bot_id, create=False)
        if draft is None:
            print(f"\n{bot_id}: no draft -- run scripts/seed_member_graphs.py --apply first")
            rc = 1
            continue
        print(f"\n{bot_id}: draft {draft['id']}")
        print("  suites:", ", ".join(run_required_suites(bot_id, draft["id"])) or "none required")
        report = dps.compile_agent_studio_card(bot_id, prompt_version_id=draft["id"])
        blocking = [(g["gate"], str(g.get("detail"))[:90]) for g in report["gates"] if g["status"] == "fail"]
        warns = [(g["gate"], str(g.get("detail"))[:90]) for g in report["gates"] if g["status"] == "warn"]
        if warns:
            print("  warn:", json.dumps(warns))
        if blocking:
            print("  BLOCKED:", json.dumps(blocking, indent=4))
            rc = 1
            continue
        if args.dry_run:
            print("  dry-run: would publish")
            continue
        published = dps.publish_prompt_version(draft["id"], f"{kind} conversation graph")
        print(f"  published {published.get('id')} -> deployment {published.get('deploymentId') or (published.get('deployment') or {}).get('id')}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
