"""Azure STT with an overlapped language switch, so no caller audio is dropped.

The defect
----------
Pipecat 1.6.0's ``AzureSTTService._update_settings`` reconnects in place::

    if ("language" in changed or "profanity" in changed) and self._audio_stream:
        await self._disconnect()
        await self._connect()

``_disconnect`` closes the push stream and sets ``_audio_stream = None``, and
``run_stt`` writes only ``if self._audio_stream:`` -- so every audio frame that
arrives between the two calls is silently discarded. The trigger is, by
construction, a caller who is *mid-sentence*: the switch fires because they
just started speaking the new language. They say a sentence in Hindi, the
first part of it is never transcribed, and they are asked to repeat themselves.

What this changes, and what it does not
---------------------------------------
Only the ordering. The new recogniser is built and started *before* the live
one is retired, and the stream is swapped in a single assignment, so there is
no window in which ``_audio_stream`` is ``None``. ``PushAudioInputStream``
buffers whatever is written before the recogniser finishes connecting, so the
audio is queued rather than lost.

Not changed: one locale at a time, the same detection, the same settings, the
same recogniser class. This is not a second concurrent transcription.

Two review claims this does NOT fix, because they are not true of this SDK:
``start_continuous_recognition_async`` and ``stop_continuous_recognition_async``
return a ``ResultFuture`` immediately and neither call site takes ``.get()``,
so neither parks the event loop. The cost was the dropped audio, not a stall.

Upgrade risk
------------
This reaches into ``_speech_config``, ``_audio_stream`` and
``_speech_recognizer``, and reimplements the six lines of
``_update_settings`` that precede the reconnect. That is the accepted
extension point for a fix Pipecat does not expose, but it is pinned by a test
and must be re-read on any Pipecat upgrade: if upstream starts overlapping the
reconnect itself, delete this module.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from azure.cognitiveservices.speech import Connection
from pipecat.frames.frames import StartFrame
from pipecat.services.azure.stt import AzureSTTService

from env_utils import env_float

logger = logging.getLogger(__name__)

# Same ceiling as TTS. The pre-open is a latency optimisation; a timeout is
# just a slower first transcript, never a refused call.
_PREOPEN_TIMEOUT_S = env_float("AZURE_STT_PREOPEN_TIMEOUT_S", 5.0)


class OverlappedAzureSTTService(AzureSTTService):
    """``AzureSTTService`` whose language switch never drops the caller's audio."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # After the parent builds ``_speech_config``. Language swap keeps the
        # same config and a new recogniser, so the knob survives a switch.
        # Pipecat upgrade must re-read this private attribute.
        self._apply_segmentation_silence()
        self._preopen_task: asyncio.Task[None] | None = None

    async def start(self, frame: StartFrame) -> None:
        await super().start(frame)
        # Parent start() builds the recogniser. Handshake in the background so
        # Flow init is not sitting behind the Azure connect; run_stt joins
        # before writing audio. Never call open() from run_stt — that is the
        # TTS 41s deadlock class, applied to the recogniser.
        rec = getattr(self, "_speech_recognizer", None)
        if rec is None:
            return
        self._preopen_task = asyncio.create_task(self._preopen(rec))

    async def _preopen(self, rec: Any) -> None:
        try:
            connection = Connection.from_recognizer(rec)
            await asyncio.wait_for(
                asyncio.to_thread(connection.open, False), timeout=_PREOPEN_TIMEOUT_S
            )
            logger.info("azure stt websocket pre-opened at start")
        except asyncio.TimeoutError:
            logger.warning(
                "azure stt pre-open timed out after %.1fs — continuing cold",
                _PREOPEN_TIMEOUT_S,
            )
        except Exception:
            logger.debug("azure stt pre-open failed", exc_info=True)

    async def _await_preopen(self) -> None:
        task = getattr(self, "_preopen_task", None)
        if task is None or task.done():
            return
        await task

    async def run_stt(self, audio: bytes):
        await self._await_preopen()
        async for frame in super().run_stt(audio):
            yield frame

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

    async def _update_settings(self, delta: Any) -> dict[str, Any]:
        # Grandparent, not parent: STTService._update_settings does the settings
        # bookkeeping and returns what changed; AzureSTTService then adds the
        # in-place reconnect this class exists to replace. Calling the
        # grandparent skips only that reconnect.
        from pipecat.services.stt_service import STTService

        changed = await STTService._update_settings(self, delta)

        # Mirrors AzureSTTService._update_settings. Kept in step deliberately;
        # see the module docstring on upgrade risk.
        if "language" in changed:
            from pipecat.services.azure.common import language_to_azure_language
            from pipecat.services.settings import assert_given
            from pipecat.transcriptions.language import Language

            self._speech_config.speech_recognition_language = assert_given(
                self._settings.language
            ) or language_to_azure_language(Language.EN_US)

        if "profanity" in changed:
            self._apply_profanity()

        if ("language" in changed or "profanity" in changed) and self._audio_stream:
            await self._swap_recognizer()

        return changed

    async def _swap_recognizer(self) -> None:
        """Start the new recogniser, then retire the old one. Never the reverse."""
        from azure.cognitiveservices.speech.audio import (
            AudioConfig,
            AudioStreamFormat,
            PushAudioInputStream,
        )
        from azure.cognitiveservices.speech import SpeechRecognizer

        old_recognizer = self._speech_recognizer
        old_stream = self._audio_stream

        try:
            stream_format = AudioStreamFormat(samples_per_second=self.sample_rate, channels=1)
            new_stream = PushAudioInputStream(stream_format)
            new_recognizer = SpeechRecognizer(
                speech_config=self._speech_config,
                audio_config=AudioConfig(stream=new_stream),
            )
            new_recognizer.recognizing.connect(self._on_handle_recognizing)
            new_recognizer.recognized.connect(self._on_handle_recognized)
            new_recognizer.canceled.connect(self._on_handle_canceled)
            new_recognizer.start_continuous_recognition_async()
        except Exception:
            # The live recogniser is untouched, so the call keeps hearing the
            # caller in the previous locale. A failed switch must degrade to
            # "wrong language", never to "no transcription".
            logger.exception("STT language swap failed — staying on the current recogniser")
            return

        # The single assignment that makes this safe: run_stt never observes
        # _audio_stream as None, so no frame is dropped.
        self._speech_recognizer = new_recognizer
        self._audio_stream = new_stream

        if old_recognizer is not None:
            # Disconnect first. A late result from the old recogniser would
            # otherwise arrive through the same callbacks and land as this
            # turn's transcript, in the locale the caller just switched away
            # from.
            for signal in ("recognizing", "recognized", "canceled"):
                try:
                    getattr(old_recognizer, signal).disconnect_all()
                except Exception:
                    logger.debug("could not disconnect old %s handler", signal, exc_info=True)
            try:
                old_recognizer.stop_continuous_recognition_async()
            except Exception:
                logger.debug("old recognizer stop failed", exc_info=True)

        if old_stream is not None:
            try:
                old_stream.close()
            except Exception:
                logger.debug("old audio stream close failed", exc_info=True)
