"""Live call state reaching an authored graph.

``build_authored_flow`` was called without ``initial_variables``, so an authored
graph started with an empty bag: only ``date`` and ``time`` resolved. The
caller's stated goal — the thing the whole goal-conditioned hub turns on — was
invisible to instructions and to edge conditions alike, which made the built-in
script impossible to express as a graph.
"""

from __future__ import annotations

from types import SimpleNamespace

from voice.flow_vars import FlowVariables, evaluate_clause
from voice.flows_dynamic import session_variables
from voice.session import VoiceSession


def _session(**kwargs) -> VoiceSession:
    session = VoiceSession(session_id="T-1")
    for key, value in kwargs.items():
        setattr(session, key, value)
    return session


def test_goal_and_intent_are_projected() -> None:
    session = _session(call_goal="dispute a late fee", call_goal_intent="dispute")
    values = session_variables(session)
    assert values["call_goal"] == "dispute a late fee"
    assert values["call_goal_intent"] == "dispute"


def test_absent_goal_is_empty_not_none() -> None:
    """`None` would render as the literal string "None" in a spoken prompt."""
    values = session_variables(_session())
    assert values["call_goal"] == ""
    assert values["call_goal_intent"] == ""


def test_identity_verified_is_lowercase_for_equals_clauses() -> None:
    """str(True) is "True"; an authored `equals true` clause compares exactly."""
    assert session_variables(_session(identity_verified=True))["identity_verified"] == "true"
    assert session_variables(_session())["identity_verified"] == "false"


def test_understanding_fields_are_projected_when_present() -> None:
    session = _session(
        understanding=SimpleNamespace(intent="hardship", sentiment=-0.4, language="hi-IN")
    )
    values = session_variables(session)
    assert values["intent"] == "hardship"
    assert values["sentiment"] == "-0.4"
    assert values["language"] == "hi-IN"


def test_missing_understanding_does_not_raise() -> None:
    values = session_variables(_session())
    assert values["intent"] == ""
    assert values["sentiment"] == ""


def test_context_is_read_late_not_snapshotted() -> None:
    """capture_call_goal runs long after the graph compiles. A build-time
    snapshot would always be empty — this is the whole bug."""
    session = _session()
    variables = FlowVariables(context=lambda: session_variables(session))
    assert variables.render("goal: {{call_goal}}") == "goal: "

    session.call_goal = "pay my emi"
    assert variables.render("goal: {{call_goal}}") == "goal: pay my emi"


def test_context_variables_are_visible_to_edge_conditions() -> None:
    """Reading _values directly meant an instruction could interpolate a
    variable that an expression edge on the same name saw as absent."""
    session = _session(call_goal_intent="dispute")
    variables = FlowVariables(context=lambda: session_variables(session))
    clause = SimpleNamespace(variable="call_goal_intent", operator="equals", value="dispute")
    assert evaluate_clause(clause, variables) is True

    session.call_goal_intent = "payment"
    assert evaluate_clause(clause, variables) is False


def test_author_values_win_over_call_state() -> None:
    """A node that explicitly declares a variable is never shadowed."""
    session = _session(call_goal="from the session")
    variables = FlowVariables(context=lambda: session_variables(session))
    variables.set("call_goal", "from an extract tool")
    assert variables.get("call_goal") == "from an extract tool"


def test_a_failing_context_does_not_break_the_call() -> None:
    """An unresolved placeholder is visible in a transcript; a raise on the
    audio path is not."""

    def boom() -> dict:
        raise RuntimeError("crm down")

    variables = FlowVariables({"kept": "yes"}, context=boom)
    assert variables.render("{{kept}} {{call_goal}}") == "yes {{call_goal}}"


def test_snapshot_stays_author_only() -> None:
    session = _session(call_goal="pay")
    variables = FlowVariables({"amount": "500"}, context=lambda: session_variables(session))
    assert variables.snapshot() == {"amount": "500"}
