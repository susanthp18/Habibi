"""The palette, the compiler and the runtime agree on what a card can call.

Four findings, one shape: the Studio offered tools from one set, the compiler
certified against a second, and the runtime executed a third.

* **FLOW-1.** ``GET /flow/built-in`` returned 500 in production. The export
  reaches ``voice/tools.py``'s module-level pipecat import, and the ``api``
  service builds from ``target: base``, which installs ``requirements.txt``
  only. So the Flow tab's "load the built-in script" — the one way to turn the
  live Python into a graph an author owns — never worked outside the voice
  container.

* **TOOLS-1.** Nine zero-argument flow-control verbs arrive from
  ``/flow/tools`` and are on the runtime floor. The Tools tab labelled them
  "unsupported" and offered Add, which writes a name G4 then fails on — after
  the tab has shown G6 green and no error.

* **FLOW-3.** No gate compared a node's tools with the card's Tool Grant.
  ``/flow/validate`` and G1 both check against the whole voice catalog, so a
  node naming a tool the card cannot grant compiled green and lost it at
  ``flows_dynamic``'s ``logger.warning``.

  It was not hypothetical. On the day this was written the live built-in script
  called exactly one such tool: ``handle_dispute`` offers ``apply_goodwill``,
  which is skill-gated and was on no attached pack. The step could size a
  goodwill waiver with ``evaluate_authority`` and had no way to post it.

* **CATALOG-2.** ``identify_customer`` is one of the catalog's two TEXT_ONLY
  specs, is named in every WhatsApp system prompt, and was on no card, in no
  pack, and behind no text floor — so ``execute_tool`` refused it as
  ``tool_not_on_card_or_skill`` every time the prompt asked for it.
"""

from __future__ import annotations

import inspect

import pytest

import flow_graph as fg
from agent_core.cards.compile import compile_card, node_offers
from agent_core.cards.defaults import COLLECTIONS_BOT_ID, card_dump, card_for
from agent_core.skills.intersect import effective_tools
from agent_core.skills.pack import pack_for_slug
from agent_core.skills.runtime import resolve_mouth
from agent_core.tools.catalog import CATALOG
from agent_core.tools.grant import TEXT_ALWAYS, VOICE_ALWAYS, ToolGrant
from agent_core.tools.schema import CHANNEL_TEXT, CHANNEL_VOICE

CATALOG_NAMES = set(CATALOG.specs)
KNOWN_BOTS = {COLLECTIONS_BOT_ID, "intake-v1", "insurance-v1", "supervisor-brief"}


def _packs(bot_id: str = COLLECTIONS_BOT_ID):
    """Packs read from the repo, not the database.

    The pack files are the source of truth and boot-sync copies them in; reading
    them here keeps the assertion about the change rather than about whether the
    container has restarted since.
    """
    card = card_for(bot_id)
    return [p for p in (pack_for_slug(s.skill_id) for s in (card.skills or [])) if p]


def _built_in():
    from voice.flow_export import built_in_collections_graph

    return built_in_collections_graph()


def _compile(bot_id: str = COLLECTIONS_BOT_ID, *, flow=None, **kwargs):
    return compile_card(
        bot_id=bot_id,
        card_raw=card_dump(bot_id),
        flow=_built_in() if flow is None else flow,
        catalog_names=CATALOG_NAMES,
        known_bot_ids=KNOWN_BOTS,
        attached_skills=_packs(bot_id),
        skip_eval_gates=True,
        **kwargs,
    )


def _gate(report, name: str):
    return next((g for g in report.gates if g.gate == name), None)


# ---------------------------------------------------------------------------
# FLOW-1 — the export does not need pipecat to be read
# ---------------------------------------------------------------------------


def test_the_export_reaches_the_api_image() -> None:
    """The whole chain, not just the leaf. ``voice.tools`` is the trunk."""
    import voice.flow_export  # noqa: F401
    import voice.flows  # noqa: F401
    import voice.tools

    # Module level only, and statements rather than prose: the comment above
    # the replaced line names the old import, and two handlers still reach for
    # pipecat frames lazily — inside code that cannot run without a call.
    lines = inspect.getsource(voice.tools).splitlines()
    assert not [ln for ln in lines if ln.startswith(("from pipecat", "import pipecat"))]
    assert (
        "from agent_core.tools.pipecat_compat import NO_RESPONSE, flows_tool_options" in lines
    )


def test_building_the_graph_does_not_need_pipecat_either() -> None:
    """Importing was half of it: deriving the graph calls every node factory,
    and a node factory renders its tools through ``to_flows_schema``."""
    from agent_core.tools.schema import ToolSpec

    src = inspect.getsource(ToolSpec.to_flows_schema)
    assert "from pipecat.flows import FlowsFunctionSchema" not in src
    assert "flows_function_schema(**kwargs)" in src


def test_the_stub_carries_what_the_export_reads() -> None:
    """``_tool_names`` matches the registry by identity and reads ``.name``."""
    from agent_core.tools.pipecat_compat import FlowsSchemaStub

    stub = FlowsSchemaStub(name="verify_identity", description="d", handler=object())
    assert stub.name == "verify_identity"
    assert FlowsSchemaStub(name="a") is not FlowsSchemaStub(name="a")


def test_the_sentinel_is_not_none_and_not_falsy() -> None:
    """The next-node slot distinguishes "stay here and say nothing" from "no
    transition requested". A falsy stand-in would collapse the two."""
    from agent_core.tools import pipecat_compat

    assert pipecat_compat.NO_RESPONSE is not None
    assert bool(pipecat_compat.NO_RESPONSE) is True


def test_the_built_in_graph_still_exports() -> None:
    graph = _built_in()
    keys = {n["key"] for n in graph["nodes"]}
    assert {"greet_disclose", "handle_dispute", "call_ended"} <= keys


# ---------------------------------------------------------------------------
# TOOLS-1 — the palette says what the runtime does
# ---------------------------------------------------------------------------


def test_flow_control_verbs_are_marked_always_on() -> None:
    rows = {r["key"]: r for r in fg.tool_catalog()}
    for key in ("disclose_recording", "begin_negotiate", "end_call", "return_to_position"):
        assert rows[key]["alwaysOn"] is True, key
        assert rows[key]["kind"] == "flow_control", key


def test_an_always_on_row_is_exactly_the_runtime_floor() -> None:
    """Two statements of the floor would drift. This one is derived."""
    rows = fg.tool_catalog()
    marked = {r["key"] for r in rows if r["alwaysOn"]}
    assert marked == (VOICE_ALWAYS | TEXT_ALWAYS) & {r["key"] for r in rows}


def test_a_grantable_tool_is_not_marked_always_on() -> None:
    rows = {r["key"]: r for r in fg.tool_catalog()}
    for key in ("create_promise_to_pay", "apply_goodwill", "search_knowledge_base"):
        assert rows[key]["alwaysOn"] is False, key


def test_adding_a_flow_control_verb_is_the_g4_failure_the_tab_hid() -> None:
    """Why the tab must not offer Add on those rows: G4 computes
    ``include − catalog`` and these nine are deliberately not catalog specs."""
    raw = card_dump(COLLECTIONS_BOT_ID)
    raw["tools"] = {**raw.get("tools", {}), "include": [*raw["tools"]["include"], "begin_dispute"]}
    report = compile_card(
        bot_id=COLLECTIONS_BOT_ID,
        card_raw=raw,
        flow=_built_in(),
        catalog_names=CATALOG_NAMES,
        known_bot_ids=KNOWN_BOTS,
        attached_skills=_packs(),
        skip_eval_gates=True,
    )
    g4 = _gate(report, "G4")
    assert g4.status == "fail"
    assert "begin_dispute" in str(g4.issues)


# ---------------------------------------------------------------------------
# CATALOG-2 — the text channel has a floor
# ---------------------------------------------------------------------------


def test_the_palette_is_no_longer_filtered_to_voice() -> None:
    rows = {r["key"]: r for r in fg.tool_catalog()}
    assert "identify_customer" in rows
    assert rows["identify_customer"]["channels"] == ["text"]
    assert "voice" in rows["verify_identity"]["channels"]


def test_identify_customer_is_granted_and_offered_on_text() -> None:
    """Both halves. A name the runtime would execute but never offers is a name
    the model cannot reach — which is what the WhatsApp prompt kept asking for."""
    mouth = resolve_mouth(card_dump(COLLECTIONS_BOT_ID))
    text_channel = {s.name for s in CATALOG.for_channel(CHANNEL_TEXT)}
    state = mouth.tools(channel_tools=text_channel, floor=TEXT_ALWAYS)
    assert "identify_customer" in state.allowed
    assert "identify_customer" in state.offered


def test_the_text_floor_does_not_reach_voice() -> None:
    mouth = resolve_mouth(card_dump(COLLECTIONS_BOT_ID))
    voice_channel = {s.name for s in CATALOG.for_channel(CHANNEL_VOICE)}
    state = mouth.tools(channel_tools=voice_channel, floor=TEXT_ALWAYS)
    assert "identify_customer" not in state.allowed


def test_a_floor_cannot_smuggle_a_tool_onto_the_wrong_channel() -> None:
    """The floor is intersected with what the channel renders first, so a
    mis-stated one degrades to nothing rather than to a missing handler."""
    mouth = resolve_mouth(card_dump(COLLECTIONS_BOT_ID))
    text_channel = {s.name for s in CATALOG.for_channel(CHANNEL_TEXT)}
    state = mouth.tools(
        channel_tools=text_channel, floor=frozenset({"disclose_recording", "not_a_tool"})
    )
    assert "disclose_recording" not in state.allowed
    assert "not_a_tool" not in state.allowed


def test_the_tool_grant_applies_the_same_floor() -> None:
    card = card_for(COLLECTIONS_BOT_ID)
    packs = _packs()
    text = ToolGrant.for_card(card, packs, channel="text")
    voice = ToolGrant.for_card(card, packs, channel="voice")
    assert text.may_execute("identify_customer")
    assert "identify_customer" in text.offer()
    assert not voice.may_execute("identify_customer")


def test_the_document_tool_has_a_card_that_can_call_it() -> None:
    """A grant, not a floor — uploading a borrower's document is a deliberate
    capability. It just needed a card that holds it."""
    card = card_for(COLLECTIONS_BOT_ID)
    assert "ingest_customer_document" in card.tools.include
    text = ToolGrant.for_card(card, _packs(), channel="text")
    assert text.may_execute("ingest_customer_document")


def test_a_text_only_tool_is_not_charged_to_the_voice_latency_cap() -> None:
    """G6 caps what a *call* carries. Counting a TEXT_ONLY spec against
    ``max_voice_tools`` charges a card for weight it never spends — and no
    compile_card caller passes ``channel_tools``, deliberately, because a
    publish gate reasons about every channel at once."""
    report = _compile()
    assert _gate(report, "G6").status == "pass"
    assert "ingest_customer_document" in report.idle_tools
    assert report.idle_voice_tools <= report.voice_tool_cap


# ---------------------------------------------------------------------------
# FLOW-3 — G16, and the tool the live script could not call
# ---------------------------------------------------------------------------


def test_g16_passes_on_every_first_party_card() -> None:
    for bot_id in sorted(KNOWN_BOTS):
        flow = _built_in() if bot_id == COLLECTIONS_BOT_ID else {}
        report = _compile(bot_id, flow=flow)
        g16 = _gate(report, "G16")
        assert g16 is not None, bot_id
        assert g16.status in {"pass", "skipped"}, (bot_id, g16.status, g16.detail)


def test_handle_dispute_can_post_the_waiver_it_sizes() -> None:
    """The finding this gate was written for. ``evaluate_authority`` decides
    whether a late-fee waiver is in policy; ``apply_goodwill`` posts it. The
    node has offered both since it was written, and the grant dropped one."""
    card = card_for(COLLECTIONS_BOT_ID)
    grant = set(effective_tools(card, catalog_names=CATALOG_NAMES, attached_skills=_packs()))
    assert {"evaluate_authority", "apply_goodwill"} <= grant

    rows = {r["key"]: r for r in node_offers(_built_in(), grant)}
    assert rows["handle_dispute"]["dropped"] == []
    assert "apply_goodwill" in rows["handle_dispute"]["offered"]


def test_the_grant_comes_from_the_pack_that_runs_that_step() -> None:
    """Not from widening the card. ``apply_goodwill`` is skill-gated, and
    ``dispute-capture`` is the pack ``handle_dispute`` runs under."""
    pack = pack_for_slug("dispute-capture")
    assert "apply_goodwill" in pack.allowed_tools
    assert "evaluate_authority" in pack.allowed_tools
    other = pack_for_slug("upsell-pitch")
    assert "apply_goodwill" not in other.allowed_tools


def test_g16_warns_and_names_the_node_when_a_pack_is_detached() -> None:
    packs = [p for p in _packs() if p.slug != "dispute-capture"]
    report = compile_card(
        bot_id=COLLECTIONS_BOT_ID,
        card_raw=card_dump(COLLECTIONS_BOT_ID),
        flow=_built_in(),
        catalog_names=CATALOG_NAMES,
        known_bot_ids=KNOWN_BOTS,
        attached_skills=packs,
        skip_eval_gates=True,
    )
    g16 = _gate(report, "G16")
    assert g16.status == "warn"
    assert "apply_goodwill" in g16.detail
    assert any(i["node"] == "handle_dispute" for i in g16.issues)


def test_g16_warns_rather_than_blocks() -> None:
    """Deliberate, and recorded: a blocking gate that fires on the shipping
    card is a gate nobody can adopt. Promotion is a later chunk's move."""
    from agent_core.cards.compile import _flow_grant_gate

    src = inspect.getsource(_flow_grant_gate)
    assert '"warn"' in src
    assert '"fail"' not in src


def test_the_runtime_floor_is_never_reported_as_dropped() -> None:
    """The nine flow-control verbs are not catalog specs at all, and
    ``capture_call_goal``/``verify_identity`` are kept whatever the card says."""
    rows = node_offers(_built_in(), set())
    dropped = {n for r in rows for n in r["dropped"]}
    assert not (dropped & VOICE_ALWAYS)


def test_an_unauthored_flow_is_skipped_not_passed() -> None:
    report = _compile(flow={})
    assert _gate(report, "G16").status == "skipped"


def test_node_offers_covers_the_graph_level_list_too() -> None:
    rows = {r["key"]: r for r in node_offers(_built_in(), set())}
    assert "globalTools" in rows
    assert "search_knowledge_base" in rows["globalTools"]["dropped"]


def test_the_gate_and_the_bundle_read_one_helper() -> None:
    """A certificate and an artefact that computed this separately would drift."""
    from agent_core.fleet import compile as fleet_compile

    src = inspect.getsource(fleet_compile.compile_bundle)
    assert "node_offers(" in src


def test_the_bundle_records_every_step_and_still_hashes() -> None:
    from agent_core.fleet.compile import bundle_hash_valid, compile_bundle

    graph = _built_in()
    report = _compile()
    bundle = compile_bundle(
        report=report, prompt="p", flow=graph, attached_skills=_packs(), prompt_version_id="pv-1"
    )
    assert bundle_hash_valid(bundle)
    assert {o.key for o in bundle.node_offers} == {"globalTools"} | {
        n["key"] for n in graph["nodes"]
    }
    again = compile_bundle(
        report=report, prompt="p", flow=graph, attached_skills=_packs(), prompt_version_id="pv-1"
    )
    assert bundle.bundle_hash == again.bundle_hash


def test_a_bundle_for_a_cardless_version_carries_no_offers() -> None:
    from agent_core.cards.compile import CompileReport
    from agent_core.fleet.compile import compile_bundle

    empty = CompileReport(bot_id=COLLECTIONS_BOT_ID, gates=[], card={})
    assert compile_bundle(report=empty, flow={}).node_offers == []


@pytest.mark.parametrize("flow", [None, {}, {"nodes": "not a list"}, 7])
def test_node_offers_never_raises_on_a_graph_it_cannot_read(flow) -> None:
    assert node_offers(flow, {"verify_identity"}) == []


# ---------------------------------------------------------------------------
# G-F11 — the script is walkable on the channel the card claims
# ---------------------------------------------------------------------------


def test_gf11_is_skipped_for_a_card_with_no_text_mouth() -> None:
    """A voice-only card is not lying by shipping a voice-only script."""
    card = card_dump(COLLECTIONS_BOT_ID)
    card["identity"]["channels"] = ["voice"]
    report = compile_card(
        bot_id=COLLECTIONS_BOT_ID,
        card_raw=card,
        flow=_built_in(),
        catalog_names=CATALOG_NAMES,
        known_bot_ids=KNOWN_BOTS,
        attached_skills=_packs(),
        skip_eval_gates=True,
    )
    assert _gate(report, "G-F11").status == "skipped"


def test_gf11_no_longer_blames_the_greeting() -> None:
    """The finding the gate was written for, resolved where it lives.

    ``greet_disclose`` leaves only via ``disclose_recording`` — a voice verb,
    on a channel with no recording to disclose. The text mouth now passes
    straight through such a step to the one place its contract leads
    (``flow_walk.FlowWalker.pass_through``), and the gate applies the same
    rule, so the greeting is never the stuck step. What the gate still
    reports on the built-in export is a step with genuinely no text exit --
    none here, because every terminal in the export ends the conversation.
    """
    report = _compile(COLLECTIONS_BOT_ID)
    gf11 = _gate(report, "G-F11")
    assert "greet_disclose" not in {i["node"] for i in (gf11.issues or [])}
    assert gf11.status in {"pass", "warn"}


def test_gf11_passes_a_graph_whose_steps_have_authored_exits() -> None:
    """An authored edge is a text exit: the model calls ``go_to_*`` and moves."""
    graph = {
        "version": 1,
        "globalTools": [],
        "nodes": [
            {"id": "a", "key": "a", "data": {"name": "A", "isStart": True}},
            {"id": "b", "key": "b", "type": "end", "data": {"name": "B"}},
        ],
        "edges": [
            {
                "id": "e",
                "source": "a",
                "target": "b",
                "data": {"condition": {"type": "prompt", "prompt": "they are done"}},
            }
        ],
    }
    assert _gate(_compile(COLLECTIONS_BOT_ID, flow=graph), "G-F11").status == "pass"


def test_gf11_is_skipped_rather_than_guessing_at_an_unreadable_flow() -> None:
    assert _gate(_compile(COLLECTIONS_BOT_ID, flow={"nodes": "not a list"}), "G-F11").status == (
        "skipped"
    )
