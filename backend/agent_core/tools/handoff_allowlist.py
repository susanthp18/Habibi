"""Published-card handoff allowlist. Missing or unreadable cards deny every target.

Voice used to resolve the built-in card and treat a missing id as unrestricted.
Text already denied. One helper, one fail-closed answer.

The same card also decides what the model is *told* about handing off — see
:func:`handoff_routes` and :func:`specialise_handoff_tool`. Enforcement and
description are built from one reading of one card here, so the tool cannot
advertise a target the allowlist would refuse.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:  # pragma: no cover - import cycle at runtime
    from agent_core.tools.schema import ToolSpec

logger = logging.getLogger(__name__)


def handoff_allowlist(
    *,
    agent_card: Mapping[str, Any] | None = None,
    bot_id: str | None = None,
) -> set[str]:
    """Targets this mouth may transfer to. Empty set — never None — on miss.

    The live published card on the bundle, or deny. There is no longer a
    second source: the first-party Python constant used to answer for a bot
    whose bundle carried no card, which meant a target removed in the Studio
    was still reachable on the phone (ADR-0002: a cardless agent is denied
    every tool). ``domain.handoff_to_agent`` reads ``None`` as unrestricted,
    so this helper never returns ``None``.
    """
    from agent_core.cards.schema import parse_card

    if agent_card:
        try:
            return set(parse_card(dict(agent_card)).handoff_targets())
        except Exception:
            logger.warning("handoff allowlist: live card unreadable — denying every target")
            return set()
    if bot_id:
        logger.warning("handoff allowlist: no card on the bundle for bot_id=%s — denying every target", bot_id)
    return set()


def handoff_routes(
    *,
    agent_card: Mapping[str, Any] | None = None,
    bot_id: str | None = None,
) -> list[tuple[str, str]]:
    """``(to_bot_id, when)`` in the order the card lists them.

    Same resolution order and same fail-closed answer as
    :func:`handoff_allowlist` — an unreadable card describes no route, which is
    consistent with it permitting none.
    """
    from agent_core.cards.schema import parse_card

    card = None
    if agent_card:
        try:
            card = parse_card(dict(agent_card))
        except Exception:
            card = None
    if card is None:
        return []
    return [(h.to_bot_id, (h.when or "").strip()) for h in card.handoffs if h.to_bot_id]


def specialise_handoff_tool(spec: "ToolSpec", routes: list[tuple[str, str]]) -> "ToolSpec":
    """``handoff_to_agent`` with this card's targets in its own schema.

    ``card.handoffs[].when`` was stored, gated at publish, shown in the Agent
    graph tab as "guidance for the model" — and read by nobody. The tool's
    ``target_bot_id`` description was a static string naming two example bot
    ids, so the model was never told which specialists this particular card can
    reach, let alone when to reach them. The default cards' own conditions
    ("collections intent", "in-policy upsell after PTP") were decoration.

    The enum is the enforcement set, so the tool cannot advertise a target
    ``domain.handoff_to_agent`` would then refuse. A card with no handoffs is
    left exactly as it is today: no enum, the catalog's own wording.
    """
    if not routes or not spec.args:
        return spec
    lines = [f"{target} — {when}" if when else target for target, when in routes]
    args = tuple(
        replace(
            arg,
            enum=tuple(target for target, _ in routes),
            description=(
                "Destination bot id. This card may transfer to: " + "; ".join(lines)
            ),
        )
        if arg.name == "target_bot_id"
        else arg
        for arg in spec.args
    )
    return replace(spec, args=args)


def handoff_tool_spec(
    spec: "ToolSpec",
    *,
    agent_card: Mapping[str, Any] | None = None,
    bot_id: str | None = None,
) -> "ToolSpec":
    """:func:`specialise_handoff_tool` for the card this turn is running."""
    return specialise_handoff_tool(
        spec, handoff_routes(agent_card=agent_card, bot_id=bot_id)
    )
