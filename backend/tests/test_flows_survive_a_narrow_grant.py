"""A card the studio lets you publish must not crash the call it answers.

``build_tools`` filters its registry to the card's grant plus ``ALWAYS_ON``. The
node factories in ``voice/flows.py`` then indexed that registry directly --
``tools["create_promise_to_pay"]`` -- 42 times. A card that detached the
``ptp-negotiate`` skill pack, which the Skills tab offers as an ordinary edit,
compiled clean, published clean, greeted the caller, and raised KeyError the
moment the flow reached ``state_position``: after identity verification, with the
borrower on the line. 33 of the 42 subscripts could reach a name a card is
allowed to exclude.

``_fns`` drops what was not granted instead. These tests pin the two properties
that makes safe:

* building never raises, for any grant, and never puts ``None`` in a functions
  list (``tools.get(...)`` would -- that was the other tempting fix, and it fails
  later and further away);
* dropping a tool never strands a node with no way out, which is the failure
  ``_fns`` would otherwise trade the crash for.

The second is guaranteed statically rather than checked at runtime: every verb in
``NODE_REQUIRED`` is in ``ALWAYS_ON``, so the grant filter cannot remove one. A
runtime assertion here could never fire, and this codebase has enough controls
that only look like controls.
"""

from __future__ import annotations

import pytest

from voice.session import VoiceSession

pytest.importorskip("pipecat.flows")

from voice.flows import build_collections_flow  # noqa: E402
from voice.node_contracts import NODE_REQUIRED  # noqa: E402
from voice.tools import ALWAYS_ON  # noqa: E402

GRAPHS = ("legacy", "hub")


def _flow(*, allowed: frozenset[str] | None, graph: str = "legacy"):
    return build_collections_flow(
        VoiceSession(session_id="VS-NARROWGRANT"),
        role_message="role",
        graph=graph,
        allowed_tool_names=set(allowed) if allowed is not None else None,
    )


def _all_tool_names() -> set[str]:
    _state, tools, _initial, _globals = _flow(allowed=None)
    return set(tools)


def _names(functions) -> set[str]:
    """Nodes mix FlowsFunctionSchema (``.name``) with plain callables."""
    return {getattr(f, "name", None) or f.__name__ for f in functions}


# --- building never raises, whatever the card granted ------------------------


@pytest.mark.parametrize("graph", GRAPHS)
def test_a_card_that_grants_nothing_still_builds(graph: str) -> None:
    """The narrowest possible card. Every node still constructs."""
    state, _tools, _initial, _globals = _flow(allowed=frozenset(), graph=graph)
    for key, factory in state.nodes.items():
        node = factory()
        assert None not in (node.get("functions") or []), (
            f"{key} put None in its functions list -- that is tools.get(), and it "
            "fails inside the LLM service instead of here"
        )


@pytest.mark.parametrize("missing", sorted(_all_tool_names()))
def test_dropping_any_single_tool_never_raises(missing: str) -> None:
    """The case a grant of ``frozenset()`` cannot reach.

    With nothing granted, ALWAYS_ON masks every node that needs only flow
    control. Removing exactly one name at a time is what exercises the
    skill-gated verbs the empty case leaves standing.
    """
    allowed = frozenset(_all_tool_names() - {missing})
    for graph in GRAPHS:
        state, _tools, _initial, _globals = _flow(allowed=allowed, graph=graph)
        for key, factory in state.nodes.items():
            node = factory()
            offered = _names(node.get("functions") or [])
            assert None not in (node.get("functions") or [])
            if missing in ALWAYS_ON:
                # Excluding one of these is not a narrower card, it is a stuck
                # one, so the grant filter unions them back in. Still offered is
                # the correct answer; building without raising is the property
                # under test.
                continue
            assert missing not in offered, (
                f"{key} still offers {missing} after the card excluded it"
            )


# --- and never strands a node ------------------------------------------------


def test_every_required_exit_is_a_verb_no_card_can_remove() -> None:
    """The contract that makes NODE_REQUIRED satisfiable rather than hopeful.

    If this fails, somebody has named an exit a card is allowed to exclude, and
    the node it belongs to can be published into a dead end.
    """
    required: set[str] = set()
    for names in NODE_REQUIRED.values():
        required |= names
    escapable = required - ALWAYS_ON
    assert not escapable, (
        f"NODE_REQUIRED names {sorted(escapable)}, which a card can exclude. "
        "Either add them to voice.tools.ALWAYS_ON or stop calling them exits."
    )


@pytest.mark.parametrize("graph", GRAPHS)
def test_every_node_keeps_an_exit_under_the_narrowest_grant(graph: str) -> None:
    state, _tools, _initial, _globals = _flow(allowed=frozenset(), graph=graph)
    for key, factory in state.nodes.items():
        required = NODE_REQUIRED.get(key)
        if not required:
            continue  # ends the call itself, or is only reached to terminate
        offered = _names(factory().get("functions") or [])
        assert offered & required, (
            f"{key} has no exit left: needs one of {sorted(required)}, offers "
            f"{sorted(offered)}"
        )


def test_node_contracts_name_nodes_that_exist() -> None:
    """A contract for a node nobody registers is a contract nothing checks."""
    registered: set[str] = set()
    for graph in GRAPHS:
        state, _tools, _initial, _globals = _flow(allowed=None, graph=graph)
        registered |= set(state.nodes)
    unknown = set(NODE_REQUIRED) - registered
    assert not unknown, f"NODE_REQUIRED names nodes no graph registers: {sorted(unknown)}"
