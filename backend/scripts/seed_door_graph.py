"""Author the door graph onto a card's draft.

The door half of the built-in script is *derived* (``flow_export.part="door"``),
so this script does not write nodes -- with one exception it has to write,
explained below. Everything else here is plumbing: fetch the draft, attach the
graph, report what changed.

**Why one node is authored.** ``build_tools`` takes ``hub_node`` as a parameter
defaulting to ``"state_position"``, and ``flows_dynamic`` never overrides it. So
on any authored graph a successful verification transitions to
``_node("state_position")``. If the door's namespace has no node under that key,
``resolve_key`` falls through to its third tier, finds the single
``kaia-v2-4/state_position``, and lands the call in another member's namespace
with no ledger row, no carry packet and no hop-cap decrement -- a boundary
crossing that no gate sees because no handoff happened. The door therefore owns
that key, as a *route* node whose business tool is ``handoff_to_agent`` and
nothing else. It cannot be derived, because the derived node under that key is
the collections hub.

**Why ``entryFor`` is stripped.** The derived ``confirm_identity`` advertises
four collections outbound missions. Those belong to the card that owns the
cadences for them; a door claiming them would be claiming mission entries it
cannot run.

Read-only by default. ``--apply`` writes, and writes only to a draft.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Python puts this script's own directory on sys.path, not the caller's cwd, so
# `python scripts/seed_door_graph.py` cannot see `voice` or `db` without this.
# Same line as scripts/eval_gate_preflight.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The route node the door owns. Not derived -- see the module docstring.
_ROUTE_NODE = {
    "id": "n_state_position",
    "key": "state_position",
    "type": "conversation",
    # `_LAYOUT["state_position"]` in flow_export, so the authored node sits
    # where a reader of the full graph already expects the hub to be.
    "position": {"x": 0, "y": 460},
    "data": {
        "name": "Route to a specialist",
        "instructionType": "prompt",
        "instructions": (
            "The caller is verified and you know why they rang. Hand the call to "
            "the specialist that owns it, using handoff_to_agent. Say one short "
            "bridging line first so the caller knows what is happening; do not "
            "discuss balances, arrears, offers, payments or policy terms "
            "yourself -- you do not have the tools for it and the specialist "
            "does. If you cannot tell which specialist owns the request, ask one "
            "clarifying question, then hand off."
        ),
        "isStart": False,
        "entryFor": [],
        "respondImmediately": False,
        "entryLine": "",
        "tools": ["handoff_to_agent"],
        "extractVariables": [],
        "endConversation": False,
    },
}


def door_graph() -> dict:
    """The derived door half plus the one authored route node.

    The derived nodes carry the collections card's tools (`pre_close` offers
    `capture_lead`); a door cannot grant those and G16 said so on every
    compile. Each node keeps only what a door may hold -- the routing set,
    the runtime floor and the flow-control verbs -- so the graph describes
    the door's conversation, not a filtered view of somebody else's.
    """
    from agent_core.fleet.compile import _DOOR_TOOLS
    from agent_core.tools.grant import VOICE_ALWAYS, VOICE_FLOW_TOOLS
    from voice.flow_export import built_in_collections_graph

    allowed = _DOOR_TOOLS | VOICE_ALWAYS | VOICE_FLOW_TOOLS
    graph = built_in_collections_graph(part="door")
    for node in graph["nodes"]:
        if node["key"] == "confirm_identity":
            node["data"]["entryFor"] = []
        node["data"]["tools"] = [t for t in node["data"]["tools"] if t in allowed]
    graph["globalTools"] = [t for t in graph["globalTools"] if t in allowed]
    graph["nodes"].append(_ROUTE_NODE)
    return graph


def entry_nodes_for(card_raw: dict) -> dict[str, str]:
    """Where each handoff should land, derived from the target's own graph.

    `CardHandoff.entry_node` defaults to "" and is documented as "that member's
    start node". There is no start node to fall back to: `namespaced` clears
    `isStart` on every non-primary member, so `_merge_members` picks "the first
    node in the list", which for a collections graph is `greet_disclose`. The
    hop would greet an already-verified caller and read the recording
    disclosure a second time.

    Same rule as the compiler's default (`flow_graph.business_entry`); this
    writes it onto the card so the canvas shows where the hop lands.
    """
    import flow_graph as fg
    from db_prompt_studio import _fleet_members

    out: dict[str, str] = {}
    # `_fleet_members` is the same reader the compiler uses to build the merged
    # graph, so the node this picks is a node that will actually be there.
    for member in _fleet_members(card_raw):
        entry = fg.business_entry(member.get("flow") or {})
        if entry and fg.local_key(entry) not in fg.DOOR_KEYS:
            out[str(member.get("bot_id") or "")] = entry
    return out


def _draft_for(bot_id: str) -> dict | None:
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
    return dict(row) if row else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bot", default="intake-v1", help="card whose draft gets the graph")
    ap.add_argument("--apply", action="store_true", help="write it (default: report only)")
    args = ap.parse_args()

    graph = door_graph()
    keys = [n["key"] for n in graph["nodes"]]
    print(f"door graph: {len(keys)} nodes")
    for n in graph["nodes"]:
        mark = "authored" if n["key"] == _ROUTE_NODE["key"] else "derived"
        print(f"  {n['key']:22s} {mark:8s} tools={n['data']['tools']}")
    print(f"globalTools: {graph['globalTools']}")

    draft = _draft_for(args.bot)
    if draft is None:
        print(f"\n{args.bot}: no draft to write to", file=sys.stderr)
        return 1
    print(f"\ntarget draft: {draft['id']} ({args.bot})")

    if not args.apply:
        print("\nread-only; pass --apply to write")
        return 0

    import db_prompt_studio as dps

    row = dps.patch_prompt_version(draft["id"], {"flow": graph})
    stored = row.get("flow") or {}
    print(f"wrote {len(stored.get('nodes', []))} nodes to {draft['id']}")

    # Author where each hop lands. Without this the merged graph sends a
    # verified caller back to `greet_disclose` in the receiving member -- G-F15
    # is the gate that says so, and this is the fix it asks for.
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
        row = dps.patch_prompt_version(draft["id"], {"agentCard": card})
        print("authored entry_node:", ", ".join(changed))
    else:
        print("entry_node: nothing to author")

    report = dps.compile_agent_studio_card(args.bot, prompt_version_id=draft["id"])
    bad = [
        (g["gate"], g["status"], str(g.get("detail"))[:80])
        for g in report["gates"]
        if g["status"] in ("fail", "warn")
    ]
    print("gates:", json.dumps(bad, indent=2) if bad else "all clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
