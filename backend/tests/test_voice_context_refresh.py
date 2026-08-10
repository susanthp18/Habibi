"""In-call CRM context refresh after a write (voice/tools.py).

The bug: ``CallContext`` was loaded exactly once, at verify_identity, and
``refresh_from_crm()`` was never called anywhere in the voice path. After
booking a PTP the bot's own context still said the account had no open
promises, so "what did I just agree to" could not be answered from context.

Only tools that change something the CRM card actually renders schedule a
refresh — see the table in the plan. request_callback deliberately does not:
CallContext.open_work omits callbacks, so a refresh would re-read the CRM and
change nothing.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_core.context import CallContext
from voice import tools as voice_tools
from voice.context_edit import CRM_CARD_PREFIX
from voice.session import VoiceSession

# Tools whose writes appear in CallContext.open_work / customer_card.
CARD_AFFECTING = {"create_promise_to_pay", "flag_dispute", "request_documents"}
# Written by voice, but invisible to the card.
NOT_CARD_AFFECTING = {"request_callback", "capture_lead", "add_customer_note"}


@pytest.fixture(autouse=True)
def _clean_registry():
    with voice_tools._session_tasks_lock:
        voice_tools._session_tasks.clear()
    yield
    with voice_tools._session_tasks_lock:
        for bucket in voice_tools._session_tasks.values():
            for task in bucket:
                task.cancel()
        voice_tools._session_tasks.clear()


def test_card_affecting_and_other_tools_are_disjoint() -> None:
    assert CARD_AFFECTING.isdisjoint(NOT_CARD_AFFECTING)


def test_only_card_affecting_tools_schedule_a_refresh() -> None:
    """Reads the wiring straight out of the source rather than mocking six calls.

    Each _schedule_context_refresh("<tool>") call names the tool that triggered
    it, so the set of names in the file IS the set of refreshing tools.
    """
    import inspect
    import re

    src = inspect.getsource(voice_tools.build_tools)
    scheduled = set(re.findall(r'_schedule_context_refresh\("(\w+)"\)', src))

    assert scheduled == CARD_AFFECTING, f"refresh wiring drifted: {scheduled}"


def test_refreshing_tools_suppress_the_redundant_delta() -> None:
    """The replaced card supersedes the delta; shipping both is a contradiction
    surface as well as wasted tokens."""
    import inspect
    import re

    src = inspect.getsource(voice_tools.build_tools)
    for tool in sorted(CARD_AFFECTING):
        pattern = rf'_announce\(result, "{tool}", inject_delta=False\)'
        assert re.search(pattern, src), f"{tool} still injects a delta alongside its refresh"


def test_flag_dispute_refreshes_the_card_without_blocking_its_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive the real handler, not a closure — this is the wiring that ships.

    Asserts both halves of the contract: the model gets its tool result
    immediately, and the refreshed card still lands.
    """
    from agent_core.tools import domain
    from agent_core.tools.domain import ToolResult
    from voice import persist

    monkeypatch.setattr(
        domain,
        "flag_dispute",
        lambda **_kw: ToolResult(
            ok=True,
            data={"disputeId": "DSP-1", "type": "paid_already"},
            entity="dispute",
            entity_id="DSP-1",
        ),
    )
    monkeypatch.setattr(persist, "record_handoff", lambda **_kw: None)

    replaced: list[tuple[str, dict]] = []
    refreshed = asyncio.Event()

    async def replace_developer(prefix: str, message: dict) -> None:
        replaced.append((prefix, message))
        refreshed.set()

    session = VoiceSession(session_id="VS-REFRESH01", customer_id="C1")
    session.identity_verified = True

    ctx = CallContext(
        channel="voice",
        session_id=session.session_id,
        interaction_id="IX-1",
        customer_id="C1",
        account_id=None,
        identity_verified=True,
    )
    refresh_calls: list[int] = []
    ctx.refresh_from_crm = lambda: refresh_calls.append(1)  # type: ignore[method-assign]

    async def scenario() -> tuple[dict, bool]:
        state, tools = voice_tools.build_tools(
            session,
            bot_id=None,
            start_recording=None,
            nodes={},
            replace_developer=replace_developer,
        )
        state.call_context = ctx

        result, _next_node = await tools["flag_dispute"].handler(
            {"dispute_type": "paid_already", "summary": "already paid"}, None
        )
        # Sampled the instant the handler returns.
        returned_before_refresh = not refreshed.is_set()

        await asyncio.wait_for(refreshed.wait(), timeout=5)
        await voice_tools.drain_background_tasks(session.session_id, timeout=2.0)
        return result, returned_before_refresh

    result, returned_before_refresh = asyncio.run(scenario())

    assert result["ok"] is True, result
    assert returned_before_refresh, "refresh blocked the tool result"
    assert refresh_calls == [1], "refresh_from_crm was not called"
    assert replaced and replaced[0][0] == CRM_CARD_PREFIX
    assert replaced[0][1]["role"] == "developer"


def test_refresh_is_a_noop_without_a_replacer() -> None:
    """A PSTN call with no injector must not crash on a write."""

    async def scenario() -> None:
        session = VoiceSession(session_id="VS-NOREPL001", customer_id="C1")
        state, _tools = voice_tools.build_tools(
            session, bot_id=None, start_recording=None, nodes={}
        )
        assert state.call_context is None

    asyncio.run(scenario())


def test_refresh_from_crm_still_hard_gates_on_verification() -> None:
    """The refresh path must not become a PII leak for an unverified caller."""
    ctx = CallContext(
        channel="voice",
        session_id="VS-UNVERIF01",
        interaction_id=None,
        customer_id="C1",
        account_id=None,
        identity_verified=False,
    )
    ctx.customer_card = {"name": "should not appear"}
    ctx.refresh_from_crm()
    assert "NO VERIFIED CUSTOMER FACTS" in ctx.crm_card()
