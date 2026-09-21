"""Azure STT end-of-utterance silence (Phase 3.6 / remaining cluster 6).

Unset/empty ships 150ms. ``false`` / ``0`` leaves Pipecat's SDK default (~500).
Clamp 100-2000.
"""

from __future__ import annotations

import pytest

from voice.config import voice_stt_segmentation_silence_ms
from voice.stt_service import OverlappedAzureSTTService


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, 150),
        ("", 150),
        ("150", 150),
        ("150.9", 150),
        ("50", 100),
        ("2000", 2000),
        ("2001", 2000),
        ("0", None),
        ("false", None),
        ("nope", 150),
    ],
)
def test_segmentation_silence_ms_parses_clamps_and_stays_unset(monkeypatch, raw, expected):
    monkeypatch.setattr("voice.config._optional", lambda _name: raw)
    assert voice_stt_segmentation_silence_ms() == expected


class _Cfg:
    def __init__(self) -> None:
        self.props: dict = {}

    def set_property(self, key, value) -> None:
        self.props[key] = value


def _bare_stt() -> OverlappedAzureSTTService:
    svc = object.__new__(OverlappedAzureSTTService)
    svc._speech_config = _Cfg()
    return svc


def test_unset_segmentation_does_not_touch_speech_config(monkeypatch):
    monkeypatch.setattr("voice.config.voice_stt_segmentation_silence_ms", lambda: None)
    svc = _bare_stt()
    svc._apply_segmentation_silence()
    assert svc._speech_config.props == {}


def test_set_segmentation_writes_the_azure_property(monkeypatch):
    monkeypatch.setattr("voice.config.voice_stt_segmentation_silence_ms", lambda: 150)
    svc = _bare_stt()
    svc._apply_segmentation_silence()
    from azure.cognitiveservices.speech import PropertyId

    assert svc._speech_config.props == {
        PropertyId.Speech_SegmentationSilenceTimeoutMs: "150",
    }
