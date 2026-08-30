"""Choosing a language in the Studio must reach the recogniser and the model.

Three surfaces named a language and none of them were connected. The Persona tab
wrote a display name into ``persona.language``; the recogniser bound
``AgentTuning.stt.language``, a BCP-47 tag that normalisation fills with
``en-IN`` when absent; and the ``{language}`` prompt variable substituted
whatever the render context carried, which on voice was always ``"English"``.

So Hindi could be selected, saved, published and dialled, and the call would
listen in English, speak English, and be *told* to speak English — with nothing
anywhere reporting a conflict. Worse, ``normalize_language`` knew four tags while
the tab offered eight languages, so Tamil, Telugu, Kannada, Marathi, Bengali and
Gujarati each fell through ``mapping.get``'s silent default back to en-IN.

The fix is a registry (:mod:`agent_core.languages`) that owns both vocabularies,
and the same explicit-wins precedence the TTS voice already had.
"""

from __future__ import annotations

import pytest

from agent_core import languages
from voice.tuning_apply import normalize_language, resolve_session_tuning


def test_every_offered_language_binds_a_distinct_recogniser() -> None:
    """The bug was six of eight collapsing onto en-IN, indistinguishably."""
    bound = {entry.name: normalize_language(entry.tag) for entry in languages.LANGUAGES}
    assert len(set(bound.values())) == len(languages.LANGUAGES), bound


def test_an_unknown_tag_still_falls_back_rather_than_raising() -> None:
    """This runs inside the live audio path; a typo must not end the call."""
    assert normalize_language("xx-YY") == normalize_language(languages.DEFAULT_TAG)


def test_name_and_tag_round_trip() -> None:
    for entry in languages.LANGUAGES:
        assert languages.tag_for(entry.name) == entry.tag
        assert languages.name_for(entry.tag) == entry.name


@pytest.mark.parametrize("variant", ["hi-IN", "hi_IN", "HI-in", " hi-in "])
def test_tags_are_matched_however_they_arrive(variant: str) -> None:
    """Tuning JSON, operator typing and provider callbacks disagree on shape."""
    assert languages.name_for(variant) == "Hindi"


def test_an_unmappable_name_is_not_guessed_at() -> None:
    """`None`, not the default — the caller must be able to tell the two apart."""
    assert languages.tag_for("Klingon") is None
    assert languages.spoken_name(None) == languages.DEFAULT_NAME


def test_the_persona_language_binds_the_recogniser() -> None:
    tuning = resolve_session_tuning({}, persona_language="Tamil")
    assert tuning["stt"]["language"] == "ta-IN"


def test_the_chosen_language_leads_its_own_fallback_list() -> None:
    """A Tamil card whose first fallback is en-IN switches itself to English.

    ``fallback_languages`` is a priority order, so appending the choice behind
    the defaults would undo the choice on the first ambiguous utterance.
    """
    tuning = resolve_session_tuning({}, persona_language="Tamil")
    assert tuning["stt"]["fallback_languages"][0] == "ta-IN"
    assert tuning["stt"]["fallback_languages"].count("ta-IN") == 1


def test_an_explicit_tuning_language_still_wins() -> None:
    """Same precedence as the TTS voice: the Tuning Studio is more specific."""
    tuning = resolve_session_tuning({"stt": {"language": "en-US"}}, persona_language="Hindi")
    assert tuning["stt"]["language"] == "en-US"


def test_an_unmappable_persona_language_leaves_the_recogniser_alone() -> None:
    tuning = resolve_session_tuning({}, persona_language="Klingon")
    assert tuning["stt"]["language"] == languages.DEFAULT_TAG


def test_no_persona_is_unchanged_from_before() -> None:
    """The default path must not have moved."""
    assert resolve_session_tuning({})["stt"]["language"] == languages.DEFAULT_TAG
