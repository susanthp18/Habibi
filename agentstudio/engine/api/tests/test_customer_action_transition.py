"""A rejected business write cannot enter an ordinary success closing node."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from api.services.workflow.pipecat_engine import PipecatEngine


@pytest.mark.asyncio
async def test_rejected_action_blocks_success_close_before_speech():
    engine = object.__new__(PipecatEngine)
    engine._engine_notes = []
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
    engine._engine_notes = []
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
    engine._engine_notes = []
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
    engine._engine_notes = []
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
    engine._engine_notes = []
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

    # Run 70: the question and a guessed call ("????") came in one response; the
    # refusal must not have it ask again over the customer's answer.
    engine._current_llm_generation_reference_text = "Could you tell me the last four digits?"
    await handler(SimpleNamespace(arguments={"value": "????"}, result_callback=callback))
    assert "say nothing more" in callback.await_args.args[0]["say"]
    engine._current_llm_generation_reference_text = ""

    engine.context.messages.append({"role": "user", "content": "2324"})
    await handler(SimpleNamespace(arguments={"value": "2324"}, result_callback=callback))
    execute.assert_awaited_once()

    # A retry needs a new answer, not the same message again.
    await handler(SimpleNamespace(arguments={"value": "2325"}, result_callback=callback))
    assert callback.await_args.args[0]["error"] == "no_new_digits_from_caller"
    assert execute.await_count == 1

    # Run 58: the digits came in the message that led into this step.
    given = {"role": "user", "content": "I think it is 2324."}
    engine.context.messages.append(given)
    engine._node_entry_user_message[("visit", "verify")] = given
    await handler(SimpleNamespace(arguments={"value": "2324"}, result_callback=callback))
    assert execute.await_count == 2
    # ...but not digits it doesn't hold.
    engine._verified_user_message = None
    await handler(SimpleNamespace(arguments={"value": "4821"}, result_callback=callback))
    assert callback.await_args.args[0]["error"] == "no_new_digits_from_caller"
    assert execute.await_count == 2


@pytest.mark.asyncio
async def test_a_write_needs_the_customer_to_speak_in_this_step(monkeypatch):
    from api.services.workflow import pipecat_engine_custom_tools as tools

    execute = AsyncMock(return_value={"status": "success", "data": {"ok": True}})
    monkeypatch.setattr(tools, "execute_http_tool", execute)
    engine = object.__new__(PipecatEngine)
    engine._engine_notes = []
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
    engine._engine_notes = []
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
    engine._engine_notes = []
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
    engine._engine_notes = []
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


@pytest.mark.asyncio
async def test_a_close_cannot_follow_its_own_unanswered_question():
    """Run 62: "Would you like me to record ... for then?" and No agreement in
    one response; the close hung up while the customer answered."""
    engine = object.__new__(PipecatEngine)
    engine._engine_notes = []
    engine._current_llm_generation_reference_text = ""
    engine._assistant_aggregator = None
    said = {"role": "user", "content": "May be 2 days before."}
    engine.context = SimpleNamespace(messages=[
        {"role": "user", "content": "No, actually I want to push it further for 2 days."},
        said,
        {"role": "assistant", "content": "Got it, that's Thursday, 8 October. Would you like me to record it?"},
    ])
    engine._node_entry_user_message = {}
    engine._context_summary_message = None
    engine._customer_action_outcomes = {}
    engine._verification_required = set()
    engine._verification_outcomes = {}
    engine._perform_variable_extraction_if_needed = AsyncMock()

    class Agent:
        visit_id = "visit"
        current_node = SimpleNamespace(id="agree")
        workflow = SimpleNamespace(nodes={"end": SimpleNamespace(is_end=True)})

        def bind_tool(self, _engine, handler):
            return handler

    handler = await engine._create_transition_func("No agreement", "end", agent=Agent())
    callback = AsyncMock()
    await handler(SimpleNamespace(arguments={}, result_callback=callback))
    assert callback.await_args.args[0]["error"] == "question_unanswered"

    # Once the customer has answered, the close is allowed again.
    engine.context.messages.append({"role": "user", "content": "No, leave it."})
    engine._active_agent = Agent()
    engine._run_transition_variable_extraction_in_background = False
    engine.set_node = AsyncMock()
    engine.arm_speech_playback = Mock()
    await handler(SimpleNamespace(arguments={}, result_callback=callback))
    engine.set_node.assert_awaited_once_with("end", origin_visit_id="visit")


def test_guard_state_survives_a_text_chat_turn():
    # Text chat rebuilds the engine per message: verification must carry over,
    # or a released agent refuses every promise after the verifying turn.
    def engine_on(messages, visit):
        engine = object.__new__(PipecatEngine)
        engine._engine_notes = []
        engine.context = SimpleNamespace(messages=messages)
        engine._active_agent = SimpleNamespace(visit_id=visit, current_node=SimpleNamespace(id="resolve"))
        engine._verification_outcomes = {}
        engine._customer_action_outcomes = {}
        engine._node_entry_user_message = {}
        engine._verified_user_message = None
        engine._written_user_message = None
        engine._opt_out_visits = set()
        return engine

    digits = {"role": "user", "content": "1234"}
    first = engine_on([{"role": "user", "content": "hi"}, digits], "visit-1")
    first._verification_outcomes[("visit-1", "verify")] = True
    first._node_entry_user_message[("visit-1", "resolve")] = digits
    first._verified_user_message = digits
    first._opt_out_visits.add("visit-1")
    state = first.export_guard_state()

    restored = [{"role": "user", "content": "hi"}, {"role": "user", "content": "1234"}]
    second = engine_on(restored, "visit-2")
    second.import_guard_state(state)
    assert second._verification_outcomes[("visit-2", "resolve")] is True
    assert second._node_entry_user_message[("visit-2", "resolve")] is restored[1]
    assert second._verified_user_message is restored[1]
    assert "visit-2" in second._opt_out_visits


@pytest.mark.asyncio
async def test_an_unheard_turn_is_answered_and_is_not_the_caller():
    # Run 51: "yes" and "ok" were not transcribed, nothing answered them, and
    # the call sat silent until the customer hung up.
    engine = object.__new__(PipecatEngine)
    engine._engine_notes = []
    engine._unheard_turns = 0
    engine._call_disposed = False
    engine._agent_on_hold = False
    engine.answer_supervisor = None
    engine._context_summary_message = None
    engine.context = SimpleNamespace(messages=[{"role": "user", "content": "Hello?"}])
    aggregator = SimpleNamespace(push_frame=AsyncMock())

    for _ in range(3):
        await engine.handle_user_turn_stopped(aggregator, "")
    # Asked twice; a third silent turn is noise and left to idle handling.
    assert aggregator.push_frame.await_count == 2
    note = aggregator.push_frame.await_args.args[0].messages[0]
    engine.context.messages.append(note)
    # The note asks the model to speak; it is not the caller speaking.
    assert engine._last_user_message()["content"] == "Hello?"

    await engine.handle_user_turn_stopped(aggregator, "yes speaking")
    assert engine._unheard_turns == 0


@pytest.mark.asyncio
async def test_a_transfer_needs_the_caller_to_ask_in_this_step():
    # An inbound agent reached for a colleague in its opening turn.
    from api.services.workflow import pipecat_engine_custom_tools as tools

    engine = object.__new__(PipecatEngine)
    engine._engine_notes = []
    engine._current_llm_generation_reference_text = ""
    engine._assistant_aggregator = None
    engine._context_summary_message = None
    engine.context = SimpleNamespace(messages=[])
    engine._node_entry_user_message = {("visit", "greeting"): None}
    agent = SimpleNamespace(visit_id="visit", current_node=SimpleNamespace(id="greeting"))
    manager = tools.CustomToolManager(engine, agent)
    handler = manager._create_transfer_call_handler(SimpleNamespace(definition={"config": {}}), "transfer_to_human")
    callback = AsyncMock()
    await handler(SimpleNamespace(arguments={"reason": "x"}, result_callback=callback))
    assert callback.await_args.args[0]["error"] == "customer_did_not_ask"


@pytest.mark.asyncio
async def test_a_transfer_needs_the_customer_to_want_a_person():
    """Run 68: "Tell me all" about exclusions was answered with a transfer."""
    from api.services.workflow import pipecat_engine_custom_tools as tools

    engine = object.__new__(PipecatEngine)
    engine._engine_notes = []
    engine._current_llm_generation_reference_text = ""
    engine._assistant_aggregator = None
    engine._context_summary_message = None
    said = {"role": "user", "content": "Tell me all"}
    engine.context = SimpleNamespace(messages=[
        {"role": "assistant", "content": "Would you like help finding a specific exclusion?"}, said])
    engine._node_entry_user_message = {("visit", "help"): None}
    asked = []

    async def run_inference(context, **_kw):
        asked.append(context.messages[0]["content"])
        return "NO"

    agent = SimpleNamespace(visit_id="visit", current_node=SimpleNamespace(id="help"),
                            llm=SimpleNamespace(run_inference=run_inference))
    manager = tools.CustomToolManager(engine, agent)
    handler = manager._create_transfer_call_handler(SimpleNamespace(definition={"config": {}}), "transfer_to_human")
    callback = AsyncMock()
    await handler(SimpleNamespace(arguments={"reason": "full exclusions"}, result_callback=callback))
    assert callback.await_args.args[0]["error"] == "customer_did_not_ask_for_a_person"
    assert "Customer: Tell me all" in asked[0] and "specific exclusion" in asked[0]

    # A failed check lets a real request through.
    async def broken(*_a, **_kw):
        raise TimeoutError
    agent.llm = SimpleNamespace(run_inference=broken)
    assert await manager._customer_wants_a_person() is True


@pytest.mark.asyncio
async def test_an_opted_out_close_needs_the_opt_out():
    """Run 66: "No need to call me" (declining a callback) closed on Stop contact
    with no record_opt_out, and the promise was never recorded."""
    engine = object.__new__(PipecatEngine)
    engine._engine_notes = []
    engine._current_llm_generation_reference_text = ""
    engine._assistant_aggregator = None
    engine.context = SimpleNamespace(messages=[
        {"role": "user", "content": "I will pay the entire 4000 by 8 October. No need to call me."}])
    engine._node_entry_user_message = {}
    engine._context_summary_message = None
    engine._customer_action_outcomes = {}
    engine._verification_required = set()
    engine._verification_outcomes = {}
    engine._opt_out_visits = set()
    engine._perform_variable_extraction_if_needed = AsyncMock()

    class Agent:
        visit_id = "visit"
        current_node = SimpleNamespace(id="hardship")
        workflow = SimpleNamespace(nodes={"stop": SimpleNamespace(is_end=True, call_disposition="opted_out")})

        def bind_tool(self, _engine, handler):
            return handler

    handler = await engine._create_transition_func("Stop contact", "stop", agent=Agent())
    callback = AsyncMock()
    await handler(SimpleNamespace(arguments={}, result_callback=callback))
    assert callback.await_args.args[0]["error"] == "opt_out_not_recorded"

    engine._opt_out_visits.add("visit")  # record_opt_out was called
    engine._active_agent = Agent()
    engine._run_transition_variable_extraction_in_background = False
    engine.set_node = AsyncMock()
    engine.arm_speech_playback = Mock()
    await handler(SimpleNamespace(arguments={}, result_callback=callback))
    engine.set_node.assert_awaited_once_with("stop", origin_visit_id="visit")


def _verify_engine(edges, nodes):
    engine = object.__new__(PipecatEngine)
    engine._run_transition_variable_extraction_in_background = True
    engine._perform_variable_extraction_if_needed = AsyncMock()
    engine.set_node = AsyncMock()
    agent = SimpleNamespace(
        visit_id="visit",
        current_node=SimpleNamespace(id="verify", out_edges=edges),
        workflow=SimpleNamespace(nodes=nodes),
    )
    return engine, agent


def _edge(target, **data):
    flags = {"requires_user_turn": False, "requires_successful_action": False,
             "transition_speech_recording_id": None, **data}
    return SimpleNamespace(target=target, transition_speech=None, data=SimpleNamespace(**flags))


@pytest.mark.asyncio
async def test_verified_takes_the_only_onward_edge():
    nodes = {"account": SimpleNamespace(is_end=False), "close": SimpleNamespace(is_end=True)}
    engine, agent = _verify_engine([_edge("account"), _edge("close")], nodes)
    assert await engine.advance_after_verification(agent) is True
    engine.set_node.assert_awaited_once_with("account", origin_visit_id="visit")


@pytest.mark.asyncio
async def test_verified_leaves_a_real_choice_to_the_model():
    nodes = {"a": SimpleNamespace(is_end=False), "b": SimpleNamespace(is_end=False)}
    engine, agent = _verify_engine([_edge("a"), _edge("b")], nodes)
    assert await engine.advance_after_verification(agent) is False
    engine, agent = _verify_engine([_edge("a", requires_user_turn=True)], nodes)
    assert await engine.advance_after_verification(agent) is False
    engine.set_node.assert_not_awaited()


@pytest.mark.asyncio
async def test_success_edge_is_taken_once_the_action_is_recorded():
    nodes = {"wrap": SimpleNamespace(is_end=False), "stands": SimpleNamespace(is_end=False)}
    edges = [_edge("wrap", requires_successful_action=True), _edge("stands")]
    engine, agent = _verify_engine(edges, nodes)
    assert await engine.advance_after_action(agent) is True
    engine.set_node.assert_awaited_once_with("wrap", origin_visit_id="visit")
    # ...but not into a close, and verification's advance leaves it alone.
    engine, agent = _verify_engine([_edge("bye", requires_successful_action=True)],
                                   {"bye": SimpleNamespace(is_end=True)})
    assert await engine.advance_after_action(agent) is False
    engine, agent = _verify_engine([_edge("wrap", requires_successful_action=True)], nodes)
    assert await engine.advance_after_verification(agent) is False


@pytest.mark.asyncio
async def test_no_goodbye_straight_after_the_customers_question():
    """Run 84: "What is the premium?" and the agent's next words were its goodbye."""
    engine = object.__new__(PipecatEngine)
    engine._engine_notes = []
    engine._current_llm_generation_reference_text = ""
    engine._assistant_aggregator = None
    engine._context_summary_message = None
    engine.context = SimpleNamespace(messages=[{"role": "user", "content": "What is the premium?"}])
    engine._node_entry_user_message = {}
    engine._customer_action_outcomes = {}
    engine._verification_required = set()
    engine._verification_outcomes = {}
    engine._perform_variable_extraction_if_needed = AsyncMock()

    class Agent:
        visit_id = "visit"
        current_node = SimpleNamespace(id="wrap")
        workflow = SimpleNamespace(nodes={"bye": SimpleNamespace(is_end=True, call_disposition=None)})

        def bind_tool(self, _engine, handler):
            return handler

    handler = await engine._create_transition_func("Goodbye", "bye", agent=Agent())
    callback = AsyncMock()
    await handler(SimpleNamespace(arguments={}, result_callback=callback))
    assert callback.await_args.args[0]["error"] == "customer_question_unanswered"


@pytest.mark.asyncio
async def test_no_bounce_back_to_the_step_just_left_without_the_caller():
    """Run 88: Agree -> Hardship -> Agree -> Hardship on one "I can only do 2000 this week"."""
    engine = object.__new__(PipecatEngine)
    engine._engine_notes = []
    engine._current_llm_generation_reference_text = ""
    engine._assistant_aggregator = None
    offer = {"role": "user", "content": "I can only do 2000 this week."}
    engine.context = SimpleNamespace(messages=[offer])
    engine._node_entry_user_message = {("visit", "hardship"): offer}
    engine._node_left_user_message = {("visit", "agree"): offer}  # left Agree on this very message
    engine._context_summary_message = None
    engine._customer_action_outcomes = {}
    engine._verification_required = set()
    engine._verification_outcomes = {}
    engine._perform_variable_extraction_if_needed = AsyncMock()
    engine._run_transition_variable_extraction_in_background = False
    engine.set_node = AsyncMock()

    class Agent:
        visit_id = "visit"
        current_node = SimpleNamespace(id="hardship")
        workflow = SimpleNamespace(nodes={"agree": SimpleNamespace(is_end=False)})

        def bind_tool(self, _engine, handler):
            return handler

    engine._active_agent = Agent()
    handler = await engine._create_transition_func("Discuss payment", "agree", agent=Agent())
    callback = AsyncMock()
    await handler(SimpleNamespace(arguments={}, result_callback=callback))
    assert callback.await_args.args[0]["error"] == "node_bounce"
    engine.set_node.assert_not_awaited()

    # The caller answers the hardship offer with a payment: now it may go back.
    engine.context.messages.append({"role": "user", "content": "Actually, 2500 on Friday and 2500 next Tuesday."})
    await handler(SimpleNamespace(arguments={}, result_callback=callback))
    engine.set_node.assert_awaited_once_with("agree", origin_visit_id="visit")


def test_digits_count_as_numerals_or_words_the_caller_said():
    from api.services.workflow.pipecat_engine_custom_tools import _heard_digits

    assert _heard_digits("2324.") == "2324" and _heard_digits("1111।") == "1111"
    assert _heard_digits("two three two four") == "2324"
    assert _heard_digits("double two three four") == "2234"
    assert _heard_digits("दो तीन दो चार") == "2324"
    assert _heard_digits("இரண்டு மூணு ரெண்டு நாலு") == "2324"
    assert _heard_digits("டூ த்ரீ டூ ஃபோர்") == "2324"  # English, written in Tamil script
    assert _heard_digits("I don't understand.") == ""


@pytest.mark.asyncio
async def test_a_guess_after_an_unrelated_answer_is_not_checked(monkeypatch):
    """Codex F15: any new message in the step let model-supplied digits through."""
    from api.services.workflow import pipecat_engine_custom_tools as tools

    execute = AsyncMock(return_value={"status": "success", "data": {"ok": True, "verified": False}})
    monkeypatch.setattr(tools, "execute_http_tool", execute)
    engine = object.__new__(PipecatEngine)
    engine._engine_notes = []
    engine._current_llm_generation_reference_text = ""
    engine._assistant_aggregator = None
    yes = {"role": "user", "content": "Yes, speaking"}
    engine.context = SimpleNamespace(messages=[yes, {"role": "user", "content": "I don't understand."}])
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
    handler = manager._create_http_tool_handler(
        SimpleNamespace(definition={"config": {}}, policy=None, revision_id=None), "verify_identity")
    callback = AsyncMock()

    await handler(SimpleNamespace(arguments={"value": "2324"}, result_callback=callback))
    assert callback.await_args.args[0]["error"] == "no_new_digits_from_caller"
    execute.assert_not_awaited()

    engine.context.messages.append({"role": "user", "content": "two three two four"})
    await handler(SimpleNamespace(arguments={"value": "2324"}, result_callback=callback))
    execute.assert_awaited_once()


def test_digits_survive_separators():
    """Codex review of run 88: "2,324" and "2-3-2-4" read as no digits at all."""
    from api.services.workflow.pipecat_engine_custom_tools import _heard_digits

    assert _heard_digits("2,324") == "2324"
    assert _heard_digits("2-3-2-4") == "2324"
    assert _heard_digits("two-three-two-four") == "2324"


def test_only_a_clear_yes_to_the_terms_is_agreement():
    """Codex F16 and its review: a new message was enough ("No, don't record
    that"), then a refusal list still let "Maybe" or "I cannot pay that" write."""
    from api.services.workflow.pipecat_engine_custom_tools import _agreed, _held

    terms = {"amount": 5000, "date": "2026-10-07",
             "parts": [{"amount": 2500, "date": "2026-10-02"}, {"amount": 2500, "date": "2026-10-07"}]}
    for said in ("No, don't record that.", "नहीं", "Wait, let me check.", "Actually, 3000 on Friday.",
                 "I cannot pay that.", "I will not pay that.", "Maybe.", "What does that mean?",
                 "Actually, two thousand on Friday.", "Yes, two thousand on Friday.", "Yes, but 3000.",
                 "Okay?", "Yes, I'm not sure.", "I can pay on Friday."):
        assert not _agreed(said, terms), said
    for said in ("Yes.", "யெஸ்", "हाँ जी", "சரி", "No problem, record it.", "Okay, go ahead.",
                 "Yes, 2500 on the 2nd and the rest on the 7th.", "Yes, that's right."):
        assert _agreed(said, terms), said
    assert _agreed("Yes, 5 pm is fine.", {"time": "2026-10-02T17:00:00+05:30"})
    # The dispute step files on the customer's own account, a "no" and all; only a pause holds it.
    assert not _held("No, I never took this loan.")
    assert _held("Wait, let me check my statement.")
