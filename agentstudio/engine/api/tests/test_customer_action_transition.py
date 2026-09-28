"""A rejected business write cannot enter an ordinary success closing node."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

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


@pytest.mark.asyncio
async def test_right_person_requires_a_caller_turn_when_edge_requests_it():
    engine = object.__new__(PipecatEngine)
    hello = {"role": "user", "content": "Hello?"}
    engine.context = SimpleNamespace(messages=[hello])
    # "Hello?" on pickup came before the node began: it answers nothing.
    engine._node_entry_user_message = {("visit", "start"): hello}
    engine._context_summary_message = None
    engine._customer_action_outcomes = {}
    engine._verification_required = set()
    engine._verification_outcomes = {}
    engine._perform_variable_extraction_if_needed = AsyncMock()

    class Agent:
        visit_id = "visit"
        current_node = SimpleNamespace(id="start")
        workflow = SimpleNamespace(nodes={"verify": SimpleNamespace(is_end=False)})

        def bind_tool(self, _engine, handler):
            return handler

    handler = await engine._create_transition_func(
        "Right person", "verify", requires_user_turn=True, agent=Agent()
    )
    callback = AsyncMock()
    await handler(SimpleNamespace(arguments={}, result_callback=callback))

    callback.assert_awaited_once_with({"status": "error", "error": "user_turn_required"})
    engine._perform_variable_extraction_if_needed.assert_not_awaited()

    engine.context.messages.append({"role": "user", "content": "Yes, speaking"})
    engine._active_agent = Agent()
    engine._run_transition_variable_extraction_in_background = False
    engine.set_node = AsyncMock()
    await handler(SimpleNamespace(arguments={}, result_callback=callback))
    engine.set_node.assert_awaited_once_with("verify", origin_visit_id="visit")


@pytest.mark.asyncio
async def test_agreed_requires_a_recorded_success_when_edge_requests_it():
    engine = object.__new__(PipecatEngine)
    engine._customer_action_outcomes = {}
    engine._verification_required = set()
    engine._verification_outcomes = {}
    engine._perform_variable_extraction_if_needed = AsyncMock()

    class Agent:
        visit_id = "visit"
        current_node = SimpleNamespace(id="resolve")
        workflow = SimpleNamespace(nodes={"end": SimpleNamespace(is_end=True)})

        def bind_tool(self, _engine, handler):
            return handler

    handler = await engine._create_transition_func(
        "Agreed", "end", requires_successful_action=True, agent=Agent()
    )
    callback = AsyncMock()
    await handler(SimpleNamespace(arguments={}, result_callback=callback))

    callback.assert_awaited_once_with({
        "status": "error", "error": "successful_action_required",
    })
    engine._perform_variable_extraction_if_needed.assert_not_awaited()

    engine._customer_action_outcomes[("visit", "resolve")] = True
    engine._active_agent = Agent()
    engine._run_transition_variable_extraction_in_background = False
    engine.set_node = AsyncMock()
    engine.arm_speech_playback = Mock()
    await handler(SimpleNamespace(arguments={}, result_callback=callback))
    engine.set_node.assert_awaited_once_with("end", origin_visit_id="visit")


@pytest.mark.asyncio
async def test_verify_identity_needs_digits_the_caller_just_gave(monkeypatch):
    from api.services.workflow import pipecat_engine_custom_tools as tools

    execute = AsyncMock(return_value={"status": "success", "data": {"ok": True, "verified": False}})
    monkeypatch.setattr(tools, "execute_http_tool", execute)
    engine = object.__new__(PipecatEngine)
    yes = {"role": "user", "content": "Yes, speaking"}
    engine.context = SimpleNamespace(messages=[yes])
    engine._node_entry_user_message = {("visit", "verify"): yes}
    engine._context_summary_message = None
    engine._verified_user_message = None
    engine._verification_outcomes = {}
    engine._customer_action_outcomes = {}
    engine._call_context_vars = {}
    engine._gathered_context = {}
    agent = SimpleNamespace(visit_id="visit", current_node=SimpleNamespace(id="verify"))
    manager = tools.CustomToolManager(engine, agent)
    manager.get_organization_id = AsyncMock(return_value=1)
    tool = SimpleNamespace(definition={"config": {}}, policy=None, revision_id=None)
    handler = manager._create_http_tool_handler(tool, "verify_identity")
    callback = AsyncMock()

    # The opening turn: nothing said since the node began, so no call.
    await handler(SimpleNamespace(arguments={"value": "4821"}, result_callback=callback))
    assert callback.await_args.args[0]["error"] == "no_new_digits_from_caller"
    execute.assert_not_awaited()

    engine.context.messages.append({"role": "user", "content": "2324"})
    await handler(SimpleNamespace(arguments={"value": "2324"}, result_callback=callback))
    execute.assert_awaited_once()

    # A retry needs a new answer, not the same message again.
    await handler(SimpleNamespace(arguments={"value": "2325"}, result_callback=callback))
    assert callback.await_args.args[0]["error"] == "no_new_digits_from_caller"
    assert execute.await_count == 1
