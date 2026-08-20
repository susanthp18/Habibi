"""Map AgentTuning → Pipecat runtime objects (construction + live deltas).

agent_core.tuning owns the serialisable schema; this module is the only place
that imports Pipecat types for those knobs.
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger

from agent_core.tuning import live_delta_only, normalize_tuning


def _is_reasoning_model(model: str) -> bool:
    """gpt-5 / o-series deployments reject sampling params (temperature/top_p/
    penalties) and require max_completion_tokens. Explicit config override wins
    over the name heuristic, since deployment names are user-defined aliases.
    """
    raw = (os.getenv("AZURE_OPENAI_VOICE_REASONING_MODEL")
           or os.getenv("AZURE_OPENAI_REASONING_MODEL") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    d = (model or "").lower()
    return d.startswith(("o1", "o3", "o4")) or "gpt-5" in d or "gpt5" in d


def normalize_language(code: str):
    """BCP-47 tag → Pipecat ``Language``, defaulting to en-IN.

    Public: mid-call language switching in voice.bot needs this, and reaching
    across modules for a private helper made an internal rename a runtime break
    in the live audio path.
    """
    from pipecat.transcriptions.language import Language

    mapping = {
        "en-in": Language.EN_IN,
        "en-us": Language.EN_US,
        "en-gb": Language.EN_GB,
        "hi-in": getattr(Language, "HI_IN", Language.EN_IN),
    }
    # Case- and separator-insensitive: BCP-47 tags arrive as en-US, en_us or
    # en-us depending on whether they came from the tuning JSON, an operator
    # typing into the Voice tab, or a provider callback. An exact-match lookup
    # silently dropped every variant to en-IN.
    key = (code or "en-IN").strip().replace("_", "-").lower()
    return mapping.get(key, Language.EN_IN)


# Backwards-compatible alias for in-module call sites.
_language = normalize_language


def text_aggregation_mode(tuning: dict[str, Any]):
    from pipecat.services.tts_service import TextAggregationMode

    mode = str((tuning.get("tts") or {}).get("text_aggregation_mode") or "SENTENCE").upper()
    return TextAggregationMode.TOKEN if mode == "TOKEN" else TextAggregationMode.SENTENCE


def build_vad_params(tuning: dict[str, Any]):
    from pipecat.audio.vad.vad_analyzer import VADParams

    vad = normalize_tuning(tuning)["vad"]
    return VADParams(
        confidence=float(vad["confidence"]),
        start_secs=float(vad["start_secs"]),
        stop_secs=float(vad["stop_secs"]),
        min_volume=float(vad["min_volume"]),
    )


def build_smart_turn_analyzer(tuning: dict[str, Any]):
    from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3

    turn = normalize_tuning(tuning)["turn"]
    params = SmartTurnParams(
        stop_secs=float(turn["stop_secs"]),
        pre_speech_ms=float(turn["pre_speech_ms"]),
        max_duration_secs=float(turn["max_duration_secs"]),
    )
    return LocalSmartTurnAnalyzerV3(params=params)


def build_user_turn_strategies(tuning: dict[str, Any]):
    """Turn start/stop strategies for one ``barge_in`` mode.

    **Start and stop must be driven by the same signal.** Pipecat's stop
    strategies are not interchangeable: ``TurnAnalyzerUserTurnStopStrategy``
    (Smart Turn v3) ends a turn on ``VADUserStoppedSpeakingFrame``, while
    ``SpeechTimeoutUserTurnStopStrategy`` ends it on transcript inactivity.
    Pairing a transcript-driven *start* with the VAD-driven *stop* leaves the
    turn waiting for a VAD stop that already fired before the turn began — the
    turn never ends. That is why ``min_words`` below keeps its own stop
    strategy rather than sharing the Smart Turn one; it is a matched pair, not
    an oversight.
    """
    from pipecat.turns.user_start import (
        MinWordsUserTurnStartStrategy,
        VADUserTurnStartStrategy,
    )
    from pipecat.turns.user_stop import (
        SpeechTimeoutUserTurnStopStrategy,
        TurnAnalyzerUserTurnStopStrategy,
    )
    from pipecat.turns.user_turn_strategies import UserTurnStrategies

    t = normalize_tuning(tuning)
    barge = t["interaction"]["barge_in"]

    if barge == "locked":
        return UserTurnStrategies(
            start=[VADUserTurnStartStrategy(enable_interruptions=False)],
        )
    if barge == "min_words":
        # Transcript-driven start, transcript-driven stop. See the docstring.
        return UserTurnStrategies(
            start=[MinWordsUserTurnStartStrategy(min_words=int(t["interaction"]["min_words"]))],
            stop=[SpeechTimeoutUserTurnStopStrategy()],
        )
    # Default ("on"): VAD start, Smart Turn v3 stop.
    #
    # ``start`` is stated rather than left to Pipecat's default. That default is
    # ``[VADUserTurnStartStrategy, TranscriptionUserTurnStartStrategy]`` — two
    # independent triggers, either of which interrupts the bot. The
    # transcription half is the harmful one on a phone call: a transcript
    # describes audio from hundreds of milliseconds ago, so a final hypothesis
    # that lands mid-sentence interrupts the bot on speech the caller finished
    # before the bot even started talking. On VS-39B35AC484 the bot was cut off
    # three times this way and the caller heard a reply that never completed.
    #
    # VAD alone measures the present, and it pairs correctly with the Smart Turn
    # stop strategy below (both keyed on VAD start/stop). Backchannels ("yeah",
    # "mm-hmm") still interrupt in this mode — that is what ``min_words`` is
    # for, and the Tuning Studio exposes it.
    return UserTurnStrategies(
        start=[VADUserTurnStartStrategy()],
        stop=[
            TurnAnalyzerUserTurnStopStrategy(
                turn_analyzer=build_smart_turn_analyzer(t),
            )
        ]
    )


def build_user_mute_strategies(tuning: dict[str, Any]) -> list[Any]:
    from pipecat.turns.user_mute import (
        AlwaysUserMuteStrategy,
        FirstSpeechUserMuteStrategy,
        FunctionCallUserMuteStrategy,
        MuteUntilFirstBotCompleteUserMuteStrategy,
    )

    mute = normalize_tuning(tuning)["interaction"]["mute"]
    out: list[Any] = []
    for key in mute:
        if key == "until_first_bot_complete":
            out.append(MuteUntilFirstBotCompleteUserMuteStrategy())
        elif key == "during_function_calls":
            out.append(FunctionCallUserMuteStrategy())
        elif key == "always":
            out.append(AlwaysUserMuteStrategy())
        elif key == "first_speech":
            out.append(FirstSpeechUserMuteStrategy())
    return out


def build_stt_settings(tuning: dict[str, Any]):
    from pipecat.services.azure.stt import AzureSTTService

    stt = normalize_tuning(tuning)["stt"]
    return AzureSTTService.Settings(
        language=_language(stt["language"]),
        profanity=stt["profanity"],
    )


def build_tts_settings(tuning: dict[str, Any]):
    from pipecat.services.azure.tts import AzureTTSService

    tts = normalize_tuning(tuning)["tts"]
    stt = normalize_tuning(tuning)["stt"]
    kwargs: dict[str, Any] = {
        "voice": tts["voice"],
        "language": _language(stt.get("language") or "en-IN"),
        "rate": tts.get("rate") or "1.05",
        "pitch": tts.get("pitch") or "+2%",
    }
    if tts.get("volume") and tts["volume"] != "default":
        kwargs["volume"] = tts["volume"]
    if tts.get("style"):
        kwargs["style"] = tts["style"]
        kwargs["style_degree"] = str(tts.get("style_degree") or "1.0")
    if tts.get("emphasis"):
        kwargs["emphasis"] = tts["emphasis"]
    return AzureTTSService.Settings(**kwargs)


def build_llm_settings_kwargs(
    tuning: dict[str, Any],
    *,
    model: str,
    system_instruction: str,
) -> dict[str, Any]:
    llm = normalize_tuning(tuning)["llm"]
    kwargs: dict[str, Any] = {
        "model": model,
        "system_instruction": system_instruction,
    }
    # Reasoning deployments (o-series / GPT-5) reject temperature and the other
    # sampling params — omit them so live turns don't 400. Matches the prewarm
    # logic in llm_pool and azure_openai.
    if not _is_reasoning_model(model):
        kwargs["temperature"] = float(llm["temperature"])
        if llm.get("top_p") is not None:
            kwargs["top_p"] = float(llm["top_p"])
        if llm.get("frequency_penalty") is not None:
            kwargs["frequency_penalty"] = float(llm["frequency_penalty"])
        if llm.get("presence_penalty") is not None:
            kwargs["presence_penalty"] = float(llm["presence_penalty"])
    if llm.get("max_completion_tokens") is not None:
        kwargs["max_completion_tokens"] = int(llm["max_completion_tokens"])
    if llm.get("seed") is not None:
        kwargs["seed"] = int(llm["seed"])
    return kwargs


def user_idle_timeout(tuning: dict[str, Any]) -> float | None:
    secs = float(normalize_tuning(tuning)["interaction"]["idle_timeout_secs"])
    return None if secs <= 0 else secs


async def apply_live_tuning_delta(
    worker: Any,
    delta: dict[str, Any] | None,
    *,
    llm_settings_cls: Any,
    tts_settings_cls: Any,
) -> dict[str, Any]:
    """Queue LLM/TTS UpdateSettingsFrames for a mid-call Studio delta.

    Returns the live-only subset that was applied (for logging / ack).
    """
    from pipecat.frames.frames import LLMUpdateSettingsFrame, TTSUpdateSettingsFrame

    live = live_delta_only(delta)
    if not live:
        return {}

    if "llm" in live and live["llm"]:
        llm_delta = dict(live["llm"])
        # system_instruction / model are not mid-call knobs from the Studio.
        llm_delta.pop("model", None)
        llm_delta.pop("system_instruction", None)
        try:
            await worker.queue_frame(LLMUpdateSettingsFrame(delta=llm_settings_cls(**llm_delta)))
        except Exception:
            logger.exception("LLMUpdateSettingsFrame failed · delta={}", llm_delta)

    if "tts" in live and live["tts"]:
        tts_delta = dict(live["tts"])
        # language is an enum on Settings — map if present as string.
        if "language" in tts_delta and isinstance(tts_delta["language"], str):
            tts_delta["language"] = _language(tts_delta["language"])
        try:
            await worker.queue_frame(TTSUpdateSettingsFrame(delta=tts_settings_cls(**tts_delta)))
        except Exception:
            logger.exception("TTSUpdateSettingsFrame failed · delta={}", tts_delta)

    return live


def resolve_session_tuning(
    raw: dict[str, Any] | None,
    *,
    voice_name: str | None = None,
    speed: float | None = None,
    pitch: int | None = None,
    warmth: int | None = None,
) -> dict[str, Any]:
    """Normalize deployment/session tuning; optionally overlay Prompt Studio voice.

    Pass speed/pitch/warmth as None when AgentTuning.tts already owns those fields
    (Sandbox Tuning Studio). Stale / removed catalog voices fall back to
    en-IN-AartiNeural at runtime only.

    **Voice precedence.** Two surfaces can name a neural voice: the Prompt Studio
    voice picker (``voice_config.voiceId``, arriving here as ``voice_name``) and
    the Sandbox Tuning Studio picker (``AgentTuning.tts.voice``). This used to
    apply ``voice_name`` unconditionally, so the Tuning Studio selection was
    silently discarded on every call — pick William in the sandbox and the
    published version's voice answered instead.

    An explicit ``tts.voice`` now wins, and ``voice_name`` supplies the default
    when the tuning does not name one. The check reads *raw*, before
    ``normalize_tuning``, because normalisation invents ``en-IN-AartiNeural``
    for a missing voice — after it runs, a deliberate choice and a default are
    indistinguishable.
    """
    from agent_core.tuning import apply_voice_config_overlay

    explicit = str(((raw or {}).get("tts") or {}).get("voice") or "").strip()
    if explicit and voice_name and explicit != str(voice_name).strip():
        logger.info(
            "tts voice: using tuning '{}' over prompt-studio '{}'", explicit, voice_name
        )
    tuning = apply_voice_config_overlay(
        normalize_tuning(raw),
        voice_name=None if explicit else voice_name,
        speed=speed,
        pitch=pitch,
        warmth=warmth,
    )
    try:
        import db

        sn = str((tuning.get("tts") or {}).get("voice") or "").strip()
        warning = db.get_tts_voice_warning(sn) if sn else None
        if warning and warning.get("fallbackVoice"):
            logger.warning(
                "stale TTS voice {} ({}) → fallback {}",
                sn,
                warning.get("code"),
                warning.get("fallbackVoice"),
            )
            tuning.setdefault("tts", {})["voice"] = warning["fallbackVoice"]
            tuning["_voiceWarning"] = warning
    except Exception:
        # Catalog table may be missing mid-migration — keep selected voice.
        logger.debug("tts catalog warning check skipped", exc_info=True)
    return tuning
