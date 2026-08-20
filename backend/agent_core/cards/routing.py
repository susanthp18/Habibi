"""Which cards actually receive traffic, and how.

The fleet index showed every published card as "live · 100%". That is true of
its *deployment* and false of its *routing*: an inbound call or message resolves
exactly one bot, and every other card is reachable only if the entry card — or
something the entry card can reach — lists it in ``handoffs``.

Three states, all derived from real config:

``entry``
    The bot both runtimes resolve for inbound traffic.
``handoff``
    In the transitive closure of ``handoffs`` from the entry card. Reached
    mid-conversation by ``handoff_to_agent`` (allowlisted against the *calling*
    card's targets in agent_core/tools/domain.py) or by the in-call mesh hop
    (gated by agent_core/cards/handoff_policy.py).
``unreachable``
    Published, deployed, and unreachable by any path. Nothing routes to it.
"""

from __future__ import annotations

import os
from collections import deque
from typing import Any, Iterable


def runtime_entry_bot_id() -> str:
    """The bot id inbound traffic resolves to.

    Both runtimes read the same env var: ``bot_runtime._bot_id()`` for the
    message channels, and ``db.DEFAULT_BOT_ID`` for voice via
    ``load_active_bundle``'s ``bot_id or DEFAULT_BOT_ID``. Kept as one function
    so the console cannot drift from what the workers actually do.
    """
    import db

    return (os.getenv("BOT_ID") or "").strip() or db.DEFAULT_BOT_ID


def handoff_targets(card: Any) -> list[str]:
    """``to_bot_id`` values off a raw card dict, tolerant of unmigrated JSON."""
    if not isinstance(card, dict):
        return []
    out: list[str] = []
    for row in card.get("handoffs") or []:
        if not isinstance(row, dict):
            continue
        target = str(row.get("to_bot_id") or row.get("toBotId") or "").strip()
        if target:
            out.append(target)
    return out


def reachable_from(entry: str, edges: dict[str, list[str]]) -> set[str]:
    """Breadth-first closure. Cycles are normal here — Collections and
    Insurance list each other — so visited-tracking is load bearing."""
    seen: set[str] = set()
    queue: deque[str] = deque([entry])
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        for nxt in edges.get(node, ()):
            if nxt not in seen:
                queue.append(nxt)
    return seen


def reachability(
    cards: Iterable[tuple[str, Any]],
    *,
    entry: str | None = None,
) -> dict[str, str]:
    """bot_id → "entry" | "handoff" | "unreachable" for the given cards.

    ``cards`` is (bot_id, raw agent card). Edges come from the cards themselves,
    so an unsaved handoff edit shows up as soon as it is published — there is no
    second routing table to keep in sync.
    """
    rows = list(cards)
    entry_id = entry or runtime_entry_bot_id()
    edges = {bot_id: handoff_targets(card) for bot_id, card in rows}
    live = reachable_from(entry_id, edges)
    out: dict[str, str] = {}
    for bot_id, _ in rows:
        if bot_id == entry_id:
            out[bot_id] = "entry"
        elif bot_id in live:
            out[bot_id] = "handoff"
        else:
            out[bot_id] = "unreachable"
    return out
