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
    card's targets in agent_core/tools/domain.py). The card's ``handoffs`` are
    the only gate: an authored edge is the permission.
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

import logging
import os
from collections import deque
from typing import Any, Iterable


_logger = logging.getLogger(__name__)


def runtime_entry_bot_id() -> str:
    """The bot id inbound traffic resolves to.

    Both runtimes read the same env var: ``bot_runtime._bot_id()`` for the
    message channels, and ``db.DEFAULT_BOT_ID`` for voice via
    ``load_active_bundle``'s ``bot_id or DEFAULT_BOT_ID``. Kept as one function
    so the console cannot drift from what the workers actually do.
    """
    import db

    return (os.getenv("BOT_ID") or "").strip() or db.DEFAULT_BOT_ID


def door_enabled() -> bool:
    """Whether authored entry bindings decide who answers.

    Declared in ``agent_core.platform_flags`` -- that module's own rule is "do
    not invent a new name in a feature PR; add it here and in .env.example", and
    this flag was breaking it. Imported lazily because ``routing`` is on the
    voice import path and ``platform_flags`` is not otherwise needed there.
    """
    from agent_core.platform_flags import door_enabled as _door_enabled

    return _door_enabled()


def resolve_entry(channel: str, address: str | None = None) -> str:
    """The bot id that answers ``channel`` at ``address``.

    The replacement for :func:`runtime_entry_bot_id`, which takes no arguments —
    not the channel, not the dialled number — and so resolves the same card for
    every inbound contact everywhere.

    ``address`` is the *dialled* number, the ``To`` leg. Routing never consults
    the caller or the CRM: ``twilio_ops.lookup_customer_for_caller`` sits under a
    bare ``except``, so letting it choose the answering card would turn one flaky
    round trip into "a different agent picked up", which is unauditable after the
    fact. A dialled number is a fact the carrier hands us and cannot fail.

    Resolution is most-specific-first: the exact address, then the channel
    default (``address IS NULL``), then today's env lookup. The text mouths reach
    the channel default by construction — ``bot_runtime._bot_id()`` has no
    address to pass — which is why both shapes live in one table rather than
    becoming a second mechanism for WhatsApp.

    Falls back to :func:`runtime_entry_bot_id` on every uncertainty: flag off,
    table absent, no row, or a failed read. A door that guesses when it cannot
    read its own bindings would route calls to an arbitrary card.
    """
    if not door_enabled():
        return runtime_entry_bot_id()
    import db

    try:
        from sqlalchemy import text as _text

        with db.engine.connect() as conn:
            if not conn.execute(
                _text("SELECT to_regclass('public.entry_bindings')")
            ).scalar():
                return runtime_entry_bot_id()
            row = conn.execute(
                _text(
                    """
                    SELECT bot_id FROM entry_bindings
                     WHERE tenant_id = :tenant
                       AND channel = :channel
                       AND enabled
                       AND (address = :address OR address IS NULL)
                     ORDER BY (address IS NULL)
                     LIMIT 1
                    """
                ),
                {
                    "tenant": db.current_tenant(),
                    "channel": (channel or "").strip(),
                    "address": (address or "").strip() or None,
                },
            ).mappings().first()
    except Exception:
        _logger.exception("entry binding lookup failed · channel=%s", channel)
        return runtime_entry_bot_id()
    if not row:
        return runtime_entry_bot_id()
    return str(row["bot_id"])


def upsert_entry_binding(
    *,
    channel: str,
    bot_id: str,
    address: str | None = None,
    note: str = "",
    enabled: bool = True,
) -> dict[str, Any]:
    """Author which card answers ``channel`` at ``address``.

    ``address=None`` is the channel default -- the row the text mouths reach,
    because ``bot_runtime._bot_id()`` has no address to pass. The table's two
    partial unique indexes enforce one binding per address and one default per
    channel, so the conflict target differs between the two shapes and there is
    no single ``ON CONFLICT`` that covers both.

    Writing a binding changes nothing while ``DOOR_ENABLED`` is unset:
    ``resolve_entry`` does not read the table at all until the flag is on. That
    is deliberate -- the row can be authored, reviewed and left in place before
    anything routes by it.
    """
    import uuid

    import db
    from sqlalchemy import text as _text

    addr = (address or "").strip() or None
    params = {
        "id": f"eb-{uuid.uuid4().hex[:12]}",
        "tenant": db.current_tenant(),
        "channel": (channel or "").strip(),
        "address": addr,
        "bot": (bot_id or "").strip(),
        "note": note,
        "enabled": bool(enabled),
    }
    conflict = (
        "(tenant_id, channel, address) WHERE address IS NOT NULL"
        if addr
        else "(tenant_id, channel) WHERE address IS NULL"
    )
    with db.engine.begin() as conn:
        row = conn.execute(
            _text(
                f"""
                INSERT INTO entry_bindings
                  (id, tenant_id, channel, address, bot_id, note, enabled)
                VALUES (:id, :tenant, :channel, :address, :bot, :note, :enabled)
                ON CONFLICT {conflict} DO UPDATE SET
                  bot_id = EXCLUDED.bot_id,
                  note = EXCLUDED.note,
                  enabled = EXCLUDED.enabled,
                  updated_at = now()
                RETURNING id, channel, address, bot_id, enabled
                """
            ),
            params,
        ).mappings().first()
    return dict(row) if row else {}


def list_entry_bindings() -> list[dict[str, Any]]:
    """Every authored binding for this tenant, most specific first."""
    import db
    from sqlalchemy import text as _text

    with db.engine.connect() as conn:
        rows = conn.execute(
            _text(
                """
                SELECT id, channel, address, bot_id, enabled, note, updated_at
                  FROM entry_bindings
                 WHERE tenant_id = :tenant
                 ORDER BY channel, (address IS NULL), address
                """
            ),
            {"tenant": db.current_tenant()},
        ).mappings().all()
    return [dict(r) for r in rows]


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


def handoff_edge(card: Any, target: str) -> dict[str, Any]:
    """The card's own edge to ``target``, or an empty dict.

    Tolerant of both spellings for the same reason :func:`handoff_targets` is —
    stored cards carry ``toBotId`` as well as ``to_bot_id``. The voice runtime
    had its own copy that matched only the snake case, so on a camelCase card a
    hop silently lost its ``carry``, ``bridge_line`` and ``refusal_line`` and
    fell back to defaults.
    """
    if not isinstance(card, dict):
        return {}
    for row in card.get("handoffs") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("to_bot_id") or row.get("toBotId") or "").strip() == target:
            return row
    return {}


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
