"""A rejected business write cannot enter an ordinary success closing node."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.workflow.pipecat_engine import PipecatEngine


@pytest.mark.asyncio
async def test_rejected_action_blocks_success_close_before_speech():
    engine = object.__new__(PipecatEngine)
    engine._customer_action_outcomes = {("visit", "resolve"): False}
    engine._verification_required = set()
    engine._verification_outcomes = {}
    engine._perform_variable_extraction_if_needed = AsyncMock()
    end = SimpleNamespace(is_end=True)

    class Agent:
        visit_id = "visit"
        current_node = SimpleNamespace(id="resolve")
        workflow = SimpleNamespace(nodes={"end": end})

        def bind_tool(self, _engine, handler):
            return handler

    handler = await engine._create_transition_func("Agreed", "end", agent=Agent())
    callback = AsyncMock()
    await handler(SimpleNamespace(arguments={}, result_callback=callback))

    callback.assert_awaited_once_with({
        "status": "error", "error": "action_failed_no_success_transition",
    })
    engine._perform_variable_extraction_if_needed.assert_not_awaited()


@pytest.mark.asyncio
async def test_unverified_identity_blocks_account_path():
    engine = object.__new__(PipecatEngine)
    engine._customer_action_outcomes = {}
    engine._verification_required = {("visit", "verify")}
    engine._verification_outcomes = {("visit", "verify"): False}
    engine._perform_variable_extraction_if_needed = AsyncMock()
    account = SimpleNamespace(is_end=False)

    class Agent:
        visit_id = "visit"
        current_node = SimpleNamespace(id="verify")
        workflow = SimpleNamespace(nodes={"account": account})

        def bind_tool(self, _engine, handler):
            return handler

    handler = await engine._create_transition_func("Verified", "account", agent=Agent())
    callback = AsyncMock()
    await handler(SimpleNamespace(arguments={}, result_callback=callback))
    callback.assert_awaited_once_with({"status": "error", "error": "identity_not_verified"})
    engine._perform_variable_extraction_if_needed.assert_not_awaited()
