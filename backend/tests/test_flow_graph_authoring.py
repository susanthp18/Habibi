"""Authored flow graphs: schema validation, variables and conditions.

The validator is the only thing standing between a half-drawn canvas and a
published call script, so its rules are pinned here rather than left to the UI.
"""

from __future__ import annotations

import pytest

import flow_graph as fg
from voice.flow_vars import FlowVariables, evaluate_condition


def _codes(validation: fg.FlowValidation, severity: str) -> set[str]:
    return {i.code for i in validation.issues if i.severity == severity}


# --- schema / defaults -----------------------------------------------------


def test_empty_graph_is_publishable() -> None:
    """The starter graph a new draft gets must not open with errors."""
    result = fg.validate_graph(fg.empty_graph())
    assert result.ok
    assert _codes(result, "error") == set()


def test_absent_flow_parses_to_empty_graph() -> None:
    """Every prompt_version predating this feature stores '{}'."""
    for raw in (None, {}, ""):
        assert fg.parse_graph(raw).nodes == []


# --- node rules ------------------------------------------------------------


def test_duplicate_node_key_is_an_error() -> None:
    """Keys become transition tool names; a collision merges two transitions."""
    graph = fg.empty_graph()
    graph.nodes[1].key = graph.nodes[0].key
    assert "duplicate_node_key" in _codes(fg.validate_graph(graph), "error")


def test_node_key_must_be_an_identifier() -> None:
    graph = fg.empty_graph()
    graph.nodes[0].key = "Greet Node"
    assert "invalid_node_key" in _codes(fg.validate_graph(graph), "error")


def test_exactly_one_start_is_required() -> None:
    graph = fg.empty_graph()
    graph.nodes[0].data.isStart = False
    assert "no_start" in _codes(fg.validate_graph(graph), "error")

    graph.nodes[0].data.isStart = True
    graph.nodes[1].data.isStart = True
    graph.nodes[1].type = "conversation"
    assert "multiple_starts" in _codes(fg.validate_graph(graph), "error")


def test_unknown_tool_is_rejected_only_when_a_catalog_is_supplied() -> None:
    graph = fg.empty_graph()
    graph.nodes[0].data.tools = ["not_a_real_tool"]
    # No catalog: the validator cannot know, so it must not invent an error.
    assert fg.validate_graph(graph).ok
    result = fg.validate_graph(graph, known_tools={"disclose_recording"})
    assert "unknown_tool" in _codes(result, "error")


def test_real_tool_keys_pass_against_the_live_catalog() -> None:
    """Guards against the catalog and the seed graph drifting apart."""
    keys = {t["key"] for t in fg.tool_catalog()}
    assert fg.validate_graph(fg.empty_graph(), known_tools=keys).ok


# --- edge rules ------------------------------------------------------------


def test_dangling_edge_is_an_error() -> None:
    graph = fg.empty_graph()
    graph.edges[0].target = "n-deleted"
    assert "dangling_target" in _codes(fg.validate_graph(graph), "error")


def test_end_node_cannot_transition_out() -> None:
    graph = fg.empty_graph()
    graph.edges.append(
        fg.FlowEdge(id="e-bad", source="n-end", target="n-start")
    )
    assert "edge_from_end" in _codes(fg.validate_graph(graph), "error")


def test_always_edge_must_be_the_only_outgoing_one() -> None:
    """A sibling of an unconditional edge could never fire."""
    graph = fg.empty_graph()
    graph.nodes.append(
        fg.FlowNode(id="n-3", key="third", data=fg.FlowNodeData(name="Third"))
    )
    graph.edges.append(
        fg.FlowEdge(
            id="e-2",
            source="n-start",
            target="n-3",
            data=fg.FlowEdgeData(condition=fg.FlowCondition(type="always")),
        )
    )
    assert "always_not_exclusive" in _codes(fg.validate_graph(graph), "error")


def test_prompt_edge_needs_condition_text() -> None:
    graph = fg.empty_graph()
    graph.edges[0].data.condition.prompt = "   "
    assert "empty_condition" in _codes(fg.validate_graph(graph), "error")


def test_expression_operator_needing_a_value_must_have_one() -> None:
    graph = fg.empty_graph()
    graph.edges[0].data.condition = fg.FlowCondition(
        type="expression",
        clauses=[fg.FlowExpressionClause(variable="amount", operator="greater_than")],
    )
    assert "empty_clause_value" in _codes(fg.validate_graph(graph), "error")


def test_unary_operator_needs_no_value() -> None:
    graph = fg.empty_graph()
    graph.edges[0].data.condition = fg.FlowCondition(
        type="expression",
        clauses=[fg.FlowExpressionClause(variable="amount", operator="exists")],
    )
    assert fg.validate_graph(graph).ok


def test_duplicate_edge_between_same_nodes_is_an_error() -> None:
    graph = fg.empty_graph()
    graph.edges.append(
        fg.FlowEdge(
            id="e-dup",
            source="n-start",
            target="n-end",
            data=fg.FlowEdgeData(condition=fg.FlowCondition(prompt="also done")),
        )
    )
    assert "duplicate_edge" in _codes(fg.validate_graph(graph), "error")


# --- warnings are advisory, not blocking -----------------------------------


def test_unreachable_node_warns_but_still_validates() -> None:
    """A half-built graph must stay savable or authors stop saving."""
    graph = fg.empty_graph()
    graph.nodes.append(
        fg.FlowNode(id="n-orphan", key="orphan", data=fg.FlowNodeData(name="Orphan"))
    )
    result = fg.validate_graph(graph)
    assert result.ok
    assert "unreachable" in _codes(result, "warning")


# --- variables -------------------------------------------------------------


def test_render_substitutes_and_preserves_unknown_keys() -> None:
    variables = FlowVariables({"amount": "5000"})
    assert variables.render("Pay {{ amount }} today") == "Pay 5000 today"
    # An unknown key must stay visible, not silently vanish into a fluent lie.
    assert variables.render("Due {{ mystery }}") == "Due {{ mystery }}"


def test_system_variables_are_available_without_being_stored() -> None:
    variables = FlowVariables()
    assert "{{" not in variables.render("Today is {{date}}")
    assert variables.snapshot() == {}


def test_values_are_coerced_to_strings() -> None:
    variables = FlowVariables({"n": 42, "b": True})
    assert variables.get("n") == "42"
    assert variables.get("b") == "True"


# --- condition evaluation --------------------------------------------------


def _expr(*clauses, match="all") -> fg.FlowCondition:
    return fg.FlowCondition(type="expression", match=match, clauses=list(clauses))


def test_always_condition_is_true_and_prompt_is_never_auto_true() -> None:
    variables = FlowVariables()
    assert evaluate_condition(fg.FlowCondition(type="always"), variables) is True
    # Prompt edges are the model's decision, never the evaluator's.
    assert evaluate_condition(fg.FlowCondition(type="prompt", prompt="x"), variables) is False


def test_numeric_comparison_uses_numbers_not_strings() -> None:
    variables = FlowVariables({"amount": "9"})
    clause = fg.FlowExpressionClause(
        variable="amount", operator="greater_than", value="10"
    )
    # String comparison would call "9" > "10" true.
    assert evaluate_condition(_expr(clause), variables) is False


def test_non_numeric_value_fails_closed() -> None:
    """An uncomparable pair must not open the edge it guards."""
    variables = FlowVariables({"amount": "later"})
    clause = fg.FlowExpressionClause(
        variable="amount", operator="greater_than", value="10"
    )
    assert evaluate_condition(_expr(clause), variables) is False


def test_missing_variable_is_false_except_for_not_exists() -> None:
    variables = FlowVariables()
    equals = fg.FlowExpressionClause(variable="x", operator="equals", value="1")
    assert evaluate_condition(_expr(equals), variables) is False
    absent = fg.FlowExpressionClause(variable="x", operator="not_exists")
    assert evaluate_condition(_expr(absent), variables) is True


def test_match_all_versus_any() -> None:
    variables = FlowVariables({"a": "1", "b": "2"})
    hit = fg.FlowExpressionClause(variable="a", operator="equals", value="1")
    miss = fg.FlowExpressionClause(variable="b", operator="equals", value="9")
    assert evaluate_condition(_expr(hit, miss, match="all"), variables) is False
    assert evaluate_condition(_expr(hit, miss, match="any"), variables) is True


def test_empty_expression_never_fires() -> None:
    assert evaluate_condition(_expr(), FlowVariables()) is False


# --- publish compiler -------------------------------------------------------


def test_empty_stored_graph_is_publishable() -> None:
    """`{}` means 'use the built-in script' — that must still ship."""
    assert fg.assert_publishable({}).nodes == []
    assert fg.assert_publishable(None).nodes == []


def test_invalid_authored_graph_is_not_publishable() -> None:
    graph = fg.empty_graph()
    graph.nodes[1].key = graph.nodes[0].key
    with pytest.raises(fg.FlowInvalidError) as exc:
        fg.assert_publishable(graph)
    assert exc.value.http_detail()["code"] == "flow_invalid"
    assert "duplicate_node_key" in _codes(exc.value.validation, "error")


def test_starter_graph_is_publishable_against_the_live_catalog() -> None:
    fg.assert_publishable(fg.empty_graph())
