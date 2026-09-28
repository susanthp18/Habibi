"""A rejected business write cannot enter an ordinary success closing node."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from api.services.workflow.pipecat_engine import PipecatEngine


@pytest.mark.asyncio
async def test_rejected_action_blocks_success_close_before_speech():
    engine = object.__new__(PipecatEngine)
    engine._current_llm_generation_reference_text = ""
    engine._assistant_aggregator = None
    engine.context = SimpleNamespace(messages=[{"role": "user", "content": "Yes, go ahead"}])
    engine._node_entry_user_message = {}
    engine._context_summary_message = None
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
    engine._current_llm_generation_reference_text = ""
    engine._assistant_aggregator = None
    engine._customer_action_outcomes = {}
    engine.context = SimpleNamespace(messages=[{"role": "user", "content": "1234"}])
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
    callback.assert_awaited_once()
    assert callback.await_args.args[0]["error"] == "identity_not_verified"
    engine._perform_variable_extraction_if_needed.assert_not_awaited()


@pytest.mark.asyncio
async def test_right_person_requires_a_caller_turn_when_edge_requests_it():
    engine = object.__new__(PipecatEngine)
    engine._current_llm_generation_reference_text = ""
    engine._assistant_aggregator = None
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

    callback.assert_awaited_once()
    assert callback.await_args.args[0]["error"] == "user_turn_required"
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
    engine._current_llm_generation_reference_text = ""
    engine._assistant_aggregator = None
    engine.context = SimpleNamespace(messages=[{"role": "user", "content": "Yes, go ahead"}])
    engine._node_entry_user_message = {}
    engine._context_summary_message = None
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

    callback.assert_awaited_once()
    assert callback.await_args.args[0]["error"] == "successful_action_required"
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
    engine._current_llm_generation_reference_text = ""
    engine._assistant_aggregator = None
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


@pytest.mark.asyncio
async def test_a_write_needs_the_customer_to_speak_in_this_step(monkeypatch):
    from api.services.workflow import pipecat_engine_custom_tools as tools

    execute = AsyncMock(return_value={"status": "success", "data": {"ok": True}})
    monkeypatch.setattr(tools, "execute_http_tool", execute)
    engine = object.__new__(PipecatEngine)
    engine._current_llm_generation_reference_text = ""
    engine._assistant_aggregator = None
    digits = {"role": "user", "content": "1234"}
    engine.context = SimpleNamespace(messages=[digits])
    # The step began after the customer's last message: nothing is confirmed here.
    engine._node_entry_user_message = {("visit", "resolve"): digits}
    engine._context_summary_message = None
    engine._verified_user_message = None
    engine._written_user_message = None
    engine._assistant_aggregator = SimpleNamespace(_aggregation=[])
    engine._verification_outcomes = {}
    engine._customer_action_outcomes = {}
    engine._call_context_vars = {}
    engine._gathered_context = {}
    agent = SimpleNamespace(visit_id="visit", current_node=SimpleNamespace(id="resolve"))
    manager = tools.CustomToolManager(engine, agent)
    manager.get_organization_id = AsyncMock(return_value=1)
    tool = SimpleNamespace(definition={"config": {}}, policy=None, revision_id=None)
    handler = manager._create_http_tool_handler(tool, "promise_to_pay")
    callback = AsyncMock()

    await handler(SimpleNamespace(arguments={"amount": 6000, "date": "2026-10-02"}, result_callback=callback))
    assert callback.await_args.args[0]["error"] == "customer_not_confirmed"
    execute.assert_not_awaited()

    # "I can pay 4000", then a read-back and the write in one response: refused,
    # and that message is spent, so an immediate retry is refused too.
    engine.context.messages.append({"role": "user", "content": "I can pay 4000 on Friday"})
    engine._assistant_aggregator._aggregation = ["Shall I record 4,000 for Fri 2 Oct?"]
    await handler(SimpleNamespace(arguments={"amount": 4000, "date": "2026-10-02"}, result_callback=callback))
    assert callback.await_args.args[0]["error"] == "customer_not_confirmed"
    engine._assistant_aggregator._aggregation = []
    await handler(SimpleNamespace(arguments={"amount": 4000, "date": "2026-10-02"}, result_callback=callback))
    assert callback.await_args.args[0]["error"] == "customer_not_confirmed"
    execute.assert_not_awaited()

    engine.context.messages.append({"role": "user", "content": "Yes"})
    await handler(SimpleNamespace(arguments={"amount": 4000, "date": "2026-10-02"}, result_callback=callback))
    execute.assert_awaited_once()


def test_a_refusal_after_speech_asks_for_silence_not_a_repeat():
    engine = object.__new__(PipecatEngine)
    engine._assistant_aggregator = None
    engine._current_llm_generation_reference_text = ""
    engine.context = SimpleNamespace(messages=[{"role": "user", "content": "Hello?"}])
    assert "Finish your turn" in engine._refusal_hint("The customer has not answered yet.")
    # The greeting was already said in this response: saying it again doubled it.
    engine._current_llm_generation_reference_text = "Hello, may I speak with Susanth?"
    assert "say nothing more" in engine._refusal_hint("The customer has not answered yet.")


def test_text_already_in_context_counts_as_speaking():
    # Text chat commits the response's words before its tool calls run.
    engine = object.__new__(PipecatEngine)
    engine._assistant_aggregator = None
    engine._current_llm_generation_reference_text = ""
    engine.context = SimpleNamespace(messages=[
        {"role": "user", "content": "I can pay 2100"},
        {"role": "assistant", "content": "Shall I record 2,100 for Fri 2 Oct?"},
        {"role": "assistant", "tool_calls": [{"id": "1"}]},
    ])
    assert engine.agent_spoke_since_customer()
    engine.context.messages.append({"role": "user", "content": "yes"})
    assert not engine.agent_spoke_since_customer()


@pytest.mark.asyncio
async def test_a_close_needs_the_customer_to_speak_in_this_step():
    engine = object.__new__(PipecatEngine)
    engine._current_llm_generation_reference_text = ""
    engine._assistant_aggregator = None
    question = {"role": "user", "content": "1234"}
    engine.context = SimpleNamespace(messages=[question])
    # Hardship was entered on the customer's last message; nobody has answered since.
    engine._node_entry_user_message = {("visit", "hardship"): question}
    engine._context_summary_message = None
    engine._customer_action_outcomes = {}
    engine._verification_required = set()
    engine._verification_outcomes = {}
    engine._perform_variable_extraction_if_needed = AsyncMock()

    class Agent:
        visit_id = "visit"
        current_node = SimpleNamespace(id="hardship")
        workflow = SimpleNamespace(nodes={"end": SimpleNamespace(is_end=True)})

        def bind_tool(self, _engine, handler):
            return handler

    handler = await engine._create_transition_func("No agreement", "end", agent=Agent())
    callback = AsyncMock()
    await handler(SimpleNamespace(arguments={}, result_callback=callback))
    assert callback.await_args.args[0]["error"] == "user_turn_required"
    engine._perform_variable_extraction_if_needed.assert_not_awaited()
