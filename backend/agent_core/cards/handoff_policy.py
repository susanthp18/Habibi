"""In-call insurance mesh is allowed only when the active card lists it."""

from __future__ import annotations

from typing import Any

from agent_core.cards.defaults import INSURANCE_BOT_ID, card_dump
from agent_core.cards.schema import AgentCard, is_authored


def insurance_handoff_allowed(bot_id: str | None, card_raw: Any = None) -> bool:
    """False when the published/authored card has detached Insurance.

    Legacy empty cards keep today's mesh behaviour (allowed) so an unmigrated
    mouth is not silently stripped of upsell.
    """
    raw = card_raw if isinstance(card_raw, dict) else None
    if not is_authored(raw) and bot_id:
        try:
            raw = card_dump(bot_id)
        except KeyError:
            return True
    if not is_authored(raw):
        return True
    try:
        card = AgentCard.model_validate(raw)
    except Exception:
        return False
    return INSURANCE_BOT_ID in card.handoff_targets()
