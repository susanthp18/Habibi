"""Insurance detached from the card never activates the upsell mesh hop."""

from __future__ import annotations

from agent_core.cards.defaults import COLLECTIONS_BOT_ID, INSURANCE_BOT_ID, collections_card
from agent_core.cards.handoff_policy import insurance_handoff_allowed


def test_collections_card_allows_insurance() -> None:
    assert insurance_handoff_allowed(COLLECTIONS_BOT_ID, collections_card().model_dump()) is True


def test_insurance_detached_is_not_allowed() -> None:
    card = collections_card().model_dump(mode="json")
    card["handoffs"] = [
        h for h in card["handoffs"] if h.get("to_bot_id") != INSURANCE_BOT_ID
    ]
    assert insurance_handoff_allowed(COLLECTIONS_BOT_ID, card) is False


def test_empty_legacy_card_keeps_mesh() -> None:
    assert insurance_handoff_allowed(COLLECTIONS_BOT_ID, {}) is True
