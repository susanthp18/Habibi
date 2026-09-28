"""A cardless mouth is granted nothing — at each runtime, not only in grant.py.

``tests/test_tool_grant.py`` already pins ADR-0002 inside ``ToolGrant``. This
file pins the same property at the three runtimes that used to fail open:
voice, WhatsApp/text, and sandbox. A Deployment with ``agent_card = '{}'``
must offer zero write tools, and ``execute_tool`` must refuse them.
"""

from __future__ import annotations

import pytest

from agent_core.skills.intersect import SKILL_GATED_TOOLS
from agent_core.skills.runtime import resolve_mouth
from agent_core.tools.catalog import CATALOG

_CARDLESS = ({}, None, {"identity": "not-an-object"})


def _cardless_state(card_raw=None):
    return resolve_mouth({} if card_raw is None else card_raw).tools()


# --- the producer -----------------------------------------------------------


@pytest.mark.parametrize("card_raw", _CARDLESS)
def test_mouth_turn_grants_nothing_when_the_card_is_unauthored(card_raw) -> None:
    tools = _cardless_state(card_raw)
    assert tools.allowed == frozenset()
    assert tools.offered == ()
    assert not (tools.allowed & SKILL_GATED_TOOLS)


# --- WhatsApp / text --------------------------------------------------------


def test_whatsapp_offers_no_tools_when_cardless() -> None:
    offered = CATALOG.openai_tools(list(_cardless_state().offered))
    assert offered == []
