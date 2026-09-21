"""Azure TTS with a SAFE connection pre-warm.

Problem (measured from logs.txt): AzureTTSService creates its SpeechSynthesizer
once in start(), but the Azure Speech SDK's underlying websocket idle-closes
during longer gaps, so the first utterance after a pause pays a full TLS+ws
re-handshake to eastus (~1.5s).

IMPORTANT — what does NOT work: calling `Connection.open()` repeatedly during
the call (periodic loop, or on user-speaking) to keep the socket warm. The Azure
SDK explicitly warns that `open()` may fail once synthesis has started, and in
practice calling it concurrently with an in-flight `speak_ssml_async` DEADLOCKS
the synthesizer — observed as a 41s TTS stall right after a barge-in, because the
warm() and the next filler synthesis collided. `open()` is an uncancellable
blocking SDK call, so no async guard can fully close that race.

Safe approach: open the connection exactly ONCE, at start(), before any
synthesis can run. That removes the greeting's cold-start with zero risk. During
an active conversation, synthesis happens every few seconds, which keeps the
socket warm naturally. After a long idle gap a single cold start (~1.5s) may
recur — that is acceptable and bounded, unlike the 41s deadlock, and the LLM
turn (p50 ~1.6s) dominates the turn budget anyway.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from collections import OrderedDict
from collections.abc import AsyncGenerator
from typing import Any

from azure.cognitiveservices.speech import Connection

from pipecat.frames.frames import Frame, StartFrame, TTSAudioRawFrame
from pipecat.services.azure.tts import AzureTTSService

from env_utils import env_float

logger = logging.getLogger(__name__)

# Ceiling on the websocket pre-open handshake at pipeline start.
_PREOPEN_TIMEOUT_S = env_float("AZURE_TTS_PREOPEN_TIMEOUT_S", 5.0)

#: Pre-synthesised audio for the closed set of filler phrases.
#:
#: The filler exists specifically to mask tool latency, so paying an Azure
#: round trip to make it audible is dead weight in the gap it was invented to
#: fill. The phrases are literals in voice/natural.py -- 14 strings, chosen by
#: random.choice -- so the audio for one is byte-identical every time.
#:
#: Keyed on the *SSML*, not the text. The SSML is what Azure actually receives,
#: and it is built from every setting that can change the output -- voice,
#: style, style degree, rate, pitch, volume, emphasis, language. Hashing it
#: means no field can be forgotten from the key, including one added later,
#: and a Tuning Studio edit changes the key on its own rather than serving a
#: stale voice.
_PCM_CACHE: "OrderedDict[tuple[int, str], list[bytes]]" = OrderedDict()
_PCM_CACHE_LOCK = threading.Lock()
_PCM_CACHE_MAX = 64


class KeepAliveAzureTTSService(AzureTTSService):
    """AzureTTSService that pre-opens the synthesis websocket once, safely."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Accept and ignore a legacy keepalive_secs kwarg so callers don't break.
        kwargs.pop("keepalive_secs", None)
        super().__init__(*args, **kwargs)
        self._preopen_task: asyncio.Task[None] | None = None

    async def start(self, frame: StartFrame) -> None:
        await super().start(frame)
        # Handshake in the background. Awaiting it here sat in front of Flow
        # init and the first LLM, so the caller heard silence for the full
        # Connection.open ceiling. run_tts joins the task before synthesis;
        # never call open() from run_tts — that is the 41s deadlock class.
        synth = getattr(self, "_speech_synthesizer", None)
        if synth is None:
            return
        self._preopen_task = asyncio.create_task(self._preopen(synth))

    async def _preopen(self, synth: Any) -> None:
        try:
            connection = Connection.from_speech_synthesizer(synth)
            # Bounded: Connection.open is a blocking SDK handshake, and a stalled
            # one held up pipeline startup indefinitely. The pre-open is a
            # latency optimisation, so a timeout is just a slower first turn.
            await asyncio.wait_for(
                asyncio.to_thread(connection.open, False), timeout=_PREOPEN_TIMEOUT_S
            )
            logger.info("azure tts websocket pre-opened at start")
        except asyncio.TimeoutError:
            logger.warning(
                "azure tts pre-open timed out after %.1fs — continuing cold",
                _PREOPEN_TIMEOUT_S,
            )
        except Exception:
            # Never fatal — the first synthesis just pays a normal cold start.
            logger.debug("azure tts pre-open failed", exc_info=True)

    async def _await_preopen(self) -> None:
        task = getattr(self, "_preopen_task", None)
        if task is None or task.done():
            return
        await task

    def _pcm_key(self, text: str) -> tuple[int, str] | None:
        try:
            ssml = self._construct_ssml(text)
        except Exception:
            return None
        return (int(self.sample_rate), hashlib.sha256(ssml.encode("utf-8")).hexdigest())

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        """Azure synthesis, short-circuited for the fixed phrase set.

        Only phrases :mod:`voice.natural` registers as cacheable are ever
        stored, so a model-authored sentence is always synthesised fresh. On a
        hit nothing is sent to Azure: no request, no usage metric, no billing.
        """
        from voice import config as voice_config
        from voice.natural import is_cacheable_phrase

        key = self._pcm_key(text) if voice_config.voice_tts_phrase_cache() else None

        if key is not None:
            with _PCM_CACHE_LOCK:
                cached = _PCM_CACHE.get(key)
                if cached is not None:
                    _PCM_CACHE.move_to_end(key)
            if cached:
                for chunk in cached:
                    yield TTSAudioRawFrame(
                        audio=chunk,
                        sample_rate=self.sample_rate,
                        num_channels=1,
                        context_id=context_id,
                    )
                # Azure's word-boundary callbacks drive this, and a cached
                # replay fires none -- so advance it here or the word timings
                # of the NEXT real synthesis in this response are offset by the
                # length of the filler. 16-bit mono, so bytes/2 samples.
                total_bytes = sum(len(c) for c in cached)
                self._cumulative_audio_offset += total_bytes / (2.0 * float(self.sample_rate))
                return

        should_store = key is not None and is_cacheable_phrase(text)
        collected: list[bytes] = []
        await self._await_preopen()
        async for frame in super().run_tts(text, context_id):
            if should_store and isinstance(frame, TTSAudioRawFrame):
                collected.append(frame.audio)
            yield frame

        if should_store and collected:
            with _PCM_CACHE_LOCK:
                _PCM_CACHE[key] = collected
                _PCM_CACHE.move_to_end(key)
                while len(_PCM_CACHE) > _PCM_CACHE_MAX:
                    _PCM_CACHE.popitem(last=False)


def clear_phrase_cache() -> None:
    """Drop every cached clip. Called when live tuning changes the voice."""
    with _PCM_CACHE_LOCK:
        _PCM_CACHE.clear()
