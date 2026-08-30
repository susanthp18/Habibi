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
``direct``
    Holds its own active production deployment, so ``load_active_bundle`` will
    resolve it when something addresses it by ``bot_id`` -- but nothing hands
    off to it. Intake is the shipped example: a front door that routes *to*
    Collections while Collections is the configured default.
``unreachable``
    No deployment and no inbound path. Nothing routes to it and nothing can
    address it. This is the state that means dead config.
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


def reachable_from(entry: str | Iterable[str], edges: dict[str, list[str]]) -> set[str]:
    """Breadth-first closure. Cycles are normal here — Collections and
    Insurance list each other — so visited-tracking is load bearing.

    Takes one bot id or several. Several, because inbound traffic does not in
    fact resolve exactly one bot: ``agent_core/deployment.py`` resolves
    ``bot_id or db.DEFAULT_BOT_ID`` against ``bot_deployments``, so the default
    is a fallback and any card holding its own active deployment is separately
    addressable.
    """
    seen: set[str] = set()
    queue: deque[str] = deque([entry] if isinstance(entry, str) else entry)
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
    deployed: Iterable[str] = (),
) -> dict[str, str]:
    """bot_id → "entry" | "handoff" | "direct" | "unreachable".

    ``cards`` is (bot_id, raw agent card). Edges come from the cards themselves,
    so an unsaved handoff edit shows up as soon as it is published — there is no
    second routing table to keep in sync.

    ``deployed`` is the set of cards holding an active production deployment.
    They seed the walk alongside the default entry, because they are reachable:
    something addressing them by bot_id gets them. Without this the fleet index
    called Intake — a live front door at 100% traffic — unreachable, and a card
    that is genuinely dead config read exactly the same as one that is not.

    A card reached through an edge is reported as ``handoff`` even when it also
    holds its own deployment: its position in the conversation graph is the more
    specific fact, and ``direct`` is reserved for the cards that have no inbound
    edge at all.
    """
    rows = list(cards)
    entry_id = entry or runtime_entry_bot_id()
    deployed_ids = {b for b in deployed if b}
    edges = {bot_id: handoff_targets(card) for bot_id, card in rows}
    closure = reachable_from({entry_id, *deployed_ids}, edges)
    # Reached *through an edge*, rather than merely present in the closure —
    # a seed is in its own closure without anything routing to it.
    inbound = {target for node in closure for target in edges.get(node, ())}
    out: dict[str, str] = {}
    for bot_id, _ in rows:
        if bot_id == entry_id:
            out[bot_id] = "entry"
        elif bot_id in inbound:
            out[bot_id] = "handoff"
        elif bot_id in deployed_ids:
            out[bot_id] = "direct"
        else:
            out[bot_id] = "unreachable"
    return out
