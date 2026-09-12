"""The hop swaps the brief and the grant, and does not touch the prompt.

Three claims, each of which was false before this chunk:

* the receiving specialist speaks on *its* grant, not the sending one's;
* what crosses the boundary is facts, never a decision an engine must make;
* the system message is byte-identical across a hop, so the prefix cache the
  whole latency argument rests on is not thrown away by the transfer.

The third is asserted rather than argued because nothing in this tree has ever
observed a prompt-cache hit. Byte-identity is the half that *is* checkable in
CI, so it is checked here and the millisecond claim is left unmade.
"""

from __future__ import annotations

import agent_core.cards.compile as card_compile
from agent_core.cards.defaults import COLLECTIONS_BOT_ID, INSURANCE_BOT_ID, collections_card
from agent_core.cards.schema import parse_card
from agent_core.context import (
    HANDOFF_PACKET_PREFIX,
    PACKET_FIELDS,
    handoff_packet,
    handoff_packet_message,
)
from agent_core.fleet.schema import ChannelGrant, CompiledBundle, CompiledHashes
from flow_graph import parse_graph
from flow_vars import FlowVariables
from flow_walk import FlowWalker, specialist_grants


class _Session:
    """Whatever the audio path would hand the packet renderer."""

    identity_verified = True
    disclosure_done = True
    call_goal = "dispute a late fee"
    call_goal_intent = "dispute"
    language = "en-IN"
    sentiment = "-0.2"
    commitments = ["PR-12 on the 5th"]
    open_questions: list[str] = []
    # Deliberately present and deliberately not carried.
    waiver_amount = 500
    next_contact_at = "2026-09-09T10:00:00Z"


def _bundle(**kw) -> CompiledBundle:
    return CompiledBundle(
        bot_id=COLLECTIONS_BOT_ID,
        hashes=CompiledHashes(prompt="", persona="", guardrails="", flow="", card=""),
        grants=[
            ChannelGrant(channel="voice", allowed=["get_account_position", "apply_goodwill"]),
        ],
        **kw,
    )


def _graph() -> dict:
    def node(key, start=False):
        return {
            "id": f"n-{key.replace('/', '-')}",
            "type": "conversation",
            "key": key,
            "data": {"name": key, "isStart": start, "tools": []},
        }

    return {
        "version": 1,
        "globalTools": [],
        "nodes": [node("collections/negotiate_ptp", start=True), node("insurance/pitch")],
        "edges": [],
    }


# --- the packet -------------------------------------------------------------


def test_the_packet_carries_facts() -> None:
    packet = handoff_packet(_Session())
    assert packet["identity_verified"] is True
    assert packet["call_goal"] == "dispute a late fee"
    assert packet["commitments"] == ["PR-12 on the 5th"]


def test_the_packet_cannot_carry_a_decision() -> None:
    """The omissions are the design, so they are what the test holds down.

    A packet with a member for an amount or a contact time would let a sending
    specialist launder a figure past the engine that is supposed to produce it —
    ``evaluate_authority`` for money, ``contact_policy`` for when to call. The
    receiver asks the engine again, on its own grant.
    """
    packet = handoff_packet(_Session())
    for banned in ("waiver_amount", "next_contact_at", "offer", "amount"):
        assert banned not in packet
    assert not {f for f in PACKET_FIELDS} & {"amount", "waiver", "offer", "callback_at"}


def test_an_empty_packet_renders_no_message() -> None:
    """Nothing established yet is a shorter context, not an empty header."""
    assert handoff_packet_message({}) is None


def test_the_packet_message_is_deterministic() -> None:
    """Same state, same bytes — which is what makes the hop's cost reviewable."""
    first = handoff_packet_message(handoff_packet(_Session()))
    second = handoff_packet_message(handoff_packet(_Session()))
    assert first == second
    assert first["role"] == "developer"
    assert first["content"].startswith(HANDOFF_PACKET_PREFIX)


def test_the_packet_block_is_replaced_not_appended() -> None:
    """A second hop must evict the first, not leave two versions in context.

    The mechanism is the prefix: ``replace_developer`` keys off it, exactly as
    the skill runtime already does for ``ACTIVE SKILL``. Pinning the constant is
    what stops a rename silently turning replacement into accumulation.
    """
    from tests.voice_tools_source import source

    assert "replace_developer(HANDOFF_PACKET_PREFIX" in source()


# --- the grant --------------------------------------------------------------


def test_a_flat_graph_keeps_the_whole_grant() -> None:
    """The assertion that says nothing shipped today changes."""
    walker = FlowWalker(parse_graph(_graph()), FlowVariables({}))
    walker.namespace = None
    assert walker.narrow({"a", "b"}, {}) == {"a", "b"}
    assert walker.narrow({"a", "b"}, None) == {"a", "b"}


def test_the_speaking_member_owns_the_grant() -> None:
    walker = FlowWalker(parse_graph(_graph()), FlowVariables({}))
    grants = {"collections": {"apply_goodwill"}, "insurance": {"recommend_next_offer"}}
    assert walker.narrow({"apply_goodwill", "recommend_next_offer"}, grants) == {
        "apply_goodwill"
    }
    walker.move_to(walker.node("insurance/pitch"))
    assert walker.narrow({"apply_goodwill", "recommend_next_offer"}, grants) == {
        "recommend_next_offer"
    }


def test_a_member_grant_narrows_and_never_widens() -> None:
    """A compiled bundle is not a way around the card."""
    walker = FlowWalker(parse_graph(_graph()), FlowVariables({}))
    grants = {"collections": {"apply_goodwill", "wire_money"}}
    assert walker.narrow({"apply_goodwill"}, grants) == {"apply_goodwill"}


def test_an_unknown_specialist_falls_back_rather_than_stranding_a_call() -> None:
    bundle = _bundle(grant_by_specialist={"insurance": ["recommend_next_offer"]})
    assert bundle.allowed_for("voice", "insurance") == {"recommend_next_offer"}
    assert bundle.allowed_for("voice", "nobody") == {
        "get_account_position",
        "apply_goodwill",
    }
    assert bundle.allowed_for("voice") == {"get_account_position", "apply_goodwill"}


def test_the_grants_reader_is_defensive_about_an_older_bundle() -> None:
    assert specialist_grants(None) == {}
    assert specialist_grants({}) == {}
    assert specialist_grants({"grant_by_specialist": "nonsense"}) == {}
    assert specialist_grants({"grant_by_specialist": {"a": ["x"]}}) == {"a": {"x"}}


# --- the card ---------------------------------------------------------------


def test_a_stored_card_still_parses_with_the_new_handoff_fields() -> None:
    """``extra='forbid'`` makes "all defaulted" a real constraint, not a hope."""
    card = collections_card()
    reparsed = parse_card(card.model_dump(mode="json"))
    assert reparsed.memory.max_hops_per_call == 2
    for handoff in reparsed.handoffs:
        assert handoff.carry == "brief"
        assert handoff.bridge_line == ""


def test_the_hop_cap_is_bounded() -> None:
    import pytest
    from pydantic import ValidationError

    raw = collections_card().model_dump(mode="json")
    raw["memory"]["max_hops_per_call"] = 99
    with pytest.raises(ValidationError):
        parse_card(raw)


# --- the gates --------------------------------------------------------------


def test_gf4_passes_when_the_card_names_its_targets() -> None:
    card = collections_card()
    gate = card_compile._handoff_edge_gate({}, card, {"handoff_to_agent"})
    assert gate.status == "pass"
    assert gate.gate == "G-F4"


def test_gf4_fails_a_granted_transfer_with_nowhere_to_go() -> None:
    """The tool is offered and every call it makes is refused.

    ``handoff_allowlist`` builds the enforcement set from ``card.handoffs``, so
    this is not a style opinion — it is a dead tool the author cannot see,
    because the Tools tab shows the grant and the canvas shows the step and
    neither shows the empty allowlist between them.
    """
    raw = collections_card().model_dump(mode="json")
    raw["handoffs"] = []
    gate = card_compile._handoff_edge_gate({}, parse_card(raw), {"handoff_to_agent"})
    assert gate.status == "fail"


def test_gf4_is_skipped_when_the_card_cannot_transfer_at_all() -> None:
    raw = collections_card().model_dump(mode="json")
    raw["handoffs"] = []
    gate = card_compile._handoff_edge_gate({}, parse_card(raw), {"get_account_position"})
    assert gate.status == "skipped"


def test_gf7_passes_a_fact_only_payload() -> None:
    gate = card_compile._carry_gate(collections_card())
    assert gate.status in {"pass", "skipped"}
    assert gate.gate == "G-F7"


def test_gf7_warns_on_a_payload_that_carries_a_decision() -> None:
    raw = collections_card().model_dump(mode="json")
    raw["handoffs"] = [
        {
            "to_bot_id": INSURANCE_BOT_ID,
            "when": "in-policy upsell",
            "payload_schema": {"waiver_amount": "number", "call_goal": "string"},
        }
    ]
    gate = card_compile._carry_gate(parse_card(raw))
    assert gate.status == "warn"
    assert "waiver_amount" in gate.detail
    assert "call_goal" not in gate.detail


# --- the prefix -------------------------------------------------------------


def test_only_the_entry_node_carries_the_system_message() -> None:
    """The byte-identity half of the latency claim, checked rather than argued.

    The whole reason the Compiled Fleet refuses a process per specialist is that
    a hop must not change the system message — a changed prefix is a cache miss
    on the one channel where sub-second turns bind. That is true only while
    ``role_message`` is emitted on the entry node alone, so this is the assertion
    that fails the day someone restates the persona on a hop.

    No millisecond figure is asserted. Nothing in this tree has ever observed a
    prompt-cache hit, and this test does not pretend otherwise; it pins the one
    thing that is checkable in CI.
    """
    from tests.test_flow_export import _stub_session
    from voice.flow_export import built_in_collections_graph
    from voice.flows_dynamic import build_authored_flow

    graph = built_in_collections_graph()
    state, _tools, initial, _globals = build_authored_flow(
        _stub_session(), graph, role_message="You are Priya.", bot_id="kaia-v2-4"
    )
    assert initial()["role_message"] == "You are Priya."
    carriers = [key for key, factory in state.nodes.items() if "role_message" in factory()]
    assert carriers == [initial()["name"]]


def test_a_hop_does_not_rebuild_the_tool_registry() -> None:
    """A hop is a pointer swap, which is what makes it cheap.

    ``build_tools`` builds one dict holding the union over members; the
    narrowing to the speaking one is a per-node predicate. If a hop had to
    rebuild the schemas, the cost would land mid-call on the audio path.
    """
    from tests.test_flow_export import _stub_session
    from voice.flow_export import built_in_collections_graph
    from voice.flows_dynamic import build_authored_flow

    state, tools, _initial, _globals = build_authored_flow(
        _stub_session(),
        built_in_collections_graph(),
        role_message="",
        bot_id="kaia-v2-4",
        allowed_tool_names={"get_account_position"},
        specialist_grants={
            "collections": {"get_account_position"},
            "insurance": {"recommend_next_offer"},
        },
    )
    before = set(tools)
    state.active_specialist = "insurance"
    assert set(tools) == before
    assert state.may_offer("get_account_position", namespace="collections") is True
    assert state.may_offer("get_account_position", namespace="insurance") is False
    # An unknown member falls back rather than amputating a live call; a
    # namespace that should not have been reachable is G-F4's job, before the
    # call, not something to discover as a silent loss of tools mid-sentence.
    assert state.may_offer("get_account_position", namespace="nobody") is True
    # The floor is never narrowed away: a mouth that cannot hang up is broken,
    # not safe.
    assert state.may_offer("end_call", namespace="insurance") is True
    # The union is what got built, so a hop finds the target's tools already
    # in the registry.
    assert "recommend_next_offer" in tools


def test_system_message_hash_is_stable_across_a_hop() -> None:
    """Assemble at the door, hop into the specialist, assemble again: same bytes.

    Pipecat keeps the existing system message when a node config carries no
    ``role_message`` (``flows_dynamic`` restates it on the entry node only), so
    the merged fleet graph's member entries must carry none. Asserted as a
    digest over the message the door assembles versus the one the hop would
    leave in place -- the CI-checkable half of "a hop costs no prefix".
    """
    import hashlib

    from agent_core.fleet.compile import _merge_members
    from tests.test_flow_export import _stub_session
    from voice.flow_export import built_in_collections_graph
    from voice.flows_dynamic import build_authored_flow

    door = built_in_collections_graph(part="door")
    fleet_flow, entries, _grants = _merge_members(
        primary_bot_id="intake-v1",
        primary_flow=door,
        primary_grant=set(),
        members=[{"bot_id": "kaia-v2-4", "flow": built_in_collections_graph(), "card": {}}],
    )
    assert set(entries) == {"intake-v1", "kaia-v2-4"}
    state, _tools, initial, _globals = build_authored_flow(
        _stub_session(),
        fleet_flow,
        role_message="You are Priya.",
        bot_id="intake-v1",
        specialist_entries=entries,
    )
    before = hashlib.sha256(initial()["role_message"].encode()).hexdigest()
    landing = state.nodes[entries["kaia-v2-4"]]()
    assert "role_message" not in landing, "the hop restates the system message"
    after = hashlib.sha256((landing.get("role_message") or initial()["role_message"]).encode()).hexdigest()
    assert before == after
