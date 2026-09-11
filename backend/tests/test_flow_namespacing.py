"""Two specialists may each own a ``wrap_up``.

Node keys were flat, so one member per reserved key was the ceiling and the
fleet you could ship held exactly one collections-shaped specialist. That is the
whole reason namespacing is Phase 1 and not Phase 5: until a key can say which
member it belongs to, ``voice/tools.py``'s ``_node("wrap_up")`` has only one
node it could possibly mean.

The rules pinned here are the ones a hop depends on: the speaking member wins,
a flat graph is unchanged, and an ambiguous local name is refused rather than
guessed at.
"""

from __future__ import annotations

import json
from pathlib import Path

from flow_graph import (
    RESERVED_NODE_KEYS,
    local_key,
    parse_graph,
    resolve_key,
    split_key,
    valid_node_key,
    validate_graph,
)
from flow_vars import FlowVariables
from flow_walk import FlowWalker, transition_tool_name

BASE = Path(__file__).resolve().parent.parent


def _node(key: str, *, start: bool = False, tools: list[str] | None = None) -> dict:
    return {
        "id": f"n-{key.replace('/', '-')}",
        "type": "conversation",
        "key": key,
        "data": {"name": key, "isStart": start, "tools": tools or []},
    }


def _two_member_graph() -> dict:
    return {
        "version": 1,
        "globalTools": [],
        "nodes": [
            _node("collections/negotiate_ptp", start=True),
            _node("collections/wrap_up"),
            _node("insurance/pitch"),
            _node("insurance/wrap_up"),
        ],
        "edges": [],
    }


# --- the grammar ------------------------------------------------------------


def test_a_namespaced_key_splits_into_member_and_local_name() -> None:
    assert split_key("collections/wrap_up") == ("collections", "wrap_up")
    assert local_key("collections/wrap_up") == "wrap_up"


def test_a_flat_key_is_its_own_local_name() -> None:
    """The migration has to be free: every stored graph is flat today."""
    assert split_key("wrap_up") == (None, "wrap_up")
    assert local_key("wrap_up") == "wrap_up"


def test_a_member_slug_may_carry_hyphens_because_a_bot_id_does() -> None:
    assert valid_node_key("kaia-v2-4/wrap_up")
    assert valid_node_key("wrap_up")
    assert not valid_node_key("Collections/wrap_up")
    assert not valid_node_key("collections/Wrap Up")
    assert not valid_node_key("a/b/c")


def test_the_validator_accepts_a_namespaced_graph() -> None:
    issues = validate_graph(parse_graph(_two_member_graph())).issues
    assert [i for i in issues if i.code == "invalid_node_key"] == []


def test_a_reserved_key_is_reserved_inside_a_namespace_too() -> None:
    """``collections/wrap_up`` is still the node ``begin_wrap_up`` reaches.

    Reachability warns on any node with no way in, and a reserved key *is* a way
    in — via the built-in tool that transitions to it by name. Namespacing must
    not turn that exemption off, or every fleet graph opens with a screenful of
    false 'unreachable' warnings.
    """
    assert "wrap_up" in RESERVED_NODE_KEYS
    issues = validate_graph(parse_graph(_two_member_graph())).issues
    unreachable = {i.nodeId for i in issues if i.code == "unreachable"}
    assert "n-collections-wrap_up" not in unreachable
    assert "n-insurance-wrap_up" not in unreachable


# --- resolution -------------------------------------------------------------


def test_the_speaking_member_wins() -> None:
    keys = {"collections/wrap_up", "insurance/wrap_up"}
    assert resolve_key(keys, "wrap_up", namespace="insurance") == "insurance/wrap_up"
    assert resolve_key(keys, "wrap_up", namespace="collections") == "collections/wrap_up"


def test_an_ambiguous_local_name_with_no_namespace_is_refused() -> None:
    """Guessing here would put the caller in the wrong specialist's close.

    An ambiguous hop is an authoring error the compiler is supposed to catch
    (G-F4), which is a thing to fix before the call — never something to resolve
    by picking whichever member sorted first.
    """
    keys = {"collections/wrap_up", "insurance/wrap_up"}
    assert resolve_key(keys, "wrap_up") is None


def test_one_unambiguous_namespace_resolves_without_being_named() -> None:
    keys = {"collections/wrap_up", "insurance/pitch"}
    assert resolve_key(keys, "pitch") == "insurance/pitch"


def test_a_flat_graph_resolves_exactly_as_it_did() -> None:
    keys = {"wrap_up", "pre_close"}
    assert resolve_key(keys, "wrap_up") == "wrap_up"
    assert resolve_key(keys, "wrap_up", namespace="collections") == "wrap_up"


# --- the walker -------------------------------------------------------------


def test_the_cursor_carries_its_namespace() -> None:
    walker = FlowWalker(parse_graph(_two_member_graph()), FlowVariables({}))
    assert walker.namespace == "collections"
    assert walker.node("wrap_up").key == "collections/wrap_up"


def test_moving_into_another_member_swaps_the_namespace() -> None:
    """This is what a handoff *is* at the graph level.

    A cursor that kept the sending member's namespace would resolve every local
    name back into the specialist that just handed the call away, which is the
    tool-grant defect the whole seam exists to close.
    """
    walker = FlowWalker(parse_graph(_two_member_graph()), FlowVariables({}))
    walker.move_to(walker.node("insurance/pitch"))
    assert walker.namespace == "insurance"
    assert walker.node("wrap_up").key == "insurance/wrap_up"


def test_a_transition_tool_name_is_a_legal_function_name() -> None:
    """``/`` is illegal in an OpenAI function name; the tool spells it ``__``."""
    name = transition_tool_name("collections/wrap_up")
    assert name == "go_to_collections__wrap_up"
    assert "/" not in name


def test_the_tool_name_is_inverted_by_lookup_not_by_splitting() -> None:
    """A local key may itself contain ``__``, so re-splitting is unsafe.

    The walker keeps the forward map instead, which is exact by construction.
    """
    graph = _two_member_graph()
    graph["nodes"].append(_node("collections/wrap__up"))
    walker = FlowWalker(parse_graph(graph), FlowVariables({}))
    assert walker.key_for_tool("go_to_collections__wrap__up") == "collections/wrap__up"
    assert walker.key_for_tool("go_to_collections__wrap_up") == "collections/wrap_up"


def test_the_built_in_script_is_untouched_by_any_of_this() -> None:
    """The one assertion that says the migration is free."""
    graph = parse_graph(
        json.loads((BASE / "agent_core" / "cards" / "graphs" / "collections.json").read_text(encoding="utf-8"))
    )
    walker = FlowWalker(graph, FlowVariables({}))
    assert walker.namespace is None
    assert walker.current.key == "greet_disclose"
    assert walker.advance("disclose_recording").key == "discover_intent"
    assert all(split_key(n.key)[0] is None for n in graph.nodes)


def test_an_explicitly_namespaced_name_is_never_rescoped() -> None:
    """The speaking member is `intake-v1`; the hop names `kaia-v2-4/state_position`.

    Scoping the local key first resolved it to `intake-v1/state_position` --
    the door's own route node -- so the handoff landed where it started.
    """
    from flow_graph import resolve_key

    keys = {"intake-v1/state_position", "kaia-v2-4/state_position", "kaia-v2-4/wrap_up"}
    assert resolve_key(keys, "kaia-v2-4/state_position", namespace="intake-v1") == "kaia-v2-4/state_position"
    assert resolve_key(keys, "state_position", namespace="intake-v1") == "intake-v1/state_position"
    assert resolve_key(keys, "kaia-v2-4/no_such", namespace="intake-v1") is None
