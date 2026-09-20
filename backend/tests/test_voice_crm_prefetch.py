"""CRM card prefetch at connect, injection only after a matching verify (Phase 3.4).

Outbound and ANI-matched inbound already know a customer id when the call
connects. Loading the card there overlaps the greeting. D3 still holds: ANI
identifies, last-4 verifies. Prefetch is not proof and must not be injected
to a wrong party.
"""

from __future__ import annotations

import asyncio

import pytest

from voice import persist
from voice import tools as voice_tools
from voice.session import VoiceSession
from voice.tools_verify import (
    drop_crm_prefetch,
    start_crm_prefetch,
    take_crm_prefetch,
)


class _Card:
    def __init__(self, cid: str) -> None:
        self.cid = cid

    def crm_card_message(self):
        return {"role": "developer", "content": f"card:{self.cid}"}

    def crm_card(self):
        return {"customerId": self.cid}


def _session(cid: str | None = None) -> VoiceSession:
    session = VoiceSession(session_id="VS-PREFETCH", customer_id=None)
    session.interaction_id = "IX-PREFETCH"
    return session


def _build(session: VoiceSession, *, inject=None):
    return voice_tools.build_tools(
        session,
        bot_id="bot-1",
        start_recording=None,
        nodes={},
        inject_developer=inject,
        channel="voice",
    )


@pytest.fixture
def loads(monkeypatch):
    seen: list[str] = []

    def fake_load(**kwargs):
        cid = kwargs["customer_id"]
        seen.append(cid)
        return _Card(cid)

    monkeypatch.setattr(
        "agent_core.context.CallContext.load_for_customer", staticmethod(fake_load)
    )
    monkeypatch.setattr("voice.config.voice_memory", lambda: False)
    return seen


def test_matching_verify_uses_the_prefetch_and_loads_once(loads, monkeypatch):
    injected: list = []

    async def inject(messages):
        injected.extend(messages)

    monkeypatch.setattr(
        persist,
        "lookup_customer_for_verify",
        lambda **_kw: {"customerId": "C-1", "name": "Ada", "accountId": "A-1", "outstanding": 0},
    )
    monkeypatch.setattr(persist, "bind_customer_to_interaction", lambda **_kw: None)
    monkeypatch.setattr(persist, "record_identity_verification", lambda **_kw: None)

    async def scenario():
        session = _session()
        start_crm_prefetch(
            session,
            customer_id="C-1",
            channel="voice",
            interaction_id=session.interaction_id,
            account_id=None,
            kb_snapshot_id=None,
            bot_id="bot-1",
            persona=None,
        )
        # Let the thread hop finish so verify consumes a completed task.
        await session.extra["_crm_prefetch_task"]
        _state, tools = _build(session, inject=inject)
        result, _next = await tools["verify_identity"].handler(
            {"method": "phone_match", "value": "3210"}, None
        )
        return result

    result = asyncio.run(scenario())
    assert result["ok"] is True
    assert loads == ["C-1"], f"verify started a second CRM load: {loads}"
    assert injected and injected[0]["content"] == "card:C-1"


def test_mismatched_id_loads_fresh_and_does_not_inject_the_prefetch(loads, monkeypatch):
    injected: list = []

    async def inject(messages):
        injected.extend(messages)

    monkeypatch.setattr(
        persist,
        "lookup_customer_for_verify",
        lambda **_kw: {"customerId": "C-RIGHT", "name": "Bea", "accountId": "A-2", "outstanding": 0},
    )
    monkeypatch.setattr(persist, "bind_customer_to_interaction", lambda **_kw: None)
    monkeypatch.setattr(persist, "record_identity_verification", lambda **_kw: None)

    async def scenario():
        session = _session()
        start_crm_prefetch(
            session,
            customer_id="C-WRONG",
            channel="voice",
            interaction_id=session.interaction_id,
            account_id=None,
            kb_snapshot_id=None,
            bot_id="bot-1",
            persona=None,
        )
        await session.extra["_crm_prefetch_task"]
        _state, tools = _build(session, inject=inject)
        result, _next = await tools["verify_identity"].handler(
            {"method": "phone_match", "value": "3210"}, None
        )
        return result

    result = asyncio.run(scenario())
    assert result["ok"] is True
    assert loads == ["C-WRONG", "C-RIGHT"]
    assert [m["content"] for m in injected] == ["card:C-RIGHT"]


def test_no_injection_if_verify_never_succeeds(loads, monkeypatch):
    injected: list = []

    async def inject(messages):
        injected.extend(messages)

    monkeypatch.setattr(persist, "lookup_customer_for_verify", lambda **_kw: None)
    monkeypatch.setattr(persist, "record_identity_verification", lambda **_kw: None)

    async def scenario():
        session = _session()
        start_crm_prefetch(
            session,
            customer_id="C-1",
            channel="voice",
            interaction_id=session.interaction_id,
            account_id=None,
            kb_snapshot_id=None,
            bot_id="bot-1",
            persona=None,
        )
        await session.extra["_crm_prefetch_task"]
        _state, tools = _build(session, inject=inject)
        result, _next = await tools["verify_identity"].handler(
            {"method": "phone_match", "value": "0000"}, None
        )
        drop_crm_prefetch(session)
        return result, session.extra.get("_crm_prefetch_task")

    result, leftover = asyncio.run(scenario())
    assert result["ok"] is False
    assert injected == [], "the prefetched card was injected without a verify match"
    assert leftover is None
    assert loads == ["C-1"]


def test_take_returns_none_for_a_mismatched_id(loads):
    async def scenario():
        session = _session()
        start_crm_prefetch(
            session,
            customer_id="C-1",
            channel="voice",
            interaction_id="IX",
            account_id=None,
            kb_snapshot_id=None,
            bot_id=None,
            persona=None,
        )
        await session.extra["_crm_prefetch_task"]
        return await take_crm_prefetch(session, "C-OTHER")

    assert asyncio.run(scenario()) is None
