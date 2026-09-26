"""Speed, Pitch and Warmth mean one thing: on the control, in the preview, on the call.

There were three definitions. The Voice tab offered speed 0.5-2.0 and pitch
+/-50 with no unit. The preview clamped speed to 0.5-1.5, read pitch as
semitones clamped to +/-6, and added its own warmth nudges to pitch, rate and
volume. The call turned speed into ``speed x 1.03`` clamped to 0.85-1.25 and
pitch into ``pitch x 2 %`` with 0 mapped to +2%. Speed 0.5 was 0.85x on a call,
Pitch 0 and Pitch 1 were the same call, and the preview was not the voice that
dialled.
"""

from __future__ import annotations

import pytest

from agent_core.providers import registry
from agent_core.tuning import (
    VOICE_PITCH_RANGE,
    VOICE_SPEED_RANGE,
    apply_voice_config_overlay,
    default_tuning,
    voice_pitch,
    voice_rate,
    warmth_style,
)
from azure_speech import build_ssml


def _control(key: str) -> dict:
    return next(d for d in registry.PARAM_AZURE_TTS if d["key"] == key)


def test_the_control_offers_exactly_the_range_the_call_applies() -> None:
    rate, pitch = _control("rate"), _control("pitch")
    assert (rate["min"], rate["max"]) == VOICE_SPEED_RANGE
    assert (pitch["min"], pitch["max"]) == VOICE_PITCH_RANGE
    assert rate["unit"] == "×" and pitch["unit"] == "st" and _control("pause_ms")["unit"] == "ms"


@pytest.mark.parametrize("speed", [0.5, 0.75, 1.0, 1.25, 1.5])
def test_speed_reaches_the_call_unchanged(speed: float) -> None:
    tts = apply_voice_config_overlay(default_tuning(), speed=speed)["tts"]
    assert tts["rate"] == f"{speed:.2f}"


def test_pitch_is_semitones_and_zero_is_neutral() -> None:
    assert voice_pitch(0) == "default"
    assert voice_pitch(1) == "+1st"
    assert voice_pitch(-3) == "-3st"
    assert voice_pitch(1) != voice_pitch(0), "Pitch 0 and Pitch 1 used to be the same call"
    assert voice_pitch(99) == "+6st" and voice_rate(9) == "1.50"


@pytest.mark.parametrize(
    "speed,pitch,warmth", [(0.8, -2, 30), (1.0, 0, 62), (1.2, 3, 85)]
)
def test_the_preview_speaks_what_the_call_will(speed: float, pitch: int, warmth: int) -> None:
    tts = apply_voice_config_overlay(default_tuning(), speed=speed, pitch=pitch, warmth=warmth)["tts"]
    ssml = build_ssml(
        "Hello there.", voice_name="en-IN-NeerjaNeural", speed=speed, pitch=pitch,
        warmth=warmth, pause_ms=300,
    )
    assert f'rate="{tts["rate"]}"' in ssml
    assert f'pitch="{tts["pitch"]}"' in ssml
    style, degree = warmth_style(warmth)
    assert (tts["style"], tts["style_degree"]) == (style, degree)
    assert f'style="{style}" styledegree="{float(degree):.2f}"' in ssml
    assert "volume=" not in ssml, "warmth no longer nudges a volume no call applies"
