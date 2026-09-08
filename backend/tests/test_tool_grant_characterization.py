"""SCAFFOLDING — delete this file in #13, with the formulas it pins.

``ToolGrant`` is introduced beside the seven formulas that answer some version
of "which tools may this agent call". This file proves the new module already
agrees with them, so the migration tickets can move one call site at a time and
know that nothing moved. It is evidence for a refactor, not coverage of a
behaviour; once the old formulas are deleted there is nothing left to compare
against and this file goes with them.

``tests/test_tool_grant.py`` holds the grant's own guarantees and is permanent.
Nothing here duplicates it: every assertion below names an old formula.

The seven, and where each lives today:

1. ``intersect.effective_tools``            the grant
2. ``intersect.idle_offered_tools``         the offer, no skill active
3. ``intersect.offered_tools``              the offer, a skill active
4. the publish gate's private scope formula (``cards/compile.py``, G9)
5. ~~``bot_tools.TOOL_DEFINITIONS``~~       deleted — text cardless is deny-all
6. the voice runtime's ``ALWAYS_ON``        pinned in test_tool_grant.py
7. ~~``sandbox_runtime._SANDBOX_TOOL_NAMES``~~ deleted — sandbox cardless is deny-all

5 and 7 used to be asserted as a *difference*: ADR-0002 made the module deny-all
where those fell open. The lists are gone; the pin now is that they stay gone.

Packs come from the ``card_and_packs`` fixture, which reads them off disk.
``packs_from_card`` fails *closed* to an empty list when the database is
unreachable, so resolving the normal way made this suite pass by comparing
empty sets to empty sets — the formula-3 cases skipped outright and every
gating assertion went vacuous. Verified, not assumed: with the database
unreachable the earlier version reported 41 passed, 4 skipped.
"""

from __future__ import annotations

import pytest

from agent_core.cards.defaults import FIRST_PARTY_BOT_IDS
from agent_core.skills.intersect import (
    PLATFORM_SKILL_TOOLS,
    effective_tools,
    idle_offered_tools,
    offered_tools,
)
from agent_core.tools.catalog import CATALOG
from agent_core.tools.grant import TEXT, TEXT_ALWAYS, VOICE, VOICE_ALWAYS, ToolGrant

CATALOG_NAMES = set(CATALOG.specs)
BOTS = sorted(FIRST_PARTY_BOT_IDS)
CHANNELS = [VOICE, TEXT]


def _today_grant(card, packs) -> set[str]:
    """Formula 1, unchannelled — the intersect call without ``channel_tools``.

    Production runtimes now pass ``channel_tools`` (WP-031 step 1). This helper
    stays the old call so the characterization still compares ToolGrant against
    the formula it replaces, not against MouthTurn's new forwarding.
    """
    return set(
        effective_tools(card, catalog_names=CATALOG_NAMES, attached_skills=list(packs))
    )


def _voice_only_on(card, packs) -> set[str]:
    """Catalog tools this card grants today that the text channel cannot render.

    The one intended difference in this ticket: the catalog's renderer applies
    its channel filter only when given no explicit name list, and the text
    runtime always gives it one built from the whole catalog. #10 makes it
    visible.
    """
    voice = {s.name for s in CATALOG.for_channel(VOICE)}
    text = {s.name for s in CATALOG.for_channel(TEXT)}
    return _today_grant(card, packs) & (voice - text)


def _text_only_on(card, packs) -> set[str]:
    """The mirror of :func:`_voice_only_on`, and the second intended difference.

    The catalog has always had TEXT_ONLY specs; until a card included one, the
    asymmetry could not show. ``ingest_customer_document`` is now on the
    collections card, so the *voice* grant drops a name the unchannelled
    formula keeps — the same filter as above, read the other way round.
    """
    voice = {s.name for s in CATALOG.for_channel(VOICE)}
    text = {s.name for s in CATALOG.for_channel(TEXT)}
    return _today_grant(card, packs) & (text - voice)


# --- 1. the grant -----------------------------------------------------------


@pytest.mark.parametrize("bot_id", BOTS)
def test_voice_grant_is_todays_answer_plus_the_always_on_floor(bot_id, card_and_packs) -> None:
    card, packs = card_and_packs(bot_id)
    grant = ToolGrant.for_card(card, packs, channel=VOICE)
    assert grant.allowed == (_today_grant(card, packs) | VOICE_ALWAYS) - _text_only_on(
        card, packs
    )


@pytest.mark.parametrize("bot_id", BOTS)
def test_text_grant_drops_the_voice_only_tools_and_adds_the_text_floor(
    bot_id, card_and_packs
) -> None:
    card, packs = card_and_packs(bot_id)
    grant = ToolGrant.for_card(card, packs, channel=TEXT)
    assert grant.allowed == (
        _today_grant(card, packs) - _voice_only_on(card, packs)
    ) | TEXT_ALWAYS


# --- 2 and 3. the offers ----------------------------------------------------


@pytest.mark.parametrize("bot_id", BOTS)
def test_idle_offer_matches_todays_idle_offer(bot_id, card_and_packs) -> None:
    card, packs = card_and_packs(bot_id)
    today = set(
        idle_offered_tools(
            card, catalog_names=CATALOG_NAMES, attached_skills=list(packs)
        )
    )
    assert set(ToolGrant.for_card(card, packs, channel=TEXT).offer()) == (
        today - _voice_only_on(card, packs)
    ) | TEXT_ALWAYS
    assert set(ToolGrant.for_card(card, packs, channel=VOICE).offer()) == (
        today | VOICE_ALWAYS
    ) - _text_only_on(card, packs)


@pytest.mark.parametrize("bot_id", BOTS)
@pytest.mark.parametrize("channel", CHANNELS)
def test_active_skill_offer_matches_todays_on_both_channels(
    bot_id, channel, card_and_packs
) -> None:
    """Formula 3, for every attached pack rather than just the first, and on
    voice as well as text — an earlier version checked text only."""
    card, packs = card_and_packs(bot_id)
    grant = ToolGrant.for_card(card, packs, channel=channel)
    for pack in packs:
        today = set(
            offered_tools(
                card,
                catalog_names=CATALOG_NAMES,
                attached_skills=list(packs),
                active_slug=pack.slug,
            )
        )
        mine = set(grant.offer(active_skill=pack.slug))
        if channel == VOICE:
            assert mine == (today | VOICE_ALWAYS) - _text_only_on(card, packs)
        else:
            assert mine == (today - _voice_only_on(card, packs)) | TEXT_ALWAYS


# --- 4. the publish gate's private formula ----------------------------------


@pytest.mark.parametrize("bot_id", BOTS)
def test_static_grant_against_the_publish_gates_formula(bot_id, card_and_packs) -> None:
    """G9 computes ``include | locked | platform`` and never intersects the
    catalog. Two documented differences, both of which #12 makes real:

    * G9 permits names no runtime could ever call — locked engines that have no
      mouth tool, and skill-gated tools no attached pack grants.
    * G9 omits the always-on floor, which the runtime does grant. ``static_grant``
      unions both channels, so that floor is now ``VOICE_ALWAYS | TEXT_ALWAYS``.
    """
    card, packs = card_and_packs(bot_id)
    g9 = set(card.tools.include) | set(card.tools.locked) | PLATFORM_SKILL_TOOLS
    static = ToolGrant.static_grant(card, packs)

    # Everything the grant adds over G9 is the floor, and nothing else. Written
    # as a difference on both sides because three of the four cards already
    # include verify_identity, which is part of that floor.
    assert static - g9 == (VOICE_ALWAYS | TEXT_ALWAYS) - g9

    unreachable = g9 - static
    locked_without_a_mouth_tool = {"evaluate_live_qa", "recommend_treatment"}
    assert locked_without_a_mouth_tool <= unreachable
    for name in unreachable - locked_without_a_mouth_tool:
        # Anything else G9 permits must be a catalog tool no attached pack
        # grants — never a name the runtime would have granted.
        assert name in CATALOG_NAMES
        assert not any(name in p.allowed_tools for p in packs)


# --- 5 and 7. the two cardless fallbacks are gone ---------------------------


def test_the_cardless_fallbacks_are_gone() -> None:
    """The text and sandbox runtimes used these when no card resolved. Both
    contained skill-gated writes. ADR-0002 deleted the lists; a cardless mouth
    is granted nothing at the live seam, not only inside ToolGrant.
    """
    import bot_tools
    import sandbox_runtime
    from agent_core.skills.runtime import resolve_mouth

    assert not hasattr(bot_tools, "TOOL_DEFINITIONS")
    assert not hasattr(sandbox_runtime, "_SANDBOX_TOOL_NAMES")

    tools = resolve_mouth({}).tools()
    assert tools.allowed == frozenset()
    assert tools.offered == ()

    for channel in CHANNELS:
        assert ToolGrant.for_card(None, (), channel=channel).allowed == frozenset()
