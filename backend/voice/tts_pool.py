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
import logging
from typing import Any

from azure.cognitiveservices.speech import Connection

from pipecat.frames.frames import StartFrame
from pipecat.services.azure.tts import AzureTTSService

from env_utils import env_float

logger = logging.getLogger(__name__)

# Ceiling on the websocket pre-open handshake at pipeline start.
_PREOPEN_TIMEOUT_S = env_float("AZURE_TTS_PREOPEN_TIMEOUT_S", 5.0)


class KeepAliveAzureTTSService(AzureTTSService):
    """AzureTTSService that pre-opens the synthesis websocket once, safely."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Accept and ignore a legacy keepalive_secs kwarg so callers don't break.
        kwargs.pop("keepalive_secs", None)
        super().__init__(*args, **kwargs)

    async def start(self, frame: StartFrame) -> None:
        await super().start(frame)
        # Safe: no synthesis has run yet, so open() cannot collide with speech.
        synth = getattr(self, "_speech_synthesizer", None)
        if synth is None:
            return
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
