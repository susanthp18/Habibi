"""Map AgentTuning → Pipecat runtime objects (construction + live deltas).

agent_core.tuning owns the serialisable schema; this module is the only place
that imports Pipecat types for those knobs.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from loguru import logger

from agent_core.tuning import live_delta_only, normalize_tuning


def _is_reasoning_model(model: str) -> bool:
    """The one definition, with the voice override read first."""
    import azure_openai

    return azure_openai._is_reasoning_deployment(
        model, envs=azure_openai.VOICE_REASONING_OVERRIDE_ENVS
    )


def normalize_language(code: str):
    """BCP-47 tag → Pipecat ``Language``, defaulting to en-IN.

    Public: mid-call language switching in voice.bot needs this, and reaching
    across modules for a private helper made an internal rename a runtime break
    in the live audio path.
    """
    from pipecat.transcriptions.language import Language

    from agent_core import languages

    # Every tag the Studio can author, plus the two non-Indian English variants
    # that only ever arrive from tuning JSON. Built from the registry rather
    # than hand-listed: this map used to carry four entries while the Persona
    # tab offered eight languages, so choosing Tamil bound an en-IN recogniser
    # and the mismatch was invisible — ``mapping.get`` falls back silently.
    mapping = {
        "en-us": Language.EN_US,
        "en-gb": Language.EN_GB,
    }
    for entry in languages.LANGUAGES:
        member = entry.tag.replace("-", "_").upper()
        resolved = getattr(Language, member, None)
        if resolved is None:
            # A build of pipecat without this language: keep the recogniser on
            # en-IN rather than raising inside the audio path, and say so once.
            logger.warning(
                "pipecat has no Language.{} for {} — falling back to en-IN",
                member,
                entry.name,
            )
            continue
        mapping[entry.tag.lower()] = resolved
    # Case- and separator-insensitive: BCP-47 tags arrive as en-US, en_us or
    # en-us depending on whether they came from the tuning JSON, an operator
    # typing into the Voice tab, or a provider callback. An exact-match lookup
    # silently dropped every variant to en-IN.
    key = (code or "en-IN").strip().replace("_", "-").lower()
    if key not in mapping:
        # Said, not silent. The substitution itself stays -- a call must not
        # die inside the audio path -- but the bind records it
        # (`voice.bot`: `language_substituted`), so a Tamil card served by an
        # English recogniser is on the interaction, not only in a log line.
        logger.warning("STT language {} is not mapped — recogniser bound to en-IN", code)
    return mapping.get(key, Language.EN_IN)


def language_supported(code: str | None) -> bool:
    """Whether ``code`` maps to a recogniser language without substitution."""
    from pipecat.transcriptions.language import Language

    key = (code or "").strip().replace("_", "-").lower()
    if not key:
        return True
    if key in {"en-us", "en-gb", "en-in"}:
        return True
    from agent_core import languages

    for entry in languages.LANGUAGES:
        if entry.tag.lower() == key:
            return getattr(Language, entry.tag.replace("-", "_").upper(), None) is not None
    return False



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


def build_vad_analyzer(tuning: dict[str, Any]):
    """A Silero analyzer for this tuning, from the warm pool when there is one.

    Measured at 327 ms warm (1374 ms cold) and rebuilt per call on the event
    loop. The object handed back is the same class with the same params; only
    when it was constructed changes, and it is never shared -- see
    voice/analyzer_pool.py.
    """
    from pipecat.audio.vad.silero import SileroVADAnalyzer

    from voice import analyzer_pool

    params = build_vad_params(tuning)
    return analyzer_pool.take(
        analyzer_pool.vad_key(params),
        lambda: SileroVADAnalyzer(params=params),
    )


def build_smart_turn_analyzer(tuning: dict[str, Any]):
    from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3

    from voice import analyzer_pool

    turn = normalize_tuning(tuning)["turn"]
    params = SmartTurnParams(
        stop_secs=float(turn["stop_secs"]),
        pre_speech_ms=float(turn["pre_speech_ms"]),
        max_duration_secs=float(turn["max_duration_secs"]),
    )
    # 215 ms warm, 386 ms cold, per call, on the loop. Same class, same params,
    # never shared between calls -- see voice/analyzer_pool.py.
    return analyzer_pool.take(
        analyzer_pool.turn_key(params, cpu_count=2),
        lambda: LocalSmartTurnAnalyzerV3(params=params, cpu_count=2),
    )


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

    from voice.greeting_hold import build_greeting_replay_turn_start_strategy
    from voice.ivr import build_keypad_turn_start_strategy

    t = normalize_tuning(tuning)
    barge = t["interaction"]["barge_in"]

    # Keypad input opens a turn in every mode. It is inert unless DTMF is on --
    # it matches only the prefix DTMFAggregator writes -- so it costs a call
    # that never sees a keypress nothing, and threading the transport flag down
    # here to gate it would buy nothing back.
    #
    # GreetingHold replay is the same shape: a TranscriptionFrame with no VAD
    # underneath, scoped to the hold_replay marker so ordinary speech cannot
    # reintroduce VS-39B35AC484. Interruptions are always on -- unmute means
    # the disclosure has already finished.
    def _start(*strategies):
        keypad = build_keypad_turn_start_strategy(
            enable_interruptions=barge != "locked",
        )
        replay = build_greeting_replay_turn_start_strategy()
        return [s for s in (keypad, replay, *strategies) if s is not None]

    if barge == "locked":
        # ``stop`` is stated, not omitted. UserTurnStrategies.__post_init__
        # fills an omitted stop list with a BRAND-NEW LocalSmartTurnAnalyzerV3()
        # at Pipecat's defaults (stop_secs=3, pre_speech_ms=500), so leaving it
        # out built a second ONNX session during setup -- pure added silence for
        # the caller -- and then ran the strictest compliance preset with the one
        # end-pointing config that ignores its own card's ``turn`` block.
        return UserTurnStrategies(
            start=_start(VADUserTurnStartStrategy(enable_interruptions=False)),
            stop=[
                TurnAnalyzerUserTurnStopStrategy(
                    turn_analyzer=build_smart_turn_analyzer(t),
                )
            ],
        )
    if barge == "min_words":
        # Transcript-driven start, transcript-driven stop. See the docstring.
        return UserTurnStrategies(
            start=_start(
                MinWordsUserTurnStartStrategy(min_words=int(t["interaction"]["min_words"]))
            ),
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
        start=_start(VADUserTurnStartStrategy()),
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


def stt_settings_kwargs(tuning: dict[str, Any]) -> dict[str, Any]:
    """Tuning as plain kwargs, before any provider's Settings class sees them.

    Split out from :func:`build_stt_settings` so the provider registry can bind
    a non-Azure recogniser: the factory filters these against whichever Settings
    class the bound model declares, which it cannot do with an already-built
    ``AzureSTTService.Settings`` instance.
    """
    stt = normalize_tuning(tuning)["stt"]
    return {"language": normalize_language(stt["language"]), "profanity": stt["profanity"]}


def build_stt_settings(tuning: dict[str, Any]):
    from pipecat.services.azure.stt import AzureSTTService

    return AzureSTTService.Settings(**stt_settings_kwargs(tuning))


def tts_settings_kwargs(tuning: dict[str, Any]) -> dict[str, Any]:
    """Tuning as plain kwargs. See :func:`stt_settings_kwargs`.

    The named keys below are Azure/SSML-shaped because ``AgentTuning.tts`` is.
    ``tts.params`` carries everything else — the controls the Voice tab renders
    from the selected model's own ``params_schema``, which for a Fish or
    Cartesia voice is not a subset of Azure's and for Deepgram is nearly empty.

    Nothing here decides which of those a provider accepts.
    :func:`agent_core.providers.factory.build` filters the merged settings
    against the bound model's ``Settings`` class and logs what it dropped, so a
    Fish ``temperature`` left on the card after switching to an Azure voice is
    discarded at construction rather than raising in the middle of call setup.
    """
    normalized = normalize_tuning(tuning)
    tts = normalized["tts"]
    stt = normalized["stt"]
    kwargs: dict[str, Any] = {
        "voice": tts["voice"],
        "language": normalize_language(stt.get("language") or "en-IN"),
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
    # setdefault, not assignment: the prosody keys above are derived from the
    # VoiceConfig sliders through `apply_voice_config_overlay`, and letting the
    # bag win would give one control two authorities that disagree after a
    # Tuning Studio edit.
    for key, value in (tts.get("params") or {}).items():
        kwargs.setdefault(key, value)
    return kwargs


def build_tts_settings(tuning: dict[str, Any]):
    """Azure's Settings, for the pre-registry fallback path.

    Filtered, unlike the registry path, because this one names a concrete class:
    ``tts.params`` may hold another provider's knobs (a card authored against a
    Fish voice whose binding is missing at call time still reaches here), and an
    undeclared kwarg is a ``TypeError`` during pipeline construction — which
    drops the call rather than the setting.
    """
    from pipecat.services.azure.tts import AzureTTSService

    from agent_core.providers.factory import settings_field_names

    kwargs = tts_settings_kwargs(tuning)
    allowed = settings_field_names(AzureTTSService.Settings)
    if allowed:
        dropped = sorted(set(kwargs) - allowed)
        if dropped:
            logger.debug("azure tts fallback dropped unsupported settings · keys={}", dropped)
        kwargs = {k: v for k, v in kwargs.items() if k in allowed}
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


def user_turn_stop_timeout(tuning: dict[str, Any]) -> float:
    """The aggregator's backstop when no stop strategy fires at all.

    A safety net, not a target. Read from tuning like every other end-pointing
    knob so an operator who shortens Smart Turn's ``stop_secs`` can shorten the
    ceiling above it too; it used to be a literal in bot_pipeline.
    """
    return float(normalize_tuning(tuning)["turn"]["stop_timeout_secs"])


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
        # Any TTS edit can change the voice, style, rate or prosody, so every
        # cached clip is now the wrong voice. The cache key is the SSML hash and
        # would miss on its own, but clearing is what bounds a process that
        # accumulates a generation of clips per Studio edit.
        try:
            from voice.tts_pool import clear_phrase_cache

            clear_phrase_cache()
        except Exception:
            logger.debug("tts phrase cache clear failed", exc_info=True)

        tts_delta = dict(live["tts"])
        # `params` is a nested bag, not a setting. Flattening it here is what
        # lets a mid-call Studio edit change a Fish temperature; leaving it
        # would hand `Settings(params={...})` to a class with no such field and
        # abort the whole delta, taking the prosody half down with it.
        extra = tts_delta.pop("params", None)
        if isinstance(extra, dict):
            for key, value in extra.items():
                tts_delta.setdefault(key, value)
        # language is an enum on Settings — map if present as string.
        if "language" in tts_delta and isinstance(tts_delta["language"], str):
            tts_delta["language"] = normalize_language(tts_delta["language"])
        from agent_core.providers.factory import settings_field_names

        allowed = settings_field_names(tts_settings_cls)
        if allowed:
            unknown = sorted(set(tts_delta) - allowed)
            if unknown:
                logger.debug("live tts delta dropped unsupported keys · {}", unknown)
            tts_delta = {k: v for k, v in tts_delta.items() if k in allowed}
        if not tts_delta:
            return live
        try:
            await worker.queue_frame(TTSUpdateSettingsFrame(delta=tts_settings_cls(**tts_delta)))
        except Exception:
            logger.exception("TTSUpdateSettingsFrame failed · delta={}", tts_delta)

    return live


def _tts_catalog_warning_off_loop(voice_name: str) -> dict[str, Any] | None:
    """Stale-voice catalog read, never on the event-loop thread.

    ``build_services`` stays sync, so this cannot ``await to_thread``. A one-shot
    worker still waits, but the Postgres driver is not on the loop thread.
    """
    import db

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return db.get_tts_voice_warning(voice_name)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(db.get_tts_voice_warning, voice_name).result()


def resolve_session_tuning(
    raw: dict[str, Any] | None,
    *,
    voice_name: str | None = None,
    speed: float | None = None,
    pitch: int | None = None,
    warmth: int | None = None,
    persona_language: str | None = None,
    persona_fallback_languages: list[str] | None = None,
    out_clamps: list[dict[str, Any]] | None = None,
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

    **Language precedence — the same shape, for the same reason.** The Persona
    tab's ``language`` was read by nothing on a call: the recogniser bound
    ``AgentTuning.stt.language``, which normalisation fills with ``en-IN`` when
    absent. So picking Hindi in the Studio changed no recogniser, no synthesiser
    and no instruction, and the product reported no conflict. ``persona_language``
    now supplies the default tag when the tuning does not name one, and an
    explicit ``stt.language`` still wins — the Tuning Studio is the more specific
    surface, exactly as it is for the voice. Read from *raw* for the same reason.
    """
    from agent_core import languages
    from agent_core.tuning import apply_voice_config_overlay

    explicit = str(((raw or {}).get("tts") or {}).get("voice") or "").strip()
    if explicit and voice_name and explicit != str(voice_name).strip():
        logger.info(
            "tts voice: using tuning '{}' over prompt-studio '{}'", explicit, voice_name
        )
    explicit_lang = str(((raw or {}).get("stt") or {}).get("language") or "").strip()
    persona_tag = languages.tag_for(persona_language)
    if persona_language and persona_tag is None:
        # Not silent: an unmappable name means the recogniser keeps whatever it
        # had, and the operator has no other way to learn their choice did not
        # take. The registry is the fix, not a guess at the tag.
        logger.warning(
            "persona language '{}' is not in the language registry — "
            "leaving stt.language as configured",
            persona_language,
        )
    elif persona_tag and explicit_lang and persona_tag.lower() != explicit_lang.lower():
        logger.info(
            "stt language: using tuning '{}' over persona '{}' ({})",
            explicit_lang,
            persona_language,
            persona_tag,
        )
    tuning = apply_voice_config_overlay(
        normalize_tuning(raw, out_clamps=out_clamps),
        voice_name=None if explicit else voice_name,
        speed=speed,
        pitch=pitch,
        warmth=warmth,
    )
    if persona_tag and not explicit_lang:
        stt = tuning.setdefault("stt", {})
        stt["language"] = persona_tag
        # The Persona tab's fallbackLanguages were read by the prompt
        # (``persona_language_line``) and by nothing on the recogniser, which
        # kept normalize_tuning's ["hi-IN", "en-IN"] whatever the card said.
        # An authored list replaces that default; names the registry does not
        # know are dropped (the primary already warned above for its own case).
        authored = [
            tag
            for tag in (languages.tag_for(name) for name in (persona_fallback_languages or []))
            if tag and tag != persona_tag
        ]
        # Re-front the chosen one rather than appending: the list is a priority
        # order and a Hindi card whose first fallback is en-IN switches itself
        # back to English on the first ambiguous utterance.
        fallbacks = authored or [f for f in (stt.get("fallback_languages") or []) if f != persona_tag]
        stt["fallback_languages"] = [persona_tag, *fallbacks]
    try:
        sn = str((tuning.get("tts") or {}).get("voice") or "").strip()
        warning = _tts_catalog_warning_off_loop(sn) if sn else None
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
