"""The Tool Grant's own guarantees.

The properties ADR-0001 and ADR-0002 require the grant to hold forever;
ADR-0001 rejects a two-module design *because* "the relationship between them
is asserted by a test". The seven formulas the grant replaced are gone (the
characterization file that compared them went with the last one); what
remains beside the grant is the publish gate's *scope* check, which is not a
grant and is pinned below as exactly that.

``voice.tools.ALWAYS_ON`` is this module's ``VOICE_ALWAYS``, imported under
that name. The pin that they are the same object cannot import ``voice.tools``
in the API image or CI (pipecat is absent), so it reads the source instead.

Packs come from the ``card_and_packs`` fixture, which reads them off disk, so
nothing here needs a database — see the fixture for why that matters.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent_core.cards.defaults import FIRST_PARTY_BOT_IDS, card_dump
from agent_core.cards.schema import LOCKED_MOUTH_TOOLS
from agent_core.skills.intersect import PLATFORM_SKILL_TOOLS
from agent_core.tools.catalog import CATALOG
from agent_core.tools.grant import (
    TEXT,
    TEXT_ALWAYS,
    VOICE,
    VOICE_ALWAYS,
    VOICE_FLOW_TOOLS,
    ToolGrant,
)

CATALOG_NAMES = set(CATALOG.specs)
BOTS = sorted(FIRST_PARTY_BOT_IDS)
CHANNELS = [VOICE, TEXT]
BACKEND = Path(__file__).resolve().parents[1]


# --- ADR-0001: one owner, and the offer can never widen the grant -----------


@pytest.mark.parametrize("bot_id", BOTS)
def test_the_static_grant_is_the_union_of_every_dynamic_answer(bot_id, card_and_packs) -> None:
    """A gate passing must imply the runtime permits.

    ADR-0001 keeps the publish and runtime questions in one module because the
    static answer is definitionally the union of the dynamic ones. It is built
    that way rather than restated, and this asserts it stays so — a future
    private formula would have to break this test to exist.
    """
    card, packs = card_and_packs(bot_id)
    union: set[str] = set()
    for channel in CHANNELS:
        union |= ToolGrant.for_card(card, packs, channel=channel).allowed
    assert ToolGrant.static_grant(card, packs) == union


@pytest.mark.parametrize("bot_id", BOTS)
def test_an_offer_is_always_inside_the_grant(bot_id, card_and_packs) -> None:
    """Narrowing what the model is shown must never widen what it may run.

    Checked for every attached skill, not just the idle case, because
    activating a skill is exactly where an offer grows.
    """
    card, packs = card_and_packs(bot_id)
    for channel in CHANNELS:
        grant = ToolGrant.for_card(card, packs, channel=channel)
        assert set(grant.offer()) <= grant.allowed
        for pack in packs:
            offered = set(grant.offer(active_skill=pack.slug))
            assert offered <= grant.allowed
            assert all(grant.may_execute(name) for name in offered)


@pytest.mark.parametrize("bot_id", BOTS)
def test_the_grant_is_frozen(bot_id, card_and_packs) -> None:
    """ADR-0001: a caller holding a mutable set is free to union onto it, and
    six competing formulas is what that produced."""
    card, packs = card_and_packs(bot_id)
    assert isinstance(ToolGrant.for_card(card, packs, channel=VOICE).allowed, frozenset)
    assert isinstance(ToolGrant.static_grant(card, packs), frozenset)


@pytest.mark.parametrize("bot_id", BOTS)
def test_locked_engines_survive_losing_every_pack(bot_id, card_and_packs) -> None:
    """A locked engine cannot be unbound by detaching a skill. Checked with no
    packs at all, which is the state a pack-resolution failure produces."""
    card, _ = card_and_packs(bot_id)
    for channel in CHANNELS:
        allowed = ToolGrant.for_card(card, (), channel=channel).allowed
        renderable = {s.name for s in CATALOG.for_channel(channel)}
        assert {n for n in LOCKED_MOUTH_TOOLS if n in renderable} <= allowed


# --- ADR-0002: a cardless mouth is granted nothing --------------------------


@pytest.mark.parametrize("channel", CHANNELS)
def test_a_cardless_mouth_is_granted_nothing_a_card_could_grant(channel) -> None:
    """On text, nothing. On voice, the flow-control floor and only that: a
    call that cannot end is a worse failure than one that cannot act. The
    voice runtime used to union ALWAYS_ON back on its own -- two statements of
    the same rule -- and this grant said the opposite of what ran."""
    grant = ToolGrant.for_card(None, (), channel=channel)
    assert grant.is_cardless
    assert not grant.may_execute("create_promise_to_pay")
    assert not grant.may_execute("apply_goodwill")
    if channel == "voice":
        assert grant.allowed == VOICE_ALWAYS
        assert grant.may_execute("end_call")
    else:
        assert grant.allowed == frozenset()
        assert grant.offer() == ()
        assert not grant.may_execute("end_call")


def test_for_bundle_reads_the_card_off_a_deployment_bundle() -> None:
    """The runtime constructor. Taking a bundle rather than a card is what lets
    a handoff hand the receiving agent's bundle straight in."""
    grant = ToolGrant.for_bundle({"agentCard": card_dump(BOTS[0])}, channel=VOICE)
    assert not grant.is_cardless
    assert ToolGrant.for_bundle({}, channel=VOICE).is_cardless
    assert ToolGrant.for_bundle({"agentCard": {}}, channel=TEXT).is_cardless
    assert ToolGrant.for_bundle(None, channel=TEXT).is_cardless


# --- the always-on floor, pinned against its other two statements -----------


def test_the_voice_runtime_imports_the_grant_floor() -> None:
    """The live filter is the grant's object, proven without importing pipecat.

    An equality assertion behind ``importorskip("voice.tools")`` skipped in the
    API image and CI, so a restated frozenset could drift with nothing red.
    """
    tree = ast.parse((BACKEND / "voice" / "tools.py").read_text(encoding="utf-8"))
    aliases = [
        alias
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "agent_core.tools.grant"
        for alias in node.names
        if alias.name == "VOICE_ALWAYS" and (alias.asname or alias.name) == "ALWAYS_ON"
    ]
    assert aliases, (
        "voice.tools.ALWAYS_ON must be agent_core.tools.grant.VOICE_ALWAYS, imported"
    )


def test_always_on_is_not_assigned_in_voice_tools() -> None:
    """A local ``ALWAYS_ON = frozenset({...})`` is a second owner."""
    tree = ast.parse((BACKEND / "voice" / "tools.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "ALWAYS_ON"
            for target in node.targets
        ):
            pytest.fail(f"voice/tools.py:{node.lineno} assigns ALWAYS_ON; import it")
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "ALWAYS_ON"
        ):
            pytest.fail(f"voice/tools.py:{node.lineno} annotates ALWAYS_ON; import it")


def test_the_always_on_floor_is_the_same_object_where_pipecat_runs() -> None:
    """Identity, not equality — a second frozenset with the same members is a new owner."""
    voice_tools = pytest.importorskip("voice.tools")
    assert voice_tools.ALWAYS_ON is VOICE_ALWAYS


def test_the_authoring_catalog_omits_nothing_the_runtime_keeps() -> None:
    """``flow_graph._FLOW_CONTROL_TOOLS`` is the third statement, and it is the
    Studio's: it names the non-catalog verbs an author can put on a node. It may
    omit a catalog tool, because the catalog supplies that half — but never a
    verb the runtime keeps that the catalog does not, which would be a tool no
    author could see and no card could reach.
    """
    from flow_graph import _FLOW_CONTROL_TOOLS

    authoring = set(_FLOW_CONTROL_TOOLS)
    assert VOICE_FLOW_TOOLS <= authoring
    assert VOICE_ALWAYS - authoring <= CATALOG_NAMES


def test_the_flow_tools_are_outside_the_catalog_and_the_rest_are_in_it() -> None:
    """Why the floor is split in two: nine verbs have no ToolSpec because they
    have no arguments and no second channel, and two are ordinary catalog tools
    the runtime keeps anyway."""
    assert not VOICE_FLOW_TOOLS & CATALOG_NAMES
    assert VOICE_ALWAYS - VOICE_FLOW_TOOLS == {"capture_call_goal", "verify_identity"}
    assert {"capture_call_goal", "verify_identity"} <= CATALOG_NAMES


@pytest.mark.parametrize("bot_id", BOTS)
def test_the_floor_is_granted_on_voice_and_absent_on_text(bot_id, card_and_packs) -> None:
    card, packs = card_and_packs(bot_id)
    assert VOICE_ALWAYS <= ToolGrant.for_card(card, packs, channel=VOICE).allowed
    text = ToolGrant.for_card(card, packs, channel=TEXT).allowed
    # verify_identity is a real text tool on cards that include it; the nine
    # flow verbs and capture_call_goal are the voice-only half of the floor.
    assert not (VOICE_FLOW_TOOLS | {"capture_call_goal"}) & text


# --- the publish gate's scope is not a second grant --------------------------


@pytest.mark.parametrize("bot_id", BOTS)
def test_the_publish_scope_is_the_authors_declaration_not_the_grant(bot_id, card_and_packs) -> None:
    """G9 checks a pack's tools against ``include | locked | platform`` -- what
    the author declared -- and never against the catalog. That is a scope for
    reporting authoring errors, not a grant, and the two differ in exactly two
    documented ways:

    * the scope permits names no runtime could call (locked engines with no
      mouth tool, skill-gated tools no attached pack grants);
    * the scope omits the always-on floor, which the grant carries.

    Anything else the scope permits and the grant does not must be a catalog
    tool no attached pack grants -- never a name a runtime would have granted.
    """
    card, packs = card_and_packs(bot_id)
    scope = set(card.tools.include) | set(card.tools.locked) | PLATFORM_SKILL_TOOLS
    static = ToolGrant.static_grant(card, packs)

    assert static - scope == (VOICE_ALWAYS | TEXT_ALWAYS) - scope

    unreachable = scope - static
    locked_without_a_mouth_tool = {"evaluate_live_qa", "recommend_treatment"}
    assert locked_without_a_mouth_tool <= unreachable
    for name in unreachable - locked_without_a_mouth_tool:
        assert name in CATALOG_NAMES
        assert not any(name in p.allowed_tools for p in packs)


