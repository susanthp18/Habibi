"""The goal-first opening: ask why they called, then verify, then serve.

These lock in the fix for a live sandbox call on 2026-08-01 whose entire
customer-facing opening was authored rather than reasoned:

    Bot: Hello, thanks for calling HDFC Bank collections — this call is
         recorded for quality and compliance.
    Bot: I understand you're upset.
    Bot: For security, could you please share the last 4 digits...

The caller had not spoken. Two independent defects produced that: the sandbox
persona stated a mood as fact at turn 0, and the graph had no node in which the
caller could say why they rang, so it marched greet → verify → recite balance.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_core.context import CallContext
from voice.flows import build_collections_flow
from voice.session import VoiceSession


def _flow(*, goal=None, intent=None, graph="legacy"):
    session = VoiceSession(session_id="VS-GOALTEST1")
    session.call_goal = goal
    session.call_goal_intent = intent
    state, tools, initial, globals_ = build_collections_flow(
        session, role_message="role", graph=graph
    )
    return session, state, tools, initial


def _task(state, node: str) -> str:
    return state.nodes[node]()["task_messages"][0]["content"].lower()


def _names(functions) -> set[str]:
    return {getattr(f, "name", None) or f.__name__ for f in functions}


# --------------------------------------------------------------- graph shape


@pytest.mark.parametrize("graph", ["legacy", "hub"])
def test_discover_intent_sits_between_greeting_and_verification(graph: str) -> None:
    _session, state, _tools, _initial = _flow(graph=graph)
    assert "discover_intent" in state.nodes


@pytest.mark.parametrize("graph", ["legacy", "hub"])
def test_greeting_opens_the_floor_without_asking_for_digits(graph: str) -> None:
    """Greeting, disclosure and "what do you need?" in one breath — the way a
    person opens a call. It used to hand straight to the identity node, which
    is what made the call feel like a form."""
    _session, state, _tools, _initial = _flow(graph=graph)
    greet = _task(state, "greet_disclose")
    assert "recorded for quality and compliance" in greet
    assert "what they need help with today" in greet
    assert "ask for no digits" in greet


@pytest.mark.parametrize("graph", ["legacy", "hub"])
def test_greeting_claims_no_call_direction(graph: str) -> None:
    """Nothing in the system models who dialled whom, so the model guessed —
    and got it wrong in both directions across runs ("thanks for calling" on an
    outbound dial, "I'm calling from" on an inbound one)."""
    greet = _task(_flow(graph=graph)[1], "greet_disclose")
    assert "thanks for calling" in greet and "i'm calling from" in greet
    assert "do not say" in greet


def test_discover_intent_listens_rather_than_asking_again() -> None:
    """respond_immediately=False is the point. The greeting already ends on the
    open question; speaking on arrival here asked it twice in a row, which is
    exactly what the first build of this node did."""
    _session, state, _tools, _initial = _flow()
    node = state.nodes["discover_intent"]()
    task = node["task_messages"][0]["content"].lower()

    assert node["respond_immediately"] is False
    assert "do not ask again" in task
    # The failure mode being guarded is the bot supplying the reason itself.
    assert "do not guess why they called" in task
    assert "capture_call_goal" in _names(node["functions"])


def test_no_account_tools_before_verification() -> None:
    """Compliance is unchanged by moving the question earlier: discover_intent
    may reach the KB (a policy question needs no account) but must not carry a
    CRM read."""
    _session, state, _tools, _initial = _flow()
    local = _names(state.nodes["discover_intent"]()["functions"])
    assert "get_account_position" not in local
    assert "get_customer_context" not in local
    assert "verify_identity" not in local


# ---------------------------------------------------------- goal conditioning


@pytest.mark.parametrize("graph,hub", [("legacy", "state_position"), ("hub", "collections_hub")])
def test_absent_goal_preserves_the_old_wording_exactly(graph: str, hub: str) -> None:
    """An outbound call, or a caller who never says why, still gets the
    position first. The change must not cost that."""
    _session, state, _tools, _initial = _flow(graph=graph)
    assert "call get_account_position first" in _task(state, hub)


@pytest.mark.parametrize("graph,hub", [("legacy", "state_position"), ("hub", "collections_hub")])
def test_non_money_goal_suppresses_the_unprompted_balance(graph: str, hub: str) -> None:
    _session, state, _tools, _initial = _flow(
        goal="dispute a late fee", intent="dispute", graph=graph
    )
    task = _task(state, hub)
    assert "dispute a late fee" in task
    assert "do not recite the outstanding balance unless they ask" in task
    assert "call get_account_position first" not in task


@pytest.mark.parametrize("intent", ["payment", "promise_to_pay", "hardship", "balance"])
def test_money_goal_still_states_the_position_first(intent: str) -> None:
    _session, state, _tools, _initial = _flow(goal="pay my EMI today", intent=intent)
    assert "call get_account_position first" in _task(state, "state_position")


def test_verification_is_framed_around_the_stated_goal() -> None:
    _session, state, _tools, _initial = _flow(goal="dispute a late fee", intent="dispute")
    task = _task(state, "verify_identity")
    assert "dispute a late fee" in task
    assert task.index("dispute a late fee") < task.index("last 4 digits")


def test_verification_without_a_goal_is_unchanged() -> None:
    _session, state, _tools, _initial = _flow()
    assert _task(state, "verify_identity").startswith("speak first")


# ----------------------------------------------------------- capture_call_goal


def test_capture_call_goal_records_and_moves_to_verification() -> None:
    session, state, tools, _initial = _flow()
    handler = tools["capture_call_goal"].handler

    result, node = asyncio.run(handler({"goal_summary": "dispute a late fee"}, None))

    assert result["ok"] is True
    assert session.call_goal == "dispute a late fee"
    # Classified, not left blank — the keyword baseline stands until the LLM
    # refinement for this turn lands on the analysis queue.
    assert session.call_goal_intent
    assert node["name"] == "verify_identity"


def test_capture_call_goal_refuses_a_question_about_the_call_itself() -> None:
    """"What all can you do?" is not why anyone rang.

    On VS-6B252E0479 it was filed as the call goal and then drove both the
    balance-suppression rule and the idle re-engagement prompt for the rest of
    the call — the nudge re-answered the capability question instead of picking
    the real thread back up. The gate reuses the intent classifier that already
    runs on every turn rather than matching the phrasing.
    """
    session, _state, tools, _initial = _flow()
    handler = tools["capture_call_goal"].handler

    result, node = asyncio.run(handler({"goal_summary": "what all can you do"}, None))

    assert result["ok"] is False
    assert result["reason"] == "not_a_call_goal"
    assert session.call_goal is None
    # Stays put: the model answers, then keeps listening for the real reason.
    assert node is None


def test_capture_call_goal_refuses_an_empty_goal() -> None:
    """The model must not be able to advance the call by inventing a reason."""
    session, _state, tools, _initial = _flow()
    handler = tools["capture_call_goal"].handler

    result, node = asyncio.run(handler({"goal_summary": "   "}, None))

    assert result["error"] == "empty_goal"
    assert node is None
    assert session.call_goal is None


def test_capture_call_goal_records_the_turn_for_later_refinement() -> None:
    session, _state, tools, _initial = _flow()
    session.turn_index = 3
    handler = tools["capture_call_goal"].handler

    asyncio.run(handler({"goal_summary": "ask about insurance cover"}, None))

    assert session.call_goal_turn_index == 3


# --------------------------------------------------------------- no dead air


@pytest.mark.parametrize("graph,hub", [("legacy", "state_position"), ("hub", "collections_hub")])
def test_hub_must_not_end_a_turn_on_a_bare_statement(graph: str, hub: str) -> None:
    """The reported symptom was the bot stating the balance and going silent."""
    _session, state, _tools, _initial = _flow(graph=graph)
    task = _task(state, hub)
    assert "never end your turn on a bare statement of fact" in task


# ------------------------------------------------------------------- persona


def test_persona_mood_is_a_stage_direction_not_an_observation() -> None:
    ctx = CallContext(
        channel="voice",
        persona={"name": "Rahul Sharma", "mood": "angry", "language": "English"},
    )
    content = ctx.persona_message()["content"]

    assert "role-playing" in content
    assert "mood they intend to play: angry" in content
    assert "you have not heard this caller yet" in content.lower()
    # The authority rule that keeps the CRM name winning after verification.
    assert "not the persona name" in content


def test_persona_message_is_absent_outside_the_sandbox() -> None:
    assert CallContext(channel="voice").persona_message() is None
