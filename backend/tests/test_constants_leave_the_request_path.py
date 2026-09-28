"""The four first-party Agent Cards are seed data, not runtime authorities.

`agent_core.cards.defaults` builds the shipped cards as Python objects. They
are seeded into `prompt_versions` and edited in the Studio from then on; the
published row is the card the compiler gated and the card a regulator is shown.
For months three request paths read the constant instead -- the voice handoff
allowlist, the mission envelope for a bot with no published version, the ops
floor's display name -- so a target removed in the Studio was still reachable
on the phone, and a card could be edited, published and change nothing.

This file pins the boundary: nothing on a request path imports the constants,
and the one-time seed is the only thing that does.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

#: Modules that serve a call, a message or a dial. None may reach for the
#: constants; a bot with no published card gets no card.
_REQUEST_PATH = (
    "voice/bot.py",
    "voice/bot_flow.py",
    "voice/bot_pipeline.py",
    "voice/bot_handlers.py",
    "voice/tools.py",
    "voice/flows_dynamic.py",
    "bot_runtime.py",
    "bot_tools.py",
    "mission.py",
    "cadence.py",
    "campaigns.py",
    "outbound.py",
    "db_floor.py",
    "db_webhooks.py",
    "db_provider_health.py",
    "agent_core/tools/handoff_allowlist.py",
    "agent_core/tools/domain.py",
    "agent_core/deployment.py",
    "agent_core/treatment/enact.py",
)


def test_a_bot_with_no_published_card_has_no_card(monkeypatch) -> None:
    import mission

    assert mission.card_for_bot("no-such-bot-anywhere") is None


def test_rupees_read_the_indian_way_on_every_borrower_facing_line() -> None:
    import mission
    import money_inr

    # the WhatsApp template amount (promise_fulfillment reads money_inr.template_amount)
    assert money_inr.template_amount(1234567) == "12,34,567"
    assert money_inr.template_amount("1500.50") == "1,500.50"
    assert mission._inr(1234567) == "12,34,567"


