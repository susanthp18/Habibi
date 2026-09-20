"""Azure STT subclass that owns ``_speech_config`` for an optional silence knob.

Pipecat 1.6.0 never sets ``Speech_SegmentationSilenceTimeoutMs``. Habibi
applies ``VOICE_STT_SEGMENTATION_SILENCE_MS`` after the parent builds the
config. Unset leaves the SDK default (~500ms). A Pipecat upgrade must
re-read this private attribute.
"""

from __future__ import annotations

import logging
from typing import Any

from pipecat.services.azure.stt import AzureSTTService

logger = logging.getLogger(__name__)


class OverlappedAzureSTTService(AzureSTTService):
    """``AzureSTTService`` that can set Azure segmentation silence."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # After the parent builds ``_speech_config``. Language swap keeps the
        # same config and a new recogniser, so the knob survives a switch.
        # Pipecat upgrade must re-read this private attribute.
        self._apply_segmentation_silence()

    def _apply_segmentation_silence(self) -> None:
        from voice import config as voice_config

        ms = voice_config.voice_stt_segmentation_silence_ms()
        if ms is None:
            return
        cfg = getattr(self, "_speech_config", None)
        if cfg is None:
            return
        from azure.cognitiveservices.speech import PropertyId

        cfg.set_property(PropertyId.Speech_SegmentationSilenceTimeoutMs, str(ms))
