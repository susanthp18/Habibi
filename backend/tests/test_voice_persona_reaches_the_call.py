"""The Persona tab must change a phone call.

``build_voice_system_prompt`` took ``(rendered_prompt, guardrails)``. That
signature is the whole bug: the persona had no way in. Language, fallback
languages and all five trait sliders reached the text channels through
``build_system_prompt`` and stopped dead at the voice loop — the primary channel
— so five controls in the Studio moved a WhatsApp reply and nothing else.

Traits arrive as directions rather than the ``empathy=75`` numbers that were
dropped earlier, deliberately: the objection to the numbers was that an LLM does
not act on a 0-100 scale reliably, which is an argument about the encoding, not
about whether the tab should mean anything.
"""

from __future__ import annotations

from voice.bot import _system_instruction_from_bundle
from voice.natural import build_voice_system_prompt, persona_style_line


def _bundle(**persona: object) -> dict:
    base = {
        "traits": {"empathy": 50, "firmness": 50, "formality": 50, "verbosity": 50, "upsell": 50},
        "language": "English",
        "fallbackLanguages": [],
    }
    base.update(persona)
    return {
        "prompt": "You are {agent_name} for {bank_name}. Speak in {language}.",
        "persona": base,
        "guardrails": {},
    }


def test_the_language_token_follows_the_card_not_the_default() -> None:
    """The single line that made every call English regardless of the card."""
    out = _system_instruction_from_bundle(_bundle(language="Hindi"))
    assert "Speak in Hindi." in out
    assert "Speak in English." not in out


def test_the_persona_language_is_stated_to_the_model() -> None:
    out = build_voice_system_prompt("", {}, persona={"language": "Tamil"})
    assert "Speak Tamil" in out


def test_fallback_languages_are_offered_not_hidden() -> None:
    out = build_voice_system_prompt(
        "", {}, persona={"language": "Hindi", "fallbackLanguages": ["English", "Tamil"]}
    )
    assert "English, Tamil" in out


def test_the_primary_language_is_not_repeated_as_its_own_fallback() -> None:
    out = build_voice_system_prompt(
        "", {}, persona={"language": "Hindi", "fallbackLanguages": ["Hindi", "English"]}
    )
    assert "fluent in English." in out


def test_a_high_trait_becomes_an_instruction() -> None:
    line = persona_style_line({"traits": {"empathy": 90}})
    assert "acknowledge" in line


def test_a_low_trait_becomes_the_opposite_instruction() -> None:
    high = persona_style_line({"traits": {"firmness": 90}})
    low = persona_style_line({"traits": {"firmness": 10}})
    assert high and low and high != low


def test_a_centred_slider_says_nothing() -> None:
    """A persona with an opinion about everything has an opinion about nothing."""
    assert persona_style_line({"traits": dict.fromkeys(
        ("empathy", "firmness", "formality", "verbosity", "upsell"), 50
    )}) == ""


def test_a_missing_or_malformed_persona_degrades_rather_than_raising() -> None:
    """This assembles the system message for a live call."""
    for bad in (None, {}, {"traits": "not a dict"}, {"traits": {"empathy": None}}):
        assert persona_style_line(bad) == ""
        assert "Speak English" in build_voice_system_prompt("", {}, persona=bad)


def test_the_style_block_stays_small_against_the_overlay() -> None:
    """Every token here is re-sent 2-3x per turn, so the budget is real."""
    line = persona_style_line({"traits": {
        "empathy": 100, "firmness": 0, "formality": 100, "verbosity": 0, "upsell": 100,
    }})
    assert len(line.split()) < 60, line


def test_the_authored_prompt_still_comes_first() -> None:
    """Persona is context; the operator's text is the policy."""
    out = build_voice_system_prompt("AUTHORED POLICY", {}, persona={"language": "Hindi"})
    assert out.index("AUTHORED POLICY") < out.index("## Persona")
