"""A draft cannot carry a voice that contradicts its card without saying so.

Two failures met on one row. Draft ``v1_5-aace95`` on ``kaia-v2-4`` stored
``fish:7e4fa512aa564e198f8659b466f6ff70`` — AboFlah, Arabic, from Fish — while
the card's persona is English / en-IN and the published version speaks
``en-IN-AartiNeural``. The Voice tab rendered it as Selected, which was
truthful; the compiler passed every gate, which was not; and Publish was
enabled, which was one click from an English collections bot speaking Arabic.

G15 is the gate. These tests cover the half the pure-gate tests in
``test_agent_card_compile`` cannot: that the three facts G15 judges are the ones
the row actually holds, resolved the same way for the compile preview and for
publish — two call sites that used to have no reason to agree.

The restore tests cover the neighbouring hole the same investigation found:
``restore_prompt_version_as_draft`` was the one write path that copied the voice
jsonb verbatim, so any id nothing can resolve came back as a live draft.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import db


ARABIC_FISH_VOICE = "fish:7e4fa512aa564e198f8659b466f6ff70"
ENGLISH_VOICE = "en-IN-AartiNeural"


def _g15(report: dict) -> dict:
    return next(g for g in report["gates"] if g["gate"] == "G15")


@pytest.fixture
def scratch_version(db_tx):
    """A throwaway version on the demo card, so the real rows stay untouched."""
    version_id = f"zz-voice-{uuid.uuid4().hex[:8]}"

    def _make(voice: dict, persona: dict) -> str:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO prompt_versions
                      (id, tenant_id, bot_id, status, prompt, persona, voice,
                       guardrails, tuning, flow, agent_card, label, summary,
                       created_at, updated_at)
                    VALUES
                      (:id, :tenant, :bot, 'archived', 'probe',
                       CAST(:persona AS jsonb), CAST(:voice AS jsonb),
                       '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                       'v9.9', 'voice integrity probe', now(), now())
                    """
                ),
                {
                    "id": version_id,
                    "tenant": db._tenant(),
                    "bot": db.DEFAULT_BOT_ID,
                    "persona": db._jsonb(persona),
                    "voice": db._jsonb(voice),
                },
            )
        return version_id

    return _make


# --- the facts the gate judges ---------------------------------------------


def test_the_stored_voice_and_persona_reach_the_gate(db_tx) -> None:
    short, locale, tags = db.voice_locale_facts(
        {"voiceId": ARABIC_FISH_VOICE, "azureVoiceName": ARABIC_FISH_VOICE},
        {"language": "English", "fallbackLanguages": ["Hindi"]},
    )
    assert short == ARABIC_FISH_VOICE
    assert locale == "ar", "the catalog row is what says which language this voice speaks"
    assert tags == ["en-IN", "hi-IN"], "display names in, BCP-47 tags out — agent_core.languages"


def test_the_resolved_voice_is_judged_not_the_stored_id(db_tx) -> None:
    """v1.2 stores voiceId 'ravi' beside a valid azureVoiceName and speaks Aarti.

    Judging ``voiceId`` would have reported a broken card that works, which is
    the same class of untruth as the silence G15 was added to end.
    """
    short, locale, _ = db.voice_locale_facts(
        {"voiceId": "ravi", "azureVoiceName": ENGLISH_VOICE}, {"language": "English"}
    )
    assert short == ENGLISH_VOICE
    assert locale == "en-IN"


def test_an_unmapped_language_name_yields_no_tags(db_tx) -> None:
    """``tag_for`` returns None rather than the default for a name this build
    does not support, and the gate skips instead of warning against en-IN."""
    _, _, tags = db.voice_locale_facts({"voiceId": ENGLISH_VOICE}, {"language": "Klingon"})
    assert tags == []


# --- the compile preview ----------------------------------------------------


def test_the_compile_preview_gates_the_editors_unsaved_voice(db_tx) -> None:
    """The Studio holds the voice between autosaves. Without this the preview
    green-lights the last save while Publish ships what is on screen."""
    report = db.compile_agent_studio_card(
        db.DEFAULT_BOT_ID,
        voice={"voiceId": ARABIC_FISH_VOICE, "azureVoiceName": ARABIC_FISH_VOICE},
        persona={"language": "English", "fallbackLanguages": ["Hindi"]},
    )
    gate = _g15(report)
    assert gate["status"] == "warn"
    assert gate["issues"][0]["voiceLocale"] == "ar"
    assert "G15" not in [g["gate"] for g in report["gates"] if g["status"] == "fail"]


def test_the_shipped_card_compiles_without_a_locale_warning(db_tx) -> None:
    report = db.compile_agent_studio_card(
        db.DEFAULT_BOT_ID,
        voice={"voiceId": ENGLISH_VOICE, "azureVoiceName": ENGLISH_VOICE},
        persona={"language": "English", "fallbackLanguages": ["Hindi"]},
    )
    assert _g15(report)["status"] == "pass"


def test_the_preview_falls_back_to_the_stored_draft(db_tx) -> None:
    """No override supplied is the Publish-dialog case before the first
    autosave lands, and the row is then the only truth there is."""
    report = db.compile_agent_studio_card(db.DEFAULT_BOT_ID)
    assert _g15(report)["status"] in {"pass", "warn"}, "the demo card has a voice and a language"


# --- restore ----------------------------------------------------------------


def test_restoring_a_junk_voice_yields_a_draft_that_can_speak(scratch_version) -> None:
    source = scratch_version({"voiceId": "ravi", "azureVoiceName": "ravi"}, {"language": "English"})
    draft = db.restore_prompt_version_as_draft(source)
    assert db.get_tts_voice_catalog_entry(draft["voice"]["azureVoiceName"]) is not None
    assert draft["voice"]["voiceId"] == db.get_tts_voice_warning("ravi")["fallbackVoice"]


def test_a_legacy_alias_beside_a_real_voice_is_left_alone(scratch_version) -> None:
    """'ravi' is an alias, not damage: resolve_prompt_azure_voice prefers the
    row's own azureVoiceName, so this version already speaks correctly."""
    source = scratch_version(
        {"voiceId": "ravi", "azureVoiceName": ENGLISH_VOICE}, {"language": "English"}
    )
    draft = db.restore_prompt_version_as_draft(source)
    assert draft["voice"]["azureVoiceName"] == ENGLISH_VOICE


def test_a_real_voice_survives_restore_unchanged(scratch_version) -> None:
    source = scratch_version(
        {"voiceId": ARABIC_FISH_VOICE, "azureVoiceName": ARABIC_FISH_VOICE, "style": "male"},
        {"language": "English"},
    )
    draft = db.restore_prompt_version_as_draft(source)
    # Wrong language, but a real voice — that is G15's story to tell, not the
    # restorer's. Rewriting it here would discard an operator's choice.
    assert draft["voice"]["voiceId"] == ARABIC_FISH_VOICE
    assert draft["voice"]["style"] == "male"


def test_the_missing_voices_provider_controls_do_not_follow_it(scratch_version) -> None:
    """style and params are the vocabulary of the provider that is gone. Carried
    onto the Azure fallback they are noise the SSML preview would honour."""
    source = scratch_version(
        {
            "voiceId": "not-a-voice-at-all",
            "azureVoiceName": "not-a-voice-at-all",
            "style": "male",
            "params": {"latency": "normal"},
        },
        {"language": "English"},
    )
    draft = db.restore_prompt_version_as_draft(source)
    assert draft["voice"]["style"] is None
    assert draft["voice"]["params"] == {}
