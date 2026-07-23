"""Map AgentTuning → Pipecat runtime objects (construction + live deltas).

agent_core.tuning owns the serialisable schema; this module is the only place
that imports Pipecat types for those knobs.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from agent_core.tuning import live_delta_only, merge_tuning_delta, normalize_tuning


def _language(code: str):
    from pipecat.transcriptions.language import Language

    mapping = {
        "en-IN": Language.EN_IN,
        "en-US": Language.EN_US,
        "en-GB": Language.EN_GB,
        "hi-IN": getattr(Language, "HI_IN", Language.EN_IN),
    }
    return mapping.get((code or "en-IN").strip(), Language.EN_IN)


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
        return UserTurnStrategies(
            start=[MinWordsUserTurnStartStrategy(min_words=int(t["interaction"]["min_words"]))],
            stop=[SpeechTimeoutUserTurnStopStrategy()],
        )
    # Default: Smart Turn v3
    return UserTurnStrategies(
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
    kwargs: dict[str, Any] = {
        "voice": tts["voice"],
        "language": _language((tuning.get("stt") or {}).get("language") or "en-IN"),
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
        "temperature": float(llm["temperature"]),
        "system_instruction": system_instruction,
    }
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
    (Sandbox Tuning Studio). Only voice_name is typically applied at call start.
    """
    from agent_core.tuning import apply_voice_config_overlay

    return apply_voice_config_overlay(
        normalize_tuning(raw),
        voice_name=voice_name,
        speed=speed,
        pitch=pitch,
        warmth=warmth,
    )


def merge_and_normalize(base: dict[str, Any] | None, delta: dict[str, Any] | None) -> dict[str, Any]:
    return merge_tuning_delta(base, delta)
