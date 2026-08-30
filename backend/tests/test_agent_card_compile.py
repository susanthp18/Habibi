"""Agent Card compiler — G0–G15. Empty card is legacy; invalid card cannot publish."""

from __future__ import annotations

from agent_core.cards.compile import compile_card
from agent_core.cards.defaults import (
    COLLECTIONS_BOT_ID,
    INTAKE_BOT_ID,
    INSURANCE_BOT_ID,
    card_dump,
    card_for,
)
from agent_core.tools.catalog import CATALOG


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


def test_unbinding_reco_fails_g3() -> None:
    card = card_for(COLLECTIONS_BOT_ID)
    dumped = card.model_dump()
    dumped["policy_bindings"]["reco"] = "off"
    report = _compile(COLLECTIONS_BOT_ID, card=dumped)
    g0 = next(g for g in report.gates if g.gate == "G0")
    assert g0.status == "fail"


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
