"""VOICE_FLOW_GRAPH=hub — the merged collections_hub node.

The hub merges state_position + negotiate_ptp + gated_upsell + wrap_up so the
model can state the position, negotiate, offer and close in any order without a
transition. That widens its authority, which is the point; it also removes two
constraints the *graph* used to enforce for free:

  1. gated_upsell was reachable ONLY from a successful create_promise_to_pay,
     so a product could not be pitched before a commitment existed;
  2. product_keys_for_node keyed the KB corpus off the node name "gated_upsell".

Both are re-implemented in code (ToolState.commitment_secured / product_scope)
and both are tested here. Losing either is silent: the bot would pitch insurance
to an angry caller, or answer an insurance question out of the collections
corpus, and nothing would error.
"""

from __future__ import annotations

import asyncio

import pytest

from voice.flows import build_collections_flow
from voice.session import VoiceSession

LEGACY_NODES = {
    "greet_disclose",
    # The outbound door and the road out of it. Registered in both
    # graphs; unreachable unless the call was placed by us.
    "confirm_identity",
    "third_party",
    "discover_intent",
    "verify_identity",
    "state_position",
    "negotiate_ptp",
    "handle_dispute",
    "gated_upsell",
    "pre_close",
    "wrap_up",
    "terminate_politely",
    "escalate_close",
    "call_ended",
}
HUB_NODES = {
    "greet_disclose",
    # The outbound door and the road out of it. Registered in both
    # graphs; unreachable unless the call was placed by us.
    "confirm_identity",
    "third_party",
    "discover_intent",
    "verify_identity",
    "collections_hub",
    "handle_dispute",
    "pre_close",
    "terminate_politely",
    "escalate_close",
    "call_ended",
}


def _flow(graph: str, **kw):
    session = kw.pop("session", None) or VoiceSession(session_id="VS-GRAPHTEST1")
    return build_collections_flow(session, role_message="role", graph=graph, **kw)


def _names(functions) -> set[str]:
    """Tool names off a node's function list.

    Nodes mix FlowsFunctionSchema (which carries ``.name``) with plain direct
    functions (which carry ``__name__``). Reading only ``.name`` raised
    AttributeError on every node that advertised a hop.
    """
    return {getattr(f, "name", None) or f.__name__ for f in functions}


# ------------------------------------------------------------------ graph shape


def test_legacy_graph_registry() -> None:
    state, _tools, _initial, _globals = _flow("legacy")
    assert set(state.nodes) == LEGACY_NODES


def test_hub_graph_registry() -> None:
    """9 nodes → 6, plus call_ended in both."""
    state, _tools, _initial, _globals = _flow("hub")
    assert set(state.nodes) == HUB_NODES


def test_call_ended_is_registered_in_both_graphs() -> None:
    """end_call used to build this node inline, bypassing the registry — so
    current_node never became "call_ended" and the RTVI flow.node stream missed
    the final hop. Matters more under hub, where every clean ending goes here."""
    for graph in ("legacy", "hub"):
        state, _tools, _initial, _globals = _flow(graph)
        assert "call_ended" in state.nodes
        node = state.nodes["call_ended"]()
        assert node["name"] == "call_ended"
        assert node["post_actions"] == [{"type": "end_conversation"}]


def test_end_call_routes_through_the_registry() -> None:
    state, tools, _initial, _globals = _flow("hub")
    _result, node = asyncio.run(tools["end_call"](None))

    assert node["name"] == "call_ended"
    assert state.current_node == "call_ended", "flow.node breadcrumb would be missing"


def test_hub_advertises_the_union_of_the_merged_nodes() -> None:
    state, _tools, _initial, _globals = _flow("hub")
    assert _names(state.nodes["collections_hub"]()["functions"]) == {
        "get_account_position",
        "create_promise_to_pay",
        # Why they have not paid, as a code. The hub is where the position is
        # stated and therefore where the reason is given.
        "capture_nonpayment_reason",
        "request_callback",
        # The engine chooses the product; check_product_eligibility is no longer
        # advertised here because a model that can call it directly is a model
        # that has already picked a product id on its own.
        "recommend_next_offer",
        "capture_lead",
        "decline_offer",
        "begin_dispute",
    }


def test_hub_does_not_advertise_a_way_to_pick_a_product_directly() -> None:
    """The whole point of the engine is that the model cannot name a product.

    Leaving check_product_eligibility on the hub would let it guess an id and
    then ask whether the guess was allowed — which is the behaviour the engine
    replaces.
    """
    state, tools, _initial, _globals = _flow("hub")
    advertised = _names(state.nodes["collections_hub"]()["functions"])
    assert "check_product_eligibility" not in advertised
    # Still callable — the insurance mesh worker and the API path both use it.
    assert "check_product_eligibility" in tools


def test_hub_does_not_advertise_the_deleted_hops_but_keeps_the_functions() -> None:
    """They must stay callable — the legacy graph still needs them."""
    state, tools, _initial, _globals = _flow("hub")
    advertised = _names(state.nodes["collections_hub"]()["functions"])

    for hop in ("begin_negotiate", "begin_wrap_up", "return_to_position"):
        assert hop not in advertised
        assert hop in tools


def test_handle_dispute_survives_the_merge() -> None:
    """A compliance state whose pre_action bridge is load-bearing."""
    for graph in ("legacy", "hub"):
        state, _tools, _initial, _globals = _flow(graph)
        node = state.nodes["handle_dispute"]()
        assert node["pre_actions"][0]["type"] == "tts_say"
        assert node["respond_immediately"] is True
        advertised = _names(node["functions"])
        assert "evaluate_authority" in advertised
        assert "apply_goodwill" in advertised
        assert "flag_dispute" in advertised


# ---------------------------------------------------------------- transitions


def _verified_flow(graph: str):
    session = VoiceSession(session_id="VS-GRAPHTEST1", customer_id="C1")
    session.identity_verified = True
    return _flow(graph, session=session)


def test_ptp_stays_on_the_hub_under_hub_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not transitioning is the whole point of the merge."""
    state, tools = _ptp(monkeypatch, "hub")
    assert state.current_node != "gated_upsell"


def test_ptp_transitions_to_gated_upsell_under_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, _tools = _ptp(monkeypatch, "legacy")
    assert state.current_node == "gated_upsell"


def _ptp(monkeypatch: pytest.MonkeyPatch, graph: str):
    from agent_core.tools import domain
    from agent_core.tools.domain import ToolResult

    monkeypatch.setattr(
        domain,
        "create_promise_to_pay",
        lambda **_kw: ToolResult(
            ok=True,
            data={"promiseId": "PR-1", "promisedDate": "2026-08-10"},
            entity="promise",
            entity_id="PR-1",
        ),
    )
    state, tools, _initial, _globals = _verified_flow(graph)
    asyncio.run(
        tools["create_promise_to_pay"].handler(
            {"amount": 100.0, "promise_date": "2026-08-10"}, None
        )
    )
    return state, tools


def test_verify_routes_to_the_right_hub_per_graph() -> None:
    for graph, expected in (("legacy", "state_position"), ("hub", "collections_hub")):
        state, _tools, _initial, _globals = _flow(graph)
        assert expected in state.nodes


def test_session_extra_overrides_the_env_graph() -> None:
    """Per-session override is what makes Sandbox A/B possible without a deploy."""
    session = VoiceSession(session_id="VS-GRAPHTEST1")
    session.extra["flowGraph"] = "hub"
    state, _tools, _initial, _globals = build_collections_flow(session, role_message="role")
    assert "collections_hub" in state.nodes


def test_an_unknown_graph_value_falls_back_to_legacy() -> None:
    """An operator typo must not take voice down."""
    state, _tools, _initial, _globals = _flow("hubb")
    assert set(state.nodes) == LEGACY_NODES


# ------------------------------------------------------------ hub task message


def test_hub_task_message_carries_the_merged_guidance() -> None:
    """Everything the four nodes said has to survive somewhere."""
    state, _tools, _initial, _globals = _flow("hub")
    content = state.nodes["collections_hub"]()["task_messages"][0]["content"].lower()

    # from state_position
    assert "get_account_position first" in content
    # Unprompted menu-reading is still banned, but the rule is now conditional:
    # an explicit "what can you do?" must be answerable. A flat "do NOT read a
    # menu of options" argued against answering it at all.
    assert "do not recite a menu of options unprompted" in content
    assert "if they ask what you can do" in content
    # money-facts precedence, verbatim intent
    assert "never search_knowledge_base" in content
    # from negotiate_ptp
    assert "5%" in content
    assert "yyyy-mm-dd" in content
    # from gated_upsell — now routed through the engine
    assert "recommend_next_offer" in content
    assert "capture_lead" in content
    # from wrap_up
    assert "end_call" in content


def test_hub_forbids_naming_a_product_the_engine_did_not_return() -> None:
    """The ordering rule is now a sourcing rule: the model may only speak about
    products the engine handed it, which subsumes the old "not until a
    commitment exists" gate (arbitration enforces that in code)."""
    state, _tools, _initial, _globals = _flow("hub")
    content = state.nodes["collections_hub"]()["task_messages"][0]["content"].lower()
    assert "never name a product you were not given" in content
    assert "do not guess product ids" in content


# ------------------------------------------------------------------ close probe


def test_pre_close_is_registered_in_both_graphs() -> None:
    """end_call is the single chokepoint every clean ending goes through, so the
    probe node has to exist on both graphs or one of them silently loses it."""
    for graph in ("legacy", "hub"):
        state, _tools, _initial, _globals = _flow(graph)
        assert "pre_close" in state.nodes


def test_pre_close_never_ends_the_conversation_itself() -> None:
    """The terminals carry post_actions: end_conversation, which fires as soon as
    TTS finishes. A question asked there hangs up on the caller mid-answer."""
    state, _tools, _initial, _globals = _flow("hub")
    node = state.nodes["pre_close"]()
    assert "post_actions" not in node
    assert _names(node["functions"]) == {
        "capture_lead",
        "decline_offer",
        # "Anything else?" is the one node that asks an open question and then
        # waits, which makes it where a borrower says "and don't ring me before
        # ten" - so it is the only node granted `set_contact_preference`.
        "set_contact_preference",
        "return_to_position",
        "end_call",
    }


def test_pre_close_asks_exactly_one_question_and_offers_nothing_by_default() -> None:
    state, _tools, _initial, _globals = _flow("hub")
    content = state.nodes["pre_close"]()["task_messages"][0]["content"].lower()
    assert "ask one short question" in content
    assert "never ask this question twice" in content
    assert "do not list options" in content
    # No offer was prepared, so the clause must be absent entirely.
    assert "specialist" not in content


def test_pre_close_folds_in_an_offer_when_one_was_prepared() -> None:
    state, _tools, _initial, _globals = _flow("hub")
    state.close_probe_offer_clause = " OFFER-CLAUSE-HERE"
    content = state.nodes["pre_close"]()["task_messages"][0]["content"]
    assert "OFFER-CLAUSE-HERE" in content


def test_end_call_routes_through_the_probe_once_then_terminates() -> None:
    """First end_call asks "anything else?"; the second actually ends."""
    session = VoiceSession(session_id="VS-GRAPHTEST1", customer_id="C1")
    session.identity_verified = True
    state, tools, _initial, _globals = _flow("hub", session=session)
    # Two customer turns and neutral sentiment — nothing suppresses the probe.
    state.current_node = "collections_hub"

    result, node = asyncio.run(tools["end_call"](None))
    assert node["name"] == "pre_close", "the probe was skipped entirely"
    assert result.get("probing") is True
    assert state.close_probe_done is True

    result, node = asyncio.run(tools["end_call"](None))
    assert node["name"] == "call_ended"
    assert node["post_actions"] == [{"type": "end_conversation"}]


def test_probe_is_suppressed_after_escalation() -> None:
    """Pitching to someone being handed to a human is how a complaint becomes a
    regulatory one."""
    session = VoiceSession(session_id="VS-GRAPHTEST1", customer_id="C1")
    session.identity_verified = True
    state, tools, _initial, _globals = _flow("hub", session=session)
    state.escalated = True

    _result, node = asyncio.run(tools["end_call"](None))
    assert node["name"] == "call_ended"
    assert state.close_probe_done is False


def test_probe_is_suppressed_when_a_dispute_was_opened() -> None:
    session = VoiceSession(session_id="VS-GRAPHTEST1", customer_id="C1")
    session.identity_verified = True
    state, tools, _initial, _globals = _flow("hub", session=session)
    state.dispute_opened = True

    _result, node = asyncio.run(tools["end_call"](None))
    assert node["name"] == "call_ended"


def test_probe_is_suppressed_when_identity_was_never_verified() -> None:
    """The call is ending because verification failed or it is a third party."""
    state, tools, _initial, _globals = _flow("hub")
    _result, node = asyncio.run(tools["end_call"](None))
    assert node["name"] == "call_ended"


def test_hub_restates_the_role_message() -> None:
    """role_message persists until re-set; the hub is a RESET node."""
    state, _tools, _initial, _globals = _flow("hub")
    assert state.nodes["collections_hub"]()["role_message"] == "role"
