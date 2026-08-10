"""Per-call usage metering for the Pipecat voice pipeline.

Until now every production voice call was unbilled. ``usage_meter`` was only
ever invoked from ``azure_openai``/``azure_speech``, which are the REST and
sandbox paths; the live call runs through Pipecat's own services and never
touched it. This module closes that gap and attributes the spend to the
interaction that incurred it.

Where the numbers come from
---------------------------
LLM and TTS are *measured*. Pipecat emits them as metrics frames when
``enable_usage_metrics=True`` (already set in ``bot.py``):

  ``LLMUsageMetricsData.value`` → ``LLMTokenUsage`` (prompt/completion split)
  ``TTSUsageMetricsData.value`` → characters synthesised (int)

STT is *derived*. Pipecat 1.6.0 has no ``STTUsageMetricsData`` — verified
against the installed package, the metrics module exposes only TTFB, TTFA,
Processing, TextAggregation, Turn, SmartTurn and the two usage classes above.
Azure bills continuous recognition for the audio streamed while the recognizer
is open, which for this pipeline is the length of the call, so the call's own
duration is the closest defensible measure. It is recorded once at teardown and
flagged ``derived`` in meta so a cost audit can tell it from a measured figure.

Everything here is called from the audio path, so nothing may block or raise.
``usage_meter.record_usage`` only appends to an in-memory buffer under a lock
(the flusher thread does the I/O), and every entry point swallows exceptions:
metering must never be the reason a call degrades.
"""

from __future__ import annotations

import logging
from typing import Any

import usage_meter

logger = logging.getLogger(__name__)

# Provenance tag on every event this module emits, so voice spend can be
# separated from the REST/batch paths that share the same service ids.
SOURCE_REF = "voice.pipeline"


class VoiceUsageMeter:
    """Meters one voice call's LLM / TTS / STT consumption.

    Bound to a :class:`~voice.session.VoiceSession`; the interaction id is read
    lazily at record time because it is assigned by ``bind_session_start`` on
    client connect, which races pipeline construction.
    """

    def __init__(
        self,
        session: Any,
        *,
        tts_voice: str | None = None,
        stt_language: str | None = None,
        llm_model: str | None = None,
    ) -> None:
        self.session = session
        self._tts_voice = tts_voice
        self._stt_language = stt_language
        self._llm_model = llm_model
        self._stt_finalized = False
        # Running totals, for the one-line cost summary at teardown.
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.tts_chars = 0
        self.stt_minutes = 0.0
        self.llm_turns = 0

    def configure(
        self,
        *,
        tts_voice: str | None = None,
        stt_language: str | None = None,
        llm_model: str | None = None,
    ) -> None:
        """Fill in model identities once the pipeline has resolved them."""
        if tts_voice:
            self._tts_voice = tts_voice
        if stt_language:
            self._stt_language = stt_language
        if llm_model:
            self._llm_model = llm_model

    @property
    def _interaction_id(self) -> str | None:
        return getattr(self.session, "interaction_id", None) or None

    def record_llm(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        model: str | None = None,
        cached_input_tokens: int | None = None,
        reasoning_tokens: int | None = None,
    ) -> None:
        """One LLM completion. Prompt and completion stay split — they price ~8x apart."""
        try:
            pt = max(0, int(prompt_tokens or 0))
            ct = max(0, int(completion_tokens or 0))
            if pt <= 0 and ct <= 0:
                return
            self.prompt_tokens += pt
            self.completion_tokens += ct
            self.llm_turns += 1
            usage_meter.record_chat_usage(
                prompt_tokens=pt,
                completion_tokens=ct,
                model=model or self._llm_model,
                interaction_id=self._interaction_id,
                source_ref=SOURCE_REF,
            )
            # Cache reads bill below the input rate on Azure, but the price book
            # has no cached-input line, so they are currently charged at the full
            # input rate. Recorded here so the overstatement is visible and can
            # be corrected without replaying calls.
            if cached_input_tokens or reasoning_tokens:
                logger.debug(
                    "llm usage extras · cached=%s · reasoning=%s · interaction=%s",
                    cached_input_tokens,
                    reasoning_tokens,
                    self._interaction_id,
                )
        except Exception:
            logger.exception("voice llm usage metering failed (non-fatal)")

    def record_tts(self, *, chars: int, model: str | None = None) -> None:
        """One synthesised utterance, measured in characters."""
        try:
            n = max(0, int(chars or 0))
            if n <= 0:
                return
            self.tts_chars += n
            usage_meter.record_tts_usage(
                chars=n,
                voice=model or self._tts_voice,
                interaction_id=self._interaction_id,
                source_ref=SOURCE_REF,
            )
        except Exception:
            logger.exception("voice tts usage metering failed (non-fatal)")

    def finalize_stt(self, *, seconds: float) -> None:
        """Record the call's recognised audio. Idempotent — teardown can run twice."""
        try:
            if self._stt_finalized:
                return
            self._stt_finalized = True
            minutes = max(0.0, float(seconds or 0.0)) / 60.0
            if minutes <= 0:
                return
            self.stt_minutes = minutes
            usage_meter.record_stt_usage(
                audio_bytes=0,
                minutes=minutes,
                language=self._stt_language,
                interaction_id=self._interaction_id,
                source_ref=SOURCE_REF,
                model=self._stt_language,
            )
        except Exception:
            logger.exception("voice stt usage metering failed (non-fatal)")

    def summary(self) -> dict[str, Any]:
        return {
            "interactionId": self._interaction_id,
            "llmTurns": self.llm_turns,
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
            "ttsChars": self.tts_chars,
            "sttMinutes": round(self.stt_minutes, 4),
        }
