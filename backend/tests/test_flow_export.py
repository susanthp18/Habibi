"""The built-in script, materialised as an authored graph.

The Studio's Flow tab governed nothing: every card stored an empty graph, so
every call ran ``voice/flows.py`` — Python no prompt version could touch. These
assert the export stays a faithful projection of that Python, because the moment
it drifts, "load the built-in script" hands the author something the agent does
not actually do.
"""

from __future__ import annotations

import pytest

import flow_graph
from voice.flow_export import _stub_session, built_in_collections_graph
from voice.flows import MONEY_GOAL_INTENTS, build_collections_flow


@pytest.fixture(scope="module")
def graph() -> dict:
    return built_in_collections_graph()


@pytest.fixture(scope="module")
def built_in() -> dict:
    state, _tools, _initial, _globals = build_collections_flow(
        _stub_session(), role_message="", graph="legacy"
    )
    return state.nodes


def test_the_graph_validates_with_no_errors(graph: dict) -> None:
    result = flow_graph.validate_graph(
        flow_graph.parse_graph(graph),
        known_tools=[t["key"] for t in flow_graph.tool_catalog()],
    )
    assert result.ok, [i.message for i in result.issues if i.severity == "error"]


def test_reserved_key_nodes_are_not_flagged_unreachable(graph: dict) -> None:
    """Every non-start node here is reached by a built-in tool hop, not an
    authored edge. Warning on those buried real findings under 11 false ones."""
    result = flow_graph.validate_graph(
        flow_graph.parse_graph(graph),
        known_tools=[t["key"] for t in flow_graph.tool_catalog()],
    )
    assert [i for i in result.issues if i.code == "unreachable"] == []


def test_every_built_in_node_is_exported(graph: dict, built_in: dict) -> None:
    assert {n["key"] for n in graph["nodes"]} == set(built_in)


def test_node_keys_are_reserved_so_built_in_transitions_still_land(graph: dict) -> None:
    """Naming is the wiring: `_node("verify_identity")` resolves against the
    authored registry, so a renamed key silently breaks every scripted hop.

    greet_disclose is the sole exception — it is the entry node, so nothing
    transitions *to* it and it needs no reserved name.
    """
    unreserved = [
        n["key"]
        for n in graph["nodes"]
        if n["key"] not in flow_graph.RESERVED_NODE_KEYS and n["key"] != "greet_disclose"
    ]
    assert unreserved == []


def test_every_built_in_transition_target_is_a_documented_reserved_key() -> None:
    """RESERVED_NODE_KEYS exists so an author cannot name a node into a hop they
    were never told about. `pre_close` was such a trap: `_node("pre_close")`
    fires on the close probe, but the map never listed it.
    """
    import re
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "voice" / "tools.py"
    targets = set(re.findall(r'_node\(\s*"([a-z_]+)"', source.read_text(encoding="utf-8")))
    assert targets <= set(flow_graph.RESERVED_NODE_KEYS), sorted(
        targets - set(flow_graph.RESERVED_NODE_KEYS)
    )


def test_exactly_one_start_and_it_is_the_greeting(graph: dict) -> None:
    starts = [n["key"] for n in graph["nodes"] if n["data"]["isStart"]]
    assert starts == ["greet_disclose"]


def test_respond_immediately_matches_the_built_in(graph: dict, built_in: dict) -> None:
    """discover_intent listening rather than speaking is load bearing — it is
    what stopped the bot asking "what can I help with?" twice in a row."""
    for node in graph["nodes"]:
        expected = bool(built_in[node["key"]]().get("respond_immediately", True))
        assert node["data"]["respondImmediately"] is expected, node["key"]
    listening = {n["key"] for n in graph["nodes"] if not n["data"]["respondImmediately"]}
    assert "discover_intent" in listening


def test_per_node_tools_match_the_built_in(graph: dict) -> None:
    """Tool specs are a mix of schema objects and bare handlers; reading `.name`
    alone dropped half of every node's list."""
    by_key = {n["key"]: n["data"]["tools"] for n in graph["nodes"]}
    assert by_key["greet_disclose"] == ["disclose_recording"]
    assert by_key["discover_intent"] == ["capture_call_goal"]
    assert set(by_key["verify_identity"]) == {
        "verify_identity",
        "refuse_verification",
        "not_account_holder",
    }
    assert "get_account_position" in by_key["state_position"]
    assert len(by_key["state_position"]) == 6


def test_instructions_are_carried_verbatim(graph: dict, built_in: dict) -> None:
    """Nodes whose text does not depend on the caller's goal must survive the
    export unchanged — this is the check that catches drift."""
    for key in ("greet_disclose", "discover_intent", "handle_dispute", "call_ended"):
        node = next(n for n in graph["nodes"] if n["key"] == key)
        source = "\n".join(
            m["content"] for m in built_in[key]()["task_messages"]
        ).strip()
        assert node["data"]["instructions"] == source, key


def test_the_goal_branch_survives_as_one_node(graph: dict) -> None:
    """_goal_directive branches the prompt, not the graph: both arms reach the
    same node with the same tools. Splitting it would change turn structure."""
    hub = next(n for n in graph["nodes"] if n["key"] == "state_position")
    text = hub["data"]["instructions"]
    assert "{{call_goal_intent}}" in text
    assert "OTHERWISE" in text
    # Both arms present: position-first and goal-first.
    assert "state outstanding and minimum due" in text
    assert "Do NOT recite the outstanding balance" in text
    for intent in MONEY_GOAL_INTENTS:
        assert intent in text


def test_global_tools_are_exported(graph: dict) -> None:
    assert "search_knowledge_base" in graph["globalTools"]
    assert "end_call" in graph["globalTools"]


def test_call_ended_is_a_terminal_node(graph: dict) -> None:
    node = next(n for n in graph["nodes"] if n["key"] == "call_ended")
    assert node["type"] == "end"
    assert node["data"]["endConversation"] is True


def test_the_exported_graph_compiles_through_the_real_builder(graph: dict) -> None:
    """The decisive one. Everything above checks the JSON; this runs it through
    ``build_authored_flow`` — the path a published graph actually takes."""
    from voice.flows_dynamic import build_authored_flow

    session = _stub_session()
    state, _tools, initial_node, globals_ = build_authored_flow(
        session, graph, role_message="You are Priya.", bot_id="kaia-v2-4"
    )
    start = initial_node()
    assert start["name"] == "greet_disclose"
    assert start["respond_immediately"] is True
    assert len(start.get("functions") or []) == 1
    assert globals_
    # Every node registered, so the built-in `_node("verify_identity")` hops
    # resolve instead of logging a miss and stranding the call.
    assert set(state.nodes) == {n["key"] for n in graph["nodes"]}


def test_the_hub_resolves_the_live_goal_at_render_time(graph: dict) -> None:
    """What the whole variable bridge is for: the caller's goal is captured
    after the graph compiles, and the hub still has to see it."""
    from voice.flows_dynamic import build_authored_flow

    session = _stub_session()
    state, _tools, _initial, _globals = build_authored_flow(
        session, graph, role_message="", bot_id="kaia-v2-4"
    )
    session.call_goal = "dispute a late fee"
    session.call_goal_intent = "dispute"

    text = state.nodes["state_position"]()["task_messages"][0]["content"]
    assert "dispute a late fee" in text
    assert "{{" not in text, "an unresolved placeholder would be spoken aloud"


def test_nodes_do_not_share_a_position(graph: dict) -> None:
    """A pile at the origin is unusable on the canvas."""
    seen = {(n["position"]["x"], n["position"]["y"]) for n in graph["nodes"]}
    assert len(seen) == len(graph["nodes"])


def test_the_prepend_shape_is_not_given_the_money_wording(graph: dict) -> None:
    """verify_identity differs by a prepended goal preamble, not a money branch.

    Sharing one merge for both shapes put "a money question the outstanding
    balance actually answers" on the *verification* node, steering the model
    toward reciting a balance at the point it is asking for digits.
    """
    node = next(n for n in graph["nodes"] if n["key"] == "verify_identity")
    text = node["data"]["instructions"]
    assert "outstanding balance actually answers" not in text
    assert "already said why they called" in text
    assert "{{call_goal}}" in text
    # The common body survives intact under either arm.
    assert "last 4 digits" in text


def test_the_hub_keeps_the_money_wording(graph: dict) -> None:
    node = next(n for n in graph["nodes"] if n["key"] == "state_position")
    assert "outstanding balance actually answers" in node["data"]["instructions"]


def test_no_node_carries_an_unrendered_brace_from_the_merge(graph: dict) -> None:
    """Only the two goal variables may survive as templates; anything else is a
    formatting accident that would be spoken aloud."""
    import re

    allowed = {"{{call_goal}}", "{{call_goal_intent}}"}
    for node in graph["nodes"]:
        found = set(re.findall(r"\{\{[^}]*\}\}", node["data"]["instructions"]))
        assert found <= allowed, (node["key"], found - allowed)


def test_the_layout_fits_a_narrow_canvas(graph: dict) -> None:
    """The Flow tab's canvas is a tall column — the inspector takes the other
    half. A left-to-right layout spanned 2240px and fitted at ~0.2 zoom, so the
    nodes were on screen but too small to read and looked like a load failure.
    """
    NODE_W, NODE_H = 256, 110
    PANE_W, PANE_H = 500, 576  # ~ the h-[36rem] canvas beside the inspector

    xs = [n["position"]["x"] for n in graph["nodes"]]
    ys = [n["position"]["y"] for n in graph["nodes"]]
    width = max(xs) - min(xs) + NODE_W
    height = max(ys) - min(ys) + NODE_H
    zoom = min(PANE_W / width, PANE_H / height)
    assert zoom > 0.35, f"fits at {zoom:.2f} zoom — nodes would be unreadable"
