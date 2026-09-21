"""The Pipecat MetricsFrame observer a CrmSink installs: TTFB/TTFA, token
usage and TTS characters land on the sink's meters as the pipeline reports
them. Carved out of crm_sink so the sink is the queue and its writers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from voice.crm_sink import CrmSink

logger = logging.getLogger(__name__)


def _cached_input_tokens(usage: Any) -> int | None:
    """Prompt-cache hits, whichever field the provider spells them in."""
    direct = getattr(usage, "cache_read_input_tokens", None)
    if direct is not None:
        return int(direct)
    details = getattr(usage, "prompt_tokens_details", None)
    if details is None and isinstance(usage, dict):
        details = usage.get("prompt_tokens_details")
    if details is None:
        return None
    cached = getattr(details, "cached_tokens", None)
    if cached is None and isinstance(details, dict):
        cached = details.get("cached_tokens")
    return int(cached) if cached is not None else None


def build(sink: "CrmSink") -> Any | None:
    """The MetricsFrame observer for one sink: latency, tokens and TTS characters.
    None if the Pipecat API is unavailable."""
    try:
        from pipecat.observers.base_observer import BaseObserver
        from pipecat.frames.frames import MetricsFrame
    except Exception:
        try:
            from pipecat.utils.base_object import BaseObject as BaseObserver  # type: ignore

            MetricsFrame = None  # type: ignore
        except Exception:
            return None

    # The usage classes carry their payload in `.value`, not as attributes on
    # the item, so they are matched by type rather than duck-typed. Optional
    # so an older/newer Pipecat that lacks them degrades to latency-only
    # observation instead of failing to build the observer at all.
    try:
        from pipecat.metrics.metrics import LLMUsageMetricsData, TTSUsageMetricsData
    except Exception:  # pragma: no cover - depends on pipecat version
        LLMUsageMetricsData = None  # type: ignore
        TTSUsageMetricsData = None  # type: ignore

    # Smart Turn already times its own inference and reports it here; nothing
    # read it, so "how long does end-pointing cost" had no answer and the
    # single-threaded ONNX session could not be argued about with a number.
    try:
        from pipecat.metrics.metrics import TurnMetricsData
    except Exception:  # pragma: no cover - depends on pipecat version
        TurnMetricsData = None  # type: ignore

    def _as_ms(value: Any) -> float | None:
        """Pipecat latency metrics are seconds — convert, don't guess.

        Every shape read below is documented and implemented in seconds:
        ``TTFBMetricsData.value`` is ``end_time - start_time``, and
        ``TTFAMetricsData.ttfa`` / ``.ttfb`` mirror it. The old magnitude
        test ("< 50 means seconds") happened to be right for realistic
        values but silently stopped converting above 50 s and would have
        multiplied a genuinely millisecond-valued field by a thousand.
        """
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        if v <= 0:
            return None
        return v * 1000.0

    # An observer is called for every hop a frame makes between processors, so one
    # MetricsFrame reached this code once per downstream stage -- seven times on a
    # phone pipeline, and every token, TTS character and latency sample was billed
    # and averaged seven times over. Each frame is counted once, by its id.
    seen: dict[int, None] = {}

    def _first_sighting(frame: Any) -> bool:
        frame_id = getattr(frame, "id", None)
        if frame_id is None:
            return True
        if frame_id in seen:
            return False
        seen[frame_id] = None
        if len(seen) > 1024:
            seen.pop(next(iter(seen)))
        return True

    class _MetricsObserver(BaseObserver):  # type: ignore[misc,valid-type]
        async def on_push_frame(self, data):  # noqa: ANN001
            try:
                frame = getattr(data, "frame", None) or data
                if (
                    MetricsFrame is not None
                    and isinstance(frame, MetricsFrame)
                    and _first_sighting(frame)
                ):
                    for item in getattr(frame, "data", None) or []:
                        name = str(getattr(item, "name", "") or "").lower()
                        cls = type(item).__name__.lower()

                        ttfb = getattr(item, "ttfb", None)
                        if ttfb is None and hasattr(item, "value") and "ttfb" in (name + cls):
                            ttfb = getattr(item, "value", None)
                        ms = _as_ms(ttfb)
                        if ms is not None:
                            sink.record_ttfb_ms(ms)

                        ttfa = getattr(item, "ttfa", None)
                        if ttfa is None and hasattr(item, "value") and "ttfa" in (name + cls):
                            ttfa = getattr(item, "value", None)
                        ms_a = _as_ms(ttfa)
                        if ms_a is not None:
                            sink.record_ttfa_ms(ms_a)

                        # leading_silence (new on TTFAMetricsData in 1.6.0)
                        # separates real TTS latency from padding at the
                        # head of the audio. Still not a column — it tunes the
                        # voice, it isn't a per-turn business metric — but it
                        # now reaches the turn trace instead of a DEBUG line
                        # nobody sees: it is the term that says whether a slow
                        # first syllable is Azure or our own aggregation.
                        lead = _as_ms(getattr(item, "leading_silence", None))
                        if lead is not None:
                            sink.record_turn_metric(leading_silence_ms=int(lead))

                        # Which end-of-turn decision this turn actually got,
                        # and what it cost to make.
                        if TurnMetricsData is not None and isinstance(item, TurnMetricsData):
                            sink.record_turn_metric(
                                smart_turn_ms=int(
                                    float(getattr(item, "e2e_processing_time_ms", 0) or 0)
                                ),
                                smart_turn_prob=round(
                                    float(getattr(item, "probability", 0) or 0), 3
                                ),
                                smart_turn_complete=int(
                                    bool(getattr(item, "is_complete", False))
                                ),
                            )

                        # Token usage. This previously read `item.tokens` /
                        # `item.total_tokens` / `item.prompt_tokens` straight
                        # off the metrics item — none of which exist on
                        # LLMUsageMetricsData, whose fields are
                        # (processor, model, value: LLMTokenUsage). Every
                        # getattr returned None, so record_tokens() was never
                        # called and interaction_transcript.tokens was NULL on
                        # every live call ever recorded.
                        if LLMUsageMetricsData is not None and isinstance(
                            item, LLMUsageMetricsData
                        ):
                            usage = getattr(item, "value", None)
                            if usage is not None:
                                prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
                                completion = int(
                                    getattr(usage, "completion_tokens", 0) or 0
                                )
                                # total_tokens is authoritative when present:
                                # some providers report a total that exceeds
                                # prompt+completion (audio/reasoning tokens).
                                total = int(getattr(usage, "total_tokens", 0) or 0)
                                if total > 0:
                                    sink.record_tokens(total)
                                elif prompt or completion:
                                    sink.record_tokens(prompt + completion)
                                cached = _cached_input_tokens(usage)
                                # Its own trace line, NOT folded into turn.e2e.
                                # LLM usage is pushed when the response
                                # finishes, and the bot starts speaking while it
                                # is still streaming -- so by the time turn.e2e
                                # is assembled (BotStartedSpeakingFrame) these
                                # may not have arrived, and stashing them would
                                # report them against the following turn. The
                                # prompt-cache hit rate is the evidence for the
                                # system-prompt reorder; attributing it to the
                                # wrong turn would make that unreadable.
                                sink._trace(
                                    "llm.turn",
                                    prompt_tokens=prompt or None,
                                    cached_tokens=cached,
                                    completion_tokens=completion or None,
                                    model=getattr(item, "model", None),
                                )
                                sink.usage.record_llm(
                                    prompt_tokens=prompt,
                                    completion_tokens=completion,
                                    model=getattr(item, "model", None),
                                    # Anthropic spells it cache_read_input_tokens;
                                    # Azure/OpenAI nest it as
                                    # prompt_tokens_details.cached_tokens. Only the
                                    # first was read, against an Azure deployment,
                                    # so no voice call had ever recorded a hit.
                                    cached_input_tokens=cached,
                                    reasoning_tokens=getattr(
                                        usage, "reasoning_tokens", None
                                    ),
                                )

                        # Characters synthesised, the unit Azure TTS bills.
                        if TTSUsageMetricsData is not None and isinstance(
                            item, TTSUsageMetricsData
                        ):
                            try:
                                chars = int(getattr(item, "value", 0) or 0)
                            except (TypeError, ValueError):
                                chars = 0
                            if chars > 0:
                                sink.usage.record_tts(
                                    chars=chars, model=getattr(item, "model", None)
                                )
            except Exception:
                logger.exception("metrics observer failed")

    try:
        return _MetricsObserver()
    except Exception:
        logger.exception("could not construct metrics observer")
        return None
