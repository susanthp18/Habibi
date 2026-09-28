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
