"""Give every first-party card its conversation graph, as a draft.

The Compiled Fleet needs a graph per member: the door (``intake-v1``) to
answer the phone and route, the specialists (``kaia-v2-4``, ``insurance-v1``)
to do the business a hop lands in, and the internal brief
(``supervisor-brief``) a warm transfer opens. Until now only the collections
card had one; a hop into a member with no graph had nowhere to land.

The graphs are seed data under ``agent_core/cards/graphs/``: the collections
conversation (materialised from the retired ``voice/flows.py``), the door
(its derived half plus one authored route node -- ``scripts/seed_door_graph``
still owns that composition), and the two hand-authored member graphs.

Read-only by default. ``--apply`` writes each graph to the card's draft,
creating the draft from the published version when there is none, authors
the ``entry_node`` of every handoff from the target's own graph, and compiles.
Publishing is a separate, deliberate step: ``scripts/republish_first_party.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

GRAPHS = Path(__file__).resolve().parents[1] / "agent_core" / "cards" / "graphs"

#: bot id -> how its graph is produced. Order is the publish order too: a
#: member before the cards whose bundles merge it.
MEMBERS: tuple[tuple[str, str], ...] = (
    ("supervisor-brief", "supervisor"),
    ("insurance-v1", "insurance"),
    ("kaia-v2-4", "collections"),
    ("intake-v1", "door"),
)


def graph_for(kind: str) -> dict:
    if kind == "door":
        from scripts.seed_door_graph import door_graph

        return door_graph()
    if kind == "collections":
        from voice.flow_export import built_in_collections_graph

        return built_in_collections_graph()
    return json.loads((GRAPHS / f"{kind}.json").read_text(encoding="utf-8"))


def draft_for(bot_id: str, *, create: bool) -> dict | None:
    """The card's newest draft, else (when ``create``) one restored from the published row."""
    import db
    from sqlalchemy import text

    with db.engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, status FROM prompt_versions "
                "WHERE bot_id = :b AND status = 'draft' AND tenant_id = :t "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"b": bot_id, "t": db.current_tenant()},
        ).mappings().first()
        if row:
            return dict(row)
        if not create:
            return None
        published = conn.execute(
            text(
                "SELECT id FROM prompt_versions "
                "WHERE bot_id = :b AND status = 'published' AND tenant_id = :t "
                "ORDER BY updated_at DESC NULLS LAST LIMIT 1"
            ),
            {"b": bot_id, "t": db.current_tenant()},
        ).scalar()
    if not published:
        return None
    import db_prompt_studio as dps

    restored = dps.restore_prompt_version_as_draft(str(published))
    return {"id": restored["id"], "status": "draft", "restored_from": published}


def seed_one(bot_id: str, kind: str, *, apply: bool) -> int:
    from scripts.seed_door_graph import entry_nodes_for

    graph = graph_for(kind)
    print(f"\n{bot_id}: {kind} graph, {len(graph['nodes'])} nodes, {len(graph.get('edges') or [])} edges")
    draft = draft_for(bot_id, create=apply)
    if draft is None:
        print(f"  no draft{' and no published version to restore from' if apply else ' (pass --apply to create one)'}")
        return 1
    note = f" (restored from {draft['restored_from']})" if draft.get("restored_from") else ""
    print(f"  draft: {draft['id']}{note}")
    if not apply:
        return 0

    import db_prompt_studio as dps

    row = dps.patch_prompt_version(draft["id"], {"flow": graph})
    print(f"  wrote {len((row.get('flow') or {}).get('nodes', []))} nodes")

    card = row.get("agentCard") or {}
    entries = entry_nodes_for(card)
    changed = []
    for hop in card.get("handoffs") or []:
        target = str(hop.get("to_bot_id") or "")
        want = entries.get(target)
        if want and hop.get("entry_node") != want:
            hop["entry_node"] = want
            changed.append(f"{target} -> {want}")
    if changed:
        dps.patch_prompt_version(draft["id"], {"agentCard": card})
        print("  authored entry_node:", ", ".join(changed))

    report = dps.compile_agent_studio_card(bot_id, prompt_version_id=draft["id"])
    bad = [
        (g["gate"], g["status"], str(g.get("detail"))[:90])
        for g in report["gates"]
        if g["status"] in ("fail", "warn")
    ]
    print("  gates:", json.dumps(bad, indent=4) if bad else "all clean")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bot", action="append", help="only these cards (default: all four)")
    ap.add_argument("--apply", action="store_true", help="write drafts (default: report only)")
    args = ap.parse_args()
    wanted = set(args.bot or [b for b, _ in MEMBERS])
    rc = 0
    for bot_id, kind in MEMBERS:
        if bot_id in wanted:
            rc |= seed_one(bot_id, kind, apply=args.apply)
    if not args.apply:
        print("\nread-only; pass --apply to write")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
