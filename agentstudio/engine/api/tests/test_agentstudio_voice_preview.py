"""AgentStudio voice delivery: one mapping for live calls and previews."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.services.voice_catalog_local import (
    _azure_tier,
    azure_delivery,
    azure_preview_ssml,
)


def test_defaults_add_nothing_so_azure_speaks_neutrally():
    assert azure_delivery(SimpleNamespace(style=None, style_degree=1.0, pitch=0, volume=100)) == {}


def test_delivery_maps_to_pipecat_azure_settings():
    cfg = SimpleNamespace(style="empathetic", style_degree=1.4, pitch=-2, volume=110)
    assert azure_delivery(cfg) == {
        "style": "empathetic",
        "style_degree": "1.40",
        "pitch": "-2st",
        "volume": "+10%",
    }


def test_unsafe_style_is_dropped_not_rendered():
    assert "style" not in azure_delivery(SimpleNamespace(style="x' onload='y", pitch=0, volume=100))


def test_preview_ssml_matches_the_call_and_escapes_text():
    ssml = azure_preview_ssml(
        voice="en-IN-AartiNeural",
        language=None,
        speed=1.1,
        delivery={"style": "friendly", "pitch": "+1st"},
        text="Pay <now> & save",
    )
    assert "xml:lang='en-IN'" in ssml or 'xml:lang="en-IN"' in ssml
    assert "express-as style=\"friendly\"" in ssml
    assert 'rate="1.10"' in ssml and 'pitch="+1st"' in ssml
    assert "Pay &lt;now&gt; &amp; save" in ssml


def test_preview_rejects_a_voice_name_that_could_inject_ssml():
    with pytest.raises(HTTPException):
        azure_preview_ssml(voice="a'/><x", language=None, speed=1.0, delivery={}, text="hi")


def test_hd_voices_are_labelled_as_premium():
    assert _azure_tier("en-US-Ava:DragonHDLatestNeural", "Neural") == "hd"
    assert _azure_tier("en-IN-AartiNeural", "Neural") == "neural"
    assert _azure_tier("hi-IN-Kavya:MAI-Voice-2", "Neural") == "mai"


def test_a_voice_speaks_its_own_and_secondary_locales_and_its_language():
    from api.services.voice_catalog_local import voice_speaks

    ava = {"language": "en-US", "locales": ["en-US", "hi-IN", "ta-IN", "ar-SA"]}
    assert voice_speaks(ava, "ta-IN") and voice_speaks(ava, "ar-AE")
    assert not voice_speaks({"language": "en-IN", "locales": ["en-IN"]}, "ta-IN")


def test_preview_speaks_a_sample_in_the_language_previewed():
    from api.services.voice_catalog_local import PREVIEW_TEXT, preview_text_for

    assert preview_text_for("ta-IN", "ta-IN-PallaviNeural") != PREVIEW_TEXT
    assert preview_text_for(None, "ar-AE-FatimaNeural").startswith("مرحباً")
    assert preview_text_for("en-IN", "en-US-AvaMultilingualNeural") == PREVIEW_TEXT
