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
_WRITES = ("create_promise_to_pay", "apply_goodwill", "flag_dispute")


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


def _text_ctx(*, allowed):
    import bot_tools

    ctx = bot_tools.ToolContext(
        job_id="job-cardless",
        conversation_id="cv-cardless",
        customer_id="CUST-1",
        interaction_id=None,
        bot_id=None,
        customer_text="",
        intent="payment_intent",
    )
    ctx.allowed_tools = allowed
    return ctx


@pytest.mark.parametrize("name", _WRITES)
def test_whatsapp_execute_refuses_writes_when_cardless(name) -> None:
    import bot_tools

    ctx = _text_ctx(allowed=_cardless_state().allowed)
    ok, payload, _latency = bot_tools.execute_tool(ctx, name, "{}")
    assert ok is False
    assert payload["error"] == "tool_not_on_card_or_skill"
    assert payload["tool"] == name


@pytest.mark.parametrize("name", _WRITES)
def test_whatsapp_execute_refuses_when_no_grant_was_set(name) -> None:
    """Inverted sentinel: ``allowed_tools is None`` is deny, not unfiltered."""
    import bot_tools

    ctx = _text_ctx(allowed=None)
    ok, payload, _latency = bot_tools.execute_tool(ctx, name, "{}")
    assert ok is False
    assert payload["error"] == "tool_not_on_card_or_skill"


def test_whatsapp_offers_no_tools_when_cardless() -> None:
    offered = CATALOG.openai_tools(list(_cardless_state().offered))
    assert offered == []


def test_text_runtime_no_longer_falls_back_to_the_full_catalog() -> None:
    import bot_tools

    # The catalogue constant the fallback read is gone; nothing can fall back to it.
    assert not hasattr(bot_tools, "TOOL_DEFINITIONS")


# --- sandbox ----------------------------------------------------------------


@pytest.mark.parametrize("name", _WRITES)
def test_sandbox_execute_refuses_writes_when_cardless(name) -> None:
    """Sandbox shares ``bot_tools.execute_tool``; the empty grant must bind."""
    import bot_tools

    ctx = _text_ctx(allowed=_cardless_state().allowed)
    ok, payload, _latency = bot_tools.execute_tool(ctx, name, "{}")
    assert ok is False
    assert payload["error"] == "tool_not_on_card_or_skill"


# --- voice ------------------------------------------------------------------


def test_voice_cardless_keeps_the_floor_and_drops_writes() -> None:
    pytest.importorskip("pipecat.flows")
    from voice.session import VoiceSession
    from voice.tools import ALWAYS_ON, build_tools

    # The floor a cardless voice mouth keeps is the grant's statement, read
    # through the same MouthTurn the voice runtime uses; build_tools no longer
    # unions ALWAYS_ON back on its own.
    grant = resolve_mouth({}).tools(channel="voice").allowed
    assert grant == ALWAYS_ON
    _state, tools = build_tools(
        VoiceSession(session_id="VS-CARDLESS"),
        bot_id=None,
        start_recording=None,
        nodes={},
        allowed_tool_names=grant,
    )
    assert ALWAYS_ON <= set(tools)
    assert not (set(tools) & SKILL_GATED_TOOLS)
    for name in _WRITES:
        assert name not in tools
    assert "end_call" in tools
    assert "disclose_recording" in tools
    assert "verify_identity" in tools


def test_voice_omitting_a_grant_is_also_deny_all() -> None:
    """Inverted sentinel: ``allowed_tool_names is None`` is not the full registry."""
    pytest.importorskip("pipecat.flows")
    from voice.session import VoiceSession
    from voice.tools import ALWAYS_ON, build_tools

    _state, tools = build_tools(
        VoiceSession(session_id="VS-CARDLESS-NONE"),
        bot_id=None,
        start_recording=None,
        nodes={},
    )
    assert set(tools) == set(ALWAYS_ON)
    assert "create_promise_to_pay" not in tools
