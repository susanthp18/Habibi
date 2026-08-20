"""Two published cards in one tenant — the unique-constraint proof."""

from __future__ import annotations

import db
from agent_core.cards.defaults import COLLECTIONS_BOT_ID, INSURANCE_BOT_ID, card_dump


def test_two_published_cards_in_one_tenant(db_tx) -> None:
    collections = db.get_published_prompt_version(COLLECTIONS_BOT_ID)
    assert collections is not None
    draft = db.create_prompt_version(
        {
            "prompt": collections["prompt"],
            "persona": collections["persona"],
            "voice": collections["voice"],
            "guardrails": collections["guardrails"],
            "botId": INSURANCE_BOT_ID,
            "agentCard": card_dump(INSURANCE_BOT_ID),
            "summary": "insurance card",
        }
    )
    published = db.publish_prompt_version(draft["id"], "insurance card")
    assert published["botId"] == INSURANCE_BOT_ID
    still_collections = db.get_published_prompt_version(COLLECTIONS_BOT_ID)
    assert still_collections is not None
    assert still_collections["id"] == collections["id"]
    assert db.get_published_prompt_version(INSURANCE_BOT_ID)["id"] == draft["id"]


def test_list_agent_studio_cards_leads_with_four_first_party(db_tx) -> None:
    """First-party mouths come first, in order; tenant bots follow.

    The old assertion demanded the list be *exactly* those four, which any
    tenant row in ``bots`` breaks — including the two the seed itself creates.
    The contract the function actually promises is ordering, not exclusivity.
    """
    cards = db.list_agent_studio_cards()
    ids = [c["botId"] for c in cards]
    assert ids[:4] == ["intake-v1", "kaia-v2-4", "insurance-v1", "supervisor-brief"]
    assert len(ids) == len(set(ids))
    assert all(c["agentCard"] for c in cards[:4])
