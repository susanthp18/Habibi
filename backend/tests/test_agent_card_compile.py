"""Agent Card compiler — G0–G15. Empty card is legacy; invalid card cannot publish."""

from __future__ import annotations

import pytest

from agent_core.cards.compile import compile_card
from agent_core.cards.defaults import (
    COLLECTIONS_BOT_ID,
    INTAKE_BOT_ID,
    INSURANCE_BOT_ID,
    card_dump,
    card_for,
)
from agent_core.tools.catalog import CATALOG


@pytest.fixture(autouse=True)
def _eval_gates_off(monkeypatch):
    """These tests compile cards with no eval report in hand; they are about
    the compiler's structure, not eval provenance (tests/test_eval_provenance.py
    covers that). The dev stack now ships with the gates on."""
    monkeypatch.setenv("EVAL_GATE_ENABLED", "false")
    monkeypatch.setenv("REDTEAM_GATE_ENABLED", "false")


def _compile(bot_id: str, card=None, flow=None, bots=None, **kwargs):
    raw = card if card is not None else card_dump(bot_id)
    if flow is None:
        if bot_id == COLLECTIONS_BOT_ID:
            from voice.flow_export import built_in_collections_graph

            flow = built_in_collections_graph()
        else:
            flow = {}
    return compile_card(
        bot_id=bot_id,
        card_raw=raw,
        flow=flow,
        catalog_names=set(CATALOG.specs),
        known_bot_ids=bots or {COLLECTIONS_BOT_ID, INTAKE_BOT_ID, INSURANCE_BOT_ID, "supervisor-brief"},
        **kwargs,
    )


def test_four_first_party_cards_compile_clean() -> None:
    for bot_id in (INTAKE_BOT_ID, COLLECTIONS_BOT_ID, INSURANCE_BOT_ID, "supervisor-brief"):
        report = _compile(bot_id)
        blocking = [g.gate for g in report.blocking]
        assert blocking == [], f"{bot_id} blocked on {blocking}: {report.model_dump()}"


def test_empty_card_is_legacy_not_fake_green() -> None:
    report = compile_card(
        bot_id=COLLECTIONS_BOT_ID,
        card_raw={},
        flow={},
        catalog_names=set(CATALOG.specs),
        known_bot_ids={COLLECTIONS_BOT_ID},
    )
    g0 = next(g for g in report.gates if g.gate == "G0")
    assert g0.status == "skipped"
    assert report.ok


def test_unlocking_a_policy_engine_fails_g3() -> None:
    """G3 is the locked-tools check. `policy_bindings` is retired: a field
    that could only hold "required" bound nothing, and the test that claimed
    to cover its half asserted G0."""
    card = card_for(COLLECTIONS_BOT_ID)
    dumped = card.model_dump()
    dumped["tools"]["locked"] = [t for t in dumped["tools"]["locked"] if t != "recommend_next_offer"]
    report = _compile(COLLECTIONS_BOT_ID, card=dumped)
    g3 = next(g for g in report.gates if g.gate == "G3")
    assert g3.status == "fail"
    assert g3.issues[0]["missing_locked"] == ["recommend_next_offer"]


def test_a_stored_policy_binding_is_dropped_not_refused() -> None:
    from agent_core.cards.schema import parse_card

    raw = card_for(COLLECTIONS_BOT_ID).model_dump()
    raw["policy_bindings"] = {"reco": "off"}
    raw["eval"]["suite_id"] = "eval-regression-collections"
    raw["identity"]["owner_user_id"] = "priya-nair"
    parsed = parse_card(raw)
    assert not hasattr(parsed, "policy_bindings")
    assert not hasattr(parsed.eval, "suite_id")


def test_unknown_tool_fails_g4() -> None:
    card = card_for(COLLECTIONS_BOT_ID)
    dumped = card.model_dump()
    dumped["tools"]["include"] = [*dumped["tools"]["include"], "apply_magic_waiver"]
    report = _compile(COLLECTIONS_BOT_ID, card=dumped)
    g4 = next(g for g in report.gates if g.gate == "G4")
    assert g4.status == "fail"


def test_handoff_to_missing_bot_fails_g5() -> None:
    card = card_for(COLLECTIONS_BOT_ID)
    dumped = card.model_dump()
    dumped["handoffs"] = [{"to_bot_id": "legal-v1", "payload_schema": {}, "when": "legal"}]
    report = _compile(COLLECTIONS_BOT_ID, card=dumped)
    g5 = next(g for g in report.gates if g.gate == "G5")
    assert g5.status == "fail"


def test_eval_gates_are_skipped_not_green_when_flags_off(monkeypatch) -> None:
    monkeypatch.delenv("EVAL_GATE_ENABLED", raising=False)
    monkeypatch.delenv("REDTEAM_GATE_ENABLED", raising=False)
    report = _compile(COLLECTIONS_BOT_ID)
    g7 = next(g for g in report.gates if g.gate == "G7")
    g8 = next(g for g in report.gates if g.gate == "G8")
    assert g7.status == "skipped"
    assert g8.status == "skipped"


def test_eval_gate_fails_closed_when_flag_on_and_no_report(monkeypatch) -> None:
    monkeypatch.setenv("EVAL_GATE_ENABLED", "true")
    report = _compile(COLLECTIONS_BOT_ID)
    g7 = next(g for g in report.gates if g.gate == "G7")
    assert g7.status == "fail"
    assert not report.ok


def test_g12_fails_closed_on_shadow() -> None:
    report = _compile(COLLECTIONS_BOT_ID, shadow=True, traffic_pct=100)
    g12 = next(g for g in report.gates if g.gate == "G12")
    assert g12.status == "fail"
    assert not report.ok


def test_g_lint_fails_on_prohibited_words() -> None:
    report = _compile(
        COLLECTIONS_BOT_ID,
        prompt="We will threaten the borrower.",
        prompt_guardrails={"prohibited": ["threaten"]},
    )
    glint = next(g for g in report.gates if g.gate == "G-LINT")
    assert glint.status == "fail"
    assert not report.ok


def test_g12_and_g14_are_honest_on_first_party_cards() -> None:
    report = _compile(COLLECTIONS_BOT_ID)
    g12 = next(g for g in report.gates if g.gate == "G12")
    g13 = next(g for g in report.gates if g.gate == "G13")
    g14 = next(g for g in report.gates if g.gate == "G14")
    assert g12.status == "pass"
    assert g13.status == "skipped"
    assert g14.status == "skipped"
    assert report.ok


# --- G15 voice_locale -------------------------------------------------------
#
# The gate that exists because a draft on the live demo card carried
# ``fish:7e4fa512aa564e198f8659b466f6ff70`` — AboFlah, an Arabic Fish voice — on
# a card whose persona is English / en-IN, and cleared G0-G14 with Publish
# enabled. Warning severity on purpose: a localisation override is a real thing
# an operator does, so refusing it would be wrong more often than right. What
# the compiler must not do is stay silent.


def _g15(**kwargs):
    report = _compile(COLLECTIONS_BOT_ID, **kwargs)
    return next(g for g in report.gates if g.gate == "G15")


def test_an_arabic_voice_on_an_english_card_warns() -> None:
    gate = _g15(
        voice_short_name="fish:7e4fa512aa564e198f8659b466f6ff70",
        voice_locale="ar",
        card_locales=["en-IN", "hi-IN"],
    )
    assert gate.status == "warn"
    assert "ar" in gate.detail and "en-IN" in gate.detail
    assert gate.issues == [
        {
            "voice": "fish:7e4fa512aa564e198f8659b466f6ff70",
            "voiceLocale": "ar",
            "cardLocales": ["en-IN", "hi-IN"],
        }
    ]


def test_a_matching_voice_passes() -> None:
    gate = _g15(
        voice_short_name="en-IN-AartiNeural",
        voice_locale="en-IN",
        card_locales=["en-IN", "hi-IN"],
    )
    assert gate.status == "pass"


def test_a_warning_does_not_block_the_publish() -> None:
    """The whole severity decision, asserted rather than described."""
    report = _compile(
        COLLECTIONS_BOT_ID,
        voice_short_name="fish:7e4fa512aa564e198f8659b466f6ff70",
        voice_locale="ar",
        card_locales=["en-IN"],
    )
    assert next(g for g in report.gates if g.gate == "G15").status == "warn"
    assert report.ok, [g.gate for g in report.blocking]


def test_a_bare_language_code_matches_a_regional_tag() -> None:
    """Only Azure publishes en-IN; every other provider syncs a bare ``en``.

    Comparing whole tags would warn on every Cartesia and Fish English voice a
    card legitimately uses, and a warning that fires on the correct case is one
    an operator learns to click past.
    """
    assert _g15(voice_short_name="cartesia:x", voice_locale="en", card_locales=["en-IN"]).status == "pass"
    assert _g15(voice_short_name="azure:x", voice_locale="hi-IN", card_locales=["hi-IN"]).status == "pass"


def test_a_fallback_language_is_part_of_the_card_set() -> None:
    """A Hindi voice on an English card with a Hindi fallback is authored, not
    accidental — the vernacular fallback is why the field exists."""
    assert _g15(
        voice_short_name="hi-IN-SwaraNeural", voice_locale="hi-IN", card_locales=["en-IN", "hi-IN"]
    ).status == "pass"


def test_an_unresolvable_voice_skips_rather_than_guessing() -> None:
    """What the runtime speaks then is the fallback voice, whose locale is not
    the stored id's. get_tts_voice_warning already reports that id; this gate
    inventing a second opinion about it would be the wrong answer twice."""
    assert _g15(voice_short_name="ravi", voice_locale=None, card_locales=["en-IN"]).status == "skipped"


def test_no_voice_and_no_language_skip() -> None:
    assert _g15().status == "skipped"
    assert _g15(voice_short_name="en-IN-AartiNeural", voice_locale="en-IN").status == "skipped"


# --- G17: the voice's vendor against what the bot can speak through ----------
# G15's sibling, and deliberately not part of it: a wrong language is a warning
# an operator may legitimately override, an unspeakable voice is a dropped call.


def _g17(**kwargs):
    report = _compile(COLLECTIONS_BOT_ID, **kwargs)
    return next(g for g in report.gates if g.gate == "G17")


def test_a_fish_voice_with_only_azure_bound_fails() -> None:
    """The live shape of the bug: `agent_provider_bindings` holds one Azure TTS
    row, while the catalog offers 2288 voices across four vendors. Nothing else
    catches this — `build_with_failover` only retries on construction errors,
    and every service accepts a voice name as a string at construction, so it
    fails at synthesis on the first utterance after the customer was dialled.
    """
    gate = _g17(
        voice_short_name="fish:7e4fa512aa564e198f8659b466f6ff70",
        voice_locale="ar",
        voice_provider="fish",
        bound_tts_providers={"azure"},
    )
    assert gate.status == "fail"
    assert gate.issues == [
        {
            "voice": "fish:7e4fa512aa564e198f8659b466f6ff70",
            "voiceProvider": "fish",
            "boundProviders": ["azure"],
        }
    ]


def test_an_azure_voice_with_azure_bound_passes() -> None:
    """Every one of the five published cards is this case, which is why the
    gate ships blocking rather than warn-first."""
    assert (
        _g17(
            voice_short_name="en-IN-AartiNeural",
            voice_locale="en-IN",
            voice_provider="azure",
            bound_tts_providers={"azure"},
        ).status
        == "pass"
    )


def test_g17_blocks_the_publish_where_g15_only_warns() -> None:
    """The severity difference between the two voice gates, asserted."""
    report = _compile(
        COLLECTIONS_BOT_ID,
        voice_short_name="fish:abc",
        voice_locale="ar",
        card_locales=["en-IN"],
        voice_provider="fish",
        bound_tts_providers={"azure"},
    )
    assert next(g for g in report.gates if g.gate == "G15").status == "warn"
    assert next(g for g in report.gates if g.gate == "G17").status == "fail"
    assert not report.ok
    assert "G17" in [g.gate for g in report.blocking]


def test_g17_skips_rather_than_guessing() -> None:
    """Three unknowns, none of which this gate has an honest opinion about."""
    assert _g17().status == "skipped"
    # Catalog cannot resolve the id — get_tts_voice_warning owns that story.
    assert _g17(voice_short_name="ravi", voice_provider=None).status == "skipped"
    # Caller could not read the bindings (unmigrated database).
    assert (
        _g17(voice_short_name="en-IN-AartiNeural", voice_provider="azure").status == "skipped"
    )
    # Nothing bound at all is NoBindingError's story, and bot.py still has an
    # Azure fallback lambda.
    assert (
        _g17(
            voice_short_name="en-IN-AartiNeural",
            voice_provider="azure",
            bound_tts_providers=set(),
        ).status
        == "skipped"
    )


def test_capability_is_no_longer_a_publish_requirement() -> None:
    """It was offered as one and read by nothing.

    `_eval_gate` matches a requirement against a *gate name*, and no gate is
    called `capability` — so ticking it changed no publish outcome. No stored
    card carried it, so it is deleted outright rather than tolerated on read:
    an invented value must still fail loudly.
    """
    import pydantic
    import pytest

    from agent_core.cards.schema import AgentCard

    raw = card_dump(COLLECTIONS_BOT_ID)
    raw["eval"] = {**(raw.get("eval") or {}), "require": ["capability"]}
    with pytest.raises(pydantic.ValidationError):
        AgentCard.model_validate(raw)


def test_the_twin_gate_says_where_to_run_it() -> None:
    """G11 reads `twin_runs`; the Evals tab's suites write `eval_reports`. An
    operator who ticks Twin and runs everything in front of them never moves
    this gate, so the failure has to name the screen that does."""
    from agent_core.cards.compile import _eval_gate

    gate = _eval_gate(
        "G11", "twin", True, None, None, where=" — run it from the Sandbox inspector's Twin tab"
    )
    assert gate.status == "fail"
    assert "Sandbox" in gate.detail and "Twin tab" in gate.detail


def _g18(card):
    report = _compile(COLLECTIONS_BOT_ID, card=card)
    return next(g for g in report.gates if g.gate == "G18")


def test_a_binding_no_skill_can_offer_warns() -> None:
    """G10 says a binding is allowed; G18 says whether anything can call it.

    `ext.*` names reach the Grant and are stripped from the idle offer, so they
    return only for tools an active skill pack names. Bind alone therefore
    changes nothing a model can do — and the live `kaia-v2-4` card is exactly
    this shape: it binds `paylink`, and no skill version in the tenant names an
    `ext.paylink.*` tool.
    """
    raw = card_dump(COLLECTIONS_BOT_ID)
    raw["connectors"] = [{"connector_id": "paylink", "allow_prefixes": ["ext.paylink."]}]
    gate = _g18(raw)
    assert gate.status == "warn"
    assert "paylink" in gate.detail
    assert gate.issues == [{"connector": "paylink", "prefixes": ["ext.paylink."]}]


def test_a_binding_with_no_prefixes_is_skipped_not_accused() -> None:
    """Nothing to match its tools against, so silence beats a wrong accusation
    on an authoring surface."""
    raw = card_dump(COLLECTIONS_BOT_ID)
    raw["connectors"] = [{"connector_id": "paylink", "allow_prefixes": []}]
    assert _g18(raw).status == "pass"


def test_g18_warns_and_does_not_block() -> None:
    """Warn-first, because it fires on the shipping card: a gate that refuses
    what is already live is one people switch off instead of adopting."""
    raw = card_dump(COLLECTIONS_BOT_ID)
    raw["connectors"] = [{"connector_id": "paylink", "allow_prefixes": ["ext.paylink."]}]
    report = _compile(COLLECTIONS_BOT_ID, card=raw)
    assert next(g for g in report.gates if g.gate == "G18").status == "warn"
    assert report.ok, [g.gate for g in report.blocking]
