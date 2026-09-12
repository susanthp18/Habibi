"""The card's handoffs are in the tool the model is offered.

**GRAPH-3.** ``card.handoffs[].when`` was authored in the Agent graph tab under
the words "The condition is guidance for the model, not a rule the runtime
enforces", stored on the card, checked by G5 at publish — and read by nobody.
``handoff_to_agent``'s ``target_bot_id`` description was a static string naming
two example bot ids, so the model was never told which specialists *this* card
can reach, or when. The default cards' own conditions ("collections intent",
"in-policy upsell after PTP") were decoration.

The enum is built from the same card the allowlist is built from, so the tool
cannot advertise a target ``domain.handoff_to_agent`` would then refuse.
"""

from __future__ import annotations

import inspect

from agent_core.cards.defaults import COLLECTIONS_BOT_ID, INTAKE_BOT_ID, card_dump
from agent_core.tools.catalog import CATALOG
from agent_core.tools.handoff_allowlist import (
    handoff_allowlist,
    handoff_routes,
    handoff_tool_spec,
    specialise_handoff_tool,
)

SPEC = CATALOG.get("handoff_to_agent")


def _target_arg(spec):
    return next(a for a in spec.args if a.name == "target_bot_id")


# ---------------------------------------------------------------------------
# The routes come off the card
# ---------------------------------------------------------------------------


def test_the_when_condition_is_read_at_last() -> None:
    routes = handoff_routes(agent_card=card_dump(COLLECTIONS_BOT_ID))
    assert routes, "the collections card authors handoffs"
    assert all(when for _, when in routes), "every default route states a condition"


def test_the_model_is_told_the_target_and_the_condition() -> None:
    spec = handoff_tool_spec(SPEC, agent_card=card_dump(COLLECTIONS_BOT_ID))
    described = _target_arg(spec).description
    for target, when in handoff_routes(agent_card=card_dump(COLLECTIONS_BOT_ID)):
        assert target in described
        assert when in described


def test_the_enum_is_the_allowlist_that_enforces_it() -> None:
    """One reading of one card. A tool that advertised a target the allowlist
    refuses would be a worse lie than the static string it replaced."""
    for bot_id in (COLLECTIONS_BOT_ID, INTAKE_BOT_ID):
        raw = card_dump(bot_id)
        spec = handoff_tool_spec(SPEC, agent_card=raw)
        assert set(_target_arg(spec).enum) == handoff_allowlist(agent_card=raw), bot_id


def test_the_catalog_spec_itself_is_never_mutated() -> None:
    """``specialise`` returns a copy: the registry is process-wide and a call
    for one card must not change what the next card is offered."""
    before = _target_arg(SPEC).description
    handoff_tool_spec(SPEC, agent_card=card_dump(COLLECTIONS_BOT_ID))
    handoff_tool_spec(SPEC, agent_card=card_dump(INTAKE_BOT_ID))
    assert _target_arg(CATALOG.get("handoff_to_agent")).description == before
    assert _target_arg(CATALOG.get("handoff_to_agent")).enum is None


def test_two_cards_get_two_different_tools() -> None:
    collections = handoff_tool_spec(SPEC, agent_card=card_dump(COLLECTIONS_BOT_ID))
    intake = handoff_tool_spec(SPEC, agent_card=card_dump(INTAKE_BOT_ID))
    assert set(_target_arg(collections).enum) != set(_target_arg(intake).enum)


# ---------------------------------------------------------------------------
# Fail closed, exactly as the allowlist does
# ---------------------------------------------------------------------------


def test_a_card_with_no_handoffs_is_the_catalog_tool_unchanged() -> None:
    assert specialise_handoff_tool(SPEC, []) is SPEC


def test_an_unreadable_card_describes_no_route() -> None:
    assert handoff_routes(agent_card={"not": "a card"}) == []
    assert handoff_tool_spec(SPEC, agent_card={"not": "a card"}) is SPEC


def test_an_unknown_bot_describes_no_route() -> None:
    assert handoff_routes(bot_id="no-such-bot") == []


def test_a_route_with_no_condition_still_names_its_target() -> None:
    spec = specialise_handoff_tool(SPEC, [("insurance-v1", "")])
    arg = _target_arg(spec)
    assert arg.enum == ("insurance-v1",)
    assert "insurance-v1" in arg.description
    assert "—" not in arg.description


# ---------------------------------------------------------------------------
# Both renderers
# ---------------------------------------------------------------------------


def test_the_openai_tool_carries_the_enum() -> None:
    spec = handoff_tool_spec(SPEC, agent_card=card_dump(COLLECTIONS_BOT_ID))
    rendered = spec.to_openai_tool()
    prop = rendered["function"]["parameters"]["properties"]["target_bot_id"]
    assert set(prop["enum"]) == handoff_allowlist(agent_card=card_dump(COLLECTIONS_BOT_ID))


def test_the_flows_schema_carries_it_too() -> None:
    spec = handoff_tool_spec(SPEC, agent_card=card_dump(COLLECTIONS_BOT_ID))
    schema = spec.to_flows_schema(lambda **_: None)
    prop = schema.properties["target_bot_id"]
    assert "enum" in prop


def test_voice_specialises_at_the_offer_site() -> None:
    from tests.voice_tools_source import source

    src = source()
    assert 'if name == "handoff_to_agent"' in src
    assert "handoff_tool_spec(spec, agent_card=agent_card, bot_id=bot_id)" in src


def test_text_specialises_at_its_own_offer_site() -> None:
    import bot_runtime

    src = inspect.getsource(bot_runtime)
    assert "def _turn_tools(" in src
    assert 'if s.name == "handoff_to_agent"' in src
    # The unspecialised renderer must not survive alongside it on this path.
    assert "CATALOG.openai_tools(list(tool_state.offered" not in src


def test_the_enum_is_prefix_weight_the_budget_gate_already_counts() -> None:
    """G6 caps the prompt prefix, and this adds to it. Small, and bounded by
    the card's own handoff list — but it is not free, so it is stated."""
    plain = len(_target_arg(SPEC).description)
    specialised = len(
        _target_arg(handoff_tool_spec(SPEC, agent_card=card_dump(COLLECTIONS_BOT_ID))).description
    )
    assert specialised > plain
    assert specialised < plain + 400
