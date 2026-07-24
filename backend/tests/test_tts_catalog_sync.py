"""Unit tests for TTS catalog tier derivation (no DB required)."""

from __future__ import annotations

from tts_catalog_sync import derive_price_tier, is_premium_tier, normalize_azure_voice


def test_standard_aarti():
    assert derive_price_tier("en-IN-AartiNeural", "Neural") == "standard"
    assert not is_premium_tier("standard")


def test_hd_dragon():
    assert derive_price_tier("en-US-Ava:DragonHDLatestNeural", "NeuralHD") == "hd"
    assert is_premium_tier("hd")


def test_hd_flash():
    assert derive_price_tier("en-US-JennyNeuralHDFlash", "Neural") == "hd_flash"
    assert is_premium_tier("hd_flash")


def test_turbo():
    assert derive_price_tier("en-US-AlloyTurboMultilingualNeural", "Neural") == "turbo"


def test_normalize_aarti():
    row = normalize_azure_voice(
        {
            "ShortName": "en-IN-AartiNeural",
            "DisplayName": "Aarti",
            "LocalName": "Aarti",
            "Gender": "Female",
            "Locale": "en-IN",
            "LocaleName": "English (India)",
            "VoiceType": "Neural",
            "Status": "GA",
            "SampleRateHertz": "48000",
        }
    )
    assert row is not None
    assert row["price_tier"] == "standard"
    assert row["is_premium"] is False
    assert row["display_name"] == "Aarti"
