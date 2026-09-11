"""VOICE-3: the Voice tab's speaking-style selector was dead config -- the
preview ignored it and the runtime derived a style from warmth alone."""

from __future__ import annotations

from agent_core.tuning import apply_voice_config_overlay, default_tuning
from azure_speech import build_ssml, cache_key


def test_an_authored_style_overrides_the_warmth_mapping() -> None:
    t = apply_voice_config_overlay(default_tuning(), warmth=80, style="calm")
    assert t["tts"]["style"] == "calm"
    t = apply_voice_config_overlay(default_tuning(), warmth=80)
    assert t["tts"]["style"] == "friendly"


def test_the_preview_speaks_the_selected_style() -> None:
    ssml = build_ssml("Hello there.", voice_name="en-IN-NeerjaNeural", warmth=80, style="calm")
    assert 'express-as style="calm"' in ssml
    assert cache_key(text="x", voice_name="v", speed=1.0, pitch=0, warmth=60, pause_ms=300, style="calm") != cache_key(
        text="x", voice_name="v", speed=1.0, pitch=0, warmth=60, pause_ms=300
    )


def test_a_missions_per_day_lowers_the_daily_cap() -> None:
    """OUTBOUND-09 / RUNTIME-11: `cadence.per_day` bounded nothing at runtime."""
    from contact_policy import daily_cap

    assert daily_cap(card_cap=1) == 1
    assert daily_cap(card_cap=99) == daily_cap()
