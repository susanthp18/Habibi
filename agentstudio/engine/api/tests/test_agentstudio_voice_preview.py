"""AgentStudio voice delivery: one mapping for live calls and previews."""

from types import SimpleNamespace
from xml.sax.saxutils import quoteattr

import pytest

from api.services.voice_catalog_local import (
    _azure_tier,
    _price_meter,
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


def test_a_voice_name_is_escaped_so_it_cannot_inject_ssml():
    ssml = azure_preview_ssml(voice="a'/><x", language=None, speed=1.0, delivery={}, text="hi")
    assert "<x" not in ssml and "name=\"a'/&gt;&lt;x\"" in ssml


@pytest.mark.parametrize("voice", ["en-US-Harper:MAI-Voice-2-Flash", "tr-TR-Aydın:MAI-Voice-2-Flash",
                                   "en-US-Voice:MAI-Voice-1.5 (Preview)"])
def test_any_name_azure_lists_can_be_previewed(voice):
    """30 Sep: MAI voices from Azure's own list were refused as "Invalid voice name":
    names are escaped, never matched against a character pattern."""
    assert f"<voice name={quoteattr(voice)}>" in azure_preview_ssml(
        voice=voice, language=None, speed=1.0, delivery={}, text="hi")


def test_hd_voices_are_labelled_as_premium():
    # VoiceType values as Azure's southeastasia voice list reports them.
    assert _azure_tier("en-US-Ava:DragonHDLatestNeural", "NeuralHD") == "hd"
    assert _azure_tier("en-US-Tiana:DragonHDFlashLatestNeural", "Neural") == "neural"
    assert _azure_tier("en-IN-AartiNeural", "Neural") == "neural"
    assert _azure_tier("hi-IN-Kavya:MAI-Voice-2", "NeuralHD") == "mai"
    # Billing follows VoiceType: full MAI at the HD rate, Flash at neural.
    assert _price_meter("NeuralHD") == "hd"
    assert _price_meter("Neural") == "neural"


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


def test_a_voice_azure_lists_can_be_saved():
    from api.services.configuration.registry import AzureSpeechTTSConfiguration

    name = "en-US-Voice:MAI-Voice-1.5 (Preview)"
    config = AzureSpeechTTSConfiguration(api_key="k", voice=name, voice_map={"hi-IN": name})
    assert config.voice == name and config.voice_map == {"hi-IN": name}
    with pytest.raises(ValueError):
        AzureSpeechTTSConfiguration(api_key="k", voice=" ")
