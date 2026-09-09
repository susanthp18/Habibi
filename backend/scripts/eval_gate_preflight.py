"""Would turning on the eval gate flags make any live card unpublishable?

Run this before setting ``EVAL_GATE_ENABLED``, ``REDTEAM_GATE_ENABLED`` or
``OUTBOUND_EVAL_GATE_ENABLED``.

The gates fail closed on a missing report, and they count only a report filed
against the *exact* prompt version being published — a green suite on last
week's card must not open the gate for this week's. Both halves are correct and
together they mean a flag flip can make every card in the tenant unpublishable
at once, with the failure arriving as a 422 on somebody's publish rather than as
a decision anybody took.

Today that is not hypothetical: every ``eval_reports`` row in this database has
``prompt_version_id`` NULL, because nothing supplied one until the plumbing
landed. So flipping a flag right now blocks all five published cards.

**This does not backfill, and no backfill is coming.** Stamping an old row with
a prompt version it was never run against would be a fabricated provenance
record, which is the exact thing these gates exist to check. The fix is to re-run
the suites; this only tells you which ones, before the flag rather than after.

Read-only. Exit 0 when every requirement is satisfied, 1 when something is
missing, so it can gate a deploy step.

    docker compose exec -T voice python scripts/eval_gate_preflight.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Same bootstrap as the other scripts in this directory: they run as __main__
# from a working directory that is not on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: Requirement name on the card -> the gate that reads it. `twin` is absent
#: deliberately: G11 reads `twin_runs`, not `eval_reports`, and is satisfied
#: from the Sandbox inspector's Twin tab rather than by a suite run.
_GATE_FOR: dict[str, str] = {
    "regression": "G7",
    "redteam": "G8",
    "outbound": "G-OB9",
}


def missing_reports() -> list[dict[str, Any]]:
    """One row per (bot, requirement) that would fail if the flags were on."""
    import db
    from agent_core.cards.schema import is_authored, parse_card

    out: list[dict[str, Any]] = []
    for summary in db.list_agent_studio_cards():
        bot_id = summary.get("botId")
        version_id = summary.get("promptVersionId")
        if not bot_id or not version_id:
            continue  # nothing published; no publish to block
        raw = summary.get("publishedCard") or {}
        if not is_authored(raw):
            continue
        try:
            card = parse_card(raw)
        except Exception as exc:  # a card that will not parse fails G0 first
            out.append({"bot": bot_id, "require": "-", "gate": "G0", "why": f"card unparseable: {exc}"})
            continue
        for want in card.eval.require or []:
            gate = _GATE_FOR.get(want)
            if gate is None:
                continue
            report = db.get_latest_eval_report(
                bot_id=bot_id, kind=want, prompt_version_id=version_id
            )
            if report is None:
                out.append(
                    {
                        "bot": bot_id,
                        "require": want,
                        "gate": gate,
                        "why": f"no {want} report filed against {version_id}",
                    }
                )
            elif str(report.get("status") or "") != "pass":
                out.append(
                    {
                        "bot": bot_id,
                        "require": want,
                        "gate": gate,
                        "why": f"{want} report {report.get('id')} is {report.get('status')}",
                    }
                )
    return out


def main() -> int:
    rows = missing_reports()
    if not rows:
        print("eval gate preflight: every published card satisfies its own eval.require")
        return 0
    print(f"eval gate preflight: {len(rows)} requirement(s) would block a publish\n")
    for row in rows:
        print(f"  {row['bot']:28} {row['gate']:7} {row['require']:11} {row['why']}")
    print(
        "\nRe-run the named suites against the published version before flipping the flag. "
        "Do not stamp existing rows with a version they were not run against."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
