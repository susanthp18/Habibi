"""SCAFFOLDING — delete this file in #13, with the formulas it pins.

``ToolGrant`` is introduced beside the seven formulas that answer some version
of "which tools may this agent call". This file proves the new module already
agrees with them, so the migration tickets can move one call site at a time and
know that nothing moved. It is evidence for a refactor, not coverage of a
behaviour; once the old formulas are deleted there is nothing left to compare
against and this file goes with them.

The seven, and where each lives today:

1. ``intersect.effective_tools``            the grant
2. ``intersect.idle_offered_tools``         the offer, no skill active
3. ``intersect.offered_tools``              the offer, a skill active
4. the publish gate's private scope formula (``cards/compile.py``, G9)
5. ``bot_tools.TOOL_DEFINITIONS``           text runtime's cardless fallback
6. the voice runtime's keep-set literal     (``voice/tools.py``)
7. ``sandbox_runtime._SANDBOX_TOOL_NAMES``  sandbox's cardless fallback

Where ``ToolGrant`` deliberately differs it is asserted as a difference, with
the ticket that makes it visible named. A characterization test that quietly
absorbed an intended change would be worse than none.

No database: pack resolution falls back to the on-disk first-party packs.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent_core.cards.defaults import FIRST_PARTY_BOT_IDS, card_dump
from agent_core.skills.intersect import (
    PLATFORM_SKILL_TOOLS,
    effective_tools,
    idle_offered_tools,
    offered_tools,
)
from agent_core.skills.runtime import resolve_mouth
from agent_core.tools.catalog import CATALOG
from agent_core.tools.grant import TEXT, VOICE, VOICE_ALWAYS, VOICE_FLOW_TOOLS, ToolGrant

CATALOG_NAMES = set(CATALOG.specs)
BOTS = sorted(FIRST_PARTY_BOT_IDS)
CHANNELS = [VOICE, TEXT]


def _mouth(bot_id: str):
    return resolve_mouth(card_dump(bot_id))


def _pinned_voice_control_tools() -> frozenset[str]:
    """The nine names as the voice registry contract states them.

    Read out of the source rather than imported: that module builds the entire
    voice tool surface at import time, and this needs one literal.
    """
    src = Path(__file__).with_name("test_voice_tool_registry.py").read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == "VOICE_CONTROL_TOOLS" for target in node.targets
        ):
            return frozenset(ast.literal_eval(node.value.args[0]))
    raise AssertionError("VOICE_CONTROL_TOOLS is no longer declared where this test reads it")


def _today_grant(mouth) -> set[str]:
    """Formula 1, called the way every runtime calls it today: no channel."""
    return set(
        effective_tools(
            mouth.card,
            catalog_names=CATALOG_NAMES,
            attached_skills=list(mouth.packs) or None,
        )
    )


def _voice_only_on(mouth) -> set[str]:
    """Catalog tools this card grants today that the text channel cannot render."""
    voice = {s.name for s in CATALOG.for_channel(VOICE)}
    text = {s.name for s in CATALOG.for_channel(TEXT)}
    return _today_grant(mouth) & (voice - text)


# --- 1. the grant -----------------------------------------------------------


@pytest.mark.parametrize("bot_id", BOTS)
def test_voice_grant_is_todays_answer_plus_the_tools_voice_always_keeps(bot_id) -> None:
    """Formula 1 on voice. The only additions are the keep-set the voice runtime
    already unions in by hand, so no voice call gains or loses a tool."""
    mouth = _mouth(bot_id)
    grant = ToolGrant._build(mouth.card, mouth.packs, channel=VOICE)
    assert grant.allowed - _today_grant(mouth) == VOICE_ALWAYS
    assert not _today_grant(mouth) - grant.allowed


@pytest.mark.parametrize("bot_id", BOTS)
def test_text_grant_drops_exactly_the_voice_only_tools(bot_id) -> None:
    """Formula 1 on text, and the one intended difference in this ticket.

    The catalog's renderer applies its channel filter only when given no
    explicit name list, and the text runtime always gives it one built from the
    whole catalog — so a card naming a voice-only tool renders it into the
    WhatsApp list where no handler exists. #10 makes this visible.
    """
    mouth = _mouth(bot_id)
    grant = ToolGrant._build(mouth.card, mouth.packs, channel=TEXT)
    assert _today_grant(mouth) - grant.allowed == _voice_only_on(mouth)
    assert not grant.allowed - _today_grant(mouth)


# --- 2 and 3. the offers ----------------------------------------------------


@pytest.mark.parametrize("bot_id", BOTS)
def test_idle_offer_matches_todays_idle_offer(bot_id) -> None:
    mouth = _mouth(bot_id)
    today = set(
        idle_offered_tools(
            mouth.card,
            catalog_names=CATALOG_NAMES,
            attached_skills=list(mouth.packs) or None,
        )
    )
    text_offer = set(ToolGrant._build(mouth.card, mouth.packs, channel=TEXT).offer())
    assert today - text_offer == _voice_only_on(mouth)
    assert not text_offer - today

    voice_offer = set(ToolGrant._build(mouth.card, mouth.packs, channel=VOICE).offer())
    assert voice_offer - today == VOICE_ALWAYS


@pytest.mark.parametrize("bot_id", BOTS)
def test_active_skill_offer_matches_todays(bot_id) -> None:
    mouth = _mouth(bot_id)
    if not mouth.packs:
        pytest.skip(f"{bot_id} attaches no skill packs")
    slug = mouth.packs[0].slug
    today = set(
        offered_tools(
            mouth.card,
            catalog_names=CATALOG_NAMES,
            attached_skills=list(mouth.packs),
            active_slug=slug,
        )
    )
    grant = ToolGrant._build(mouth.card, mouth.packs, channel=TEXT)
    assert today - set(grant.offer(active_skill=slug)) == _voice_only_on(mouth)


@pytest.mark.parametrize("bot_id", BOTS)
def test_an_offer_is_always_inside_the_grant(bot_id) -> None:
    """ADR-0001: narrowing what the model is shown must never widen what it may
    run. Checked for every attached skill, not just the idle case."""
    mouth = _mouth(bot_id)
    for channel in CHANNELS:
        grant = ToolGrant._build(mouth.card, mouth.packs, channel=channel)
        assert set(grant.offer()) <= grant.allowed
        for pack in mouth.packs:
            assert set(grant.offer(active_skill=pack.slug)) <= grant.allowed


# --- 4. the publish gate's private formula ----------------------------------


@pytest.mark.parametrize("bot_id", BOTS)
def test_static_scope_against_the_publish_gates_formula(bot_id) -> None:
    """G9 computes ``include | locked | platform`` and never intersects the
    catalog. Two documented differences, both of which #12 makes real:

    * G9 permits names no runtime could ever call — locked engines that have no
      mouth tool, and skill-gated tools no attached pack grants.
    * G9 omits the voice flow tools, which the runtime does grant.
    """
    mouth = _mouth(bot_id)
    card = mouth.card
    g9 = set(card.tools.include) | set(card.tools.locked) | PLATFORM_SKILL_TOOLS
    static = ToolGrant.static_scope(card, mouth.packs)

    assert static - g9 == VOICE_ALWAYS

    unreachable = g9 - static
    locked_without_a_mouth_tool = {"evaluate_live_qa", "recommend_treatment"}
    assert locked_without_a_mouth_tool <= unreachable
    # Whatever else G9 permits must be a catalog tool that no attached pack
    # grants — never a name the runtime would have granted.
    for name in unreachable - locked_without_a_mouth_tool:
        assert name in CATALOG_NAMES
        assert not any(name in p.allowed_tools for p in mouth.packs)


@pytest.mark.parametrize("bot_id", BOTS)
def test_static_scope_is_the_union_of_every_dynamic_answer(bot_id) -> None:
    """The invariant that stops an eighth formula: a gate passing must imply the
    runtime permits. Built as the union rather than restated, so a future
    private calculation would have to break this to exist."""
    mouth = _mouth(bot_id)
    static = ToolGrant.static_scope(mouth.card, mouth.packs)
    union: set[str] = set()
    for channel in CHANNELS:
        union |= ToolGrant._build(mouth.card, mouth.packs, channel=channel).allowed
    assert union == static


# --- 6. the voice runtime's keep-set ----------------------------------------


def test_the_flow_tools_match_the_voice_registry_contract() -> None:
    """Two independent statements of the same nine names must agree.

    ``tests/test_voice_tool_registry.py`` pins them as "deliberately not in
    CATALOG"; this module owns them as part of the grant. Reading its literal
    rather than restating it is what stops the pair drifting before #13 deletes
    the keep-set in the voice runtime.
    """
    assert VOICE_FLOW_TOOLS == _pinned_voice_control_tools()
    assert VOICE_ALWAYS - VOICE_FLOW_TOOLS == {"capture_call_goal"}
    # The tenth is a real catalog tool, voice-only, on no card's include list:
    # the built-in flow captures the caller's goal before identity is confirmed.
    assert "capture_call_goal" in CATALOG_NAMES
    assert not VOICE_FLOW_TOOLS & CATALOG_NAMES


@pytest.mark.parametrize("bot_id", BOTS)
def test_flow_tools_are_granted_on_voice_and_absent_on_text(bot_id) -> None:
    mouth = _mouth(bot_id)
    assert VOICE_ALWAYS <= ToolGrant._build(mouth.card, mouth.packs, channel=VOICE).allowed
    text = ToolGrant._build(mouth.card, mouth.packs, channel=TEXT).allowed
    assert not VOICE_ALWAYS & text


# --- 5 and 7. the two cardless fallbacks ------------------------------------


def test_the_module_does_not_reproduce_the_cardless_fallbacks() -> None:
    """Formulas 5 and 7 are what the text and sandbox runtimes use when no card
    resolves. ``ToolGrant`` grants nothing there instead (ADR-0002), so this
    asserts the *difference* rather than pretending to reproduce it.

    Both lists contain skill-gated writes, which is the fail-open ADR-0002
    retires. They stay reachable through ``is_cardless`` until #14 deletes the
    branches that read them.
    """
    import bot_tools
    from sandbox_runtime import _SANDBOX_TOOL_NAMES

    text_fallback = {t["function"]["name"] for t in bot_tools.TOOL_DEFINITIONS}
    sandbox_fallback = set(_SANDBOX_TOOL_NAMES)
    assert "create_promise_to_pay" in text_fallback
    assert "create_promise_to_pay" in sandbox_fallback

    for channel in CHANNELS:
        grant = ToolGrant._build(None, (), channel=channel)
        assert grant.is_cardless
        assert grant.allowed == frozenset()
        assert grant.offer() == ()
        assert not grant.may_execute("create_promise_to_pay")


# --- properties that hold whatever the card says ----------------------------


@pytest.mark.parametrize("bot_id", BOTS)
def test_locked_mouth_tools_are_granted_regardless_of_pack_attachment(bot_id) -> None:
    """A locked engine cannot be unbound by detaching a skill. Checked with no
    packs at all, which is the state a pack-resolution failure produces."""
    from agent_core.cards.schema import LOCKED_MOUTH_TOOLS

    card = _mouth(bot_id).card
    for channel in CHANNELS:
        allowed = ToolGrant._build(card, (), channel=channel).allowed
        expected = {
            n
            for n in LOCKED_MOUTH_TOOLS
            if n in CATALOG_NAMES and n in {s.name for s in CATALOG.for_channel(channel)}
        }
        assert expected <= allowed


@pytest.mark.parametrize("bot_id", BOTS)
def test_the_grant_is_frozen(bot_id) -> None:
    mouth = _mouth(bot_id)
    assert isinstance(ToolGrant._build(mouth.card, mouth.packs, channel=VOICE).allowed, frozenset)


def test_for_bundle_reads_the_card_off_a_deployment_bundle() -> None:
    """The runtime constructor. Taking a bundle rather than a card is what lets
    a handoff hand the receiving agent's bundle straight in."""
    bundle = {"agentCard": card_dump(BOTS[0])}
    grant = ToolGrant.for_bundle(bundle, channel=VOICE)
    assert not grant.is_cardless
    assert grant.allowed == ToolGrant._build(*_pair(BOTS[0]), channel=VOICE).allowed
    assert ToolGrant.for_bundle({}, channel=VOICE).is_cardless
    assert ToolGrant.for_bundle({"agentCard": {}}, channel=TEXT).is_cardless


def _pair(bot_id):
    mouth = _mouth(bot_id)
    return mouth.card, mouth.packs
