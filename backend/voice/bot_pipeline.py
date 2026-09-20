"""The services and the pipeline they form -- the transport half of run_bot.

A pure move out of :mod:`voice.bot`: STT/TTS/LLM binding, the context
aggregators, KB enrichment, the recording buffer, AMD and IVR, the stage list
and the PipelineWorker. Each step reads and writes the per-call namespace that
:func:`voice.bot.run_bot` threads through its three halves.
"""

from __future__ import annotations

import os
import time
from typing import Any

from loguru import logger

from agent_core import voice_params_from_config
from voice import config as voice_config
from voice.llm_pool import KeepAliveAzureLLMService, prewarm_shared_client
from voice.recording import attach_recording_handlers
from voice.spoken_text import SpokenTextFilter
from voice.turn_probe import SpokeThisResponseProbe
from voice.tuning_apply import (
    build_llm_settings_kwargs,
    build_stt_settings,
    build_tts_settings,
    build_user_mute_strategies,
    build_user_turn_strategies,
    build_vad_params,
    resolve_session_tuning,
    text_aggregation_mode,
    user_idle_timeout,
)

# Worker-level silence backstop under the aggregator idle ladder.
_WORKER_IDLE_TIMEOUT_SECS = 180


def emit_first_token_traces(trace, *, text: str, waited_s: float | None) -> None:
    """Keep ``first.tts`` for existing greps; ``first.llm_text`` is the honest name."""
    from voice.call_trace import preview as _preview

    fields = {
        "stage": "llm_text",
        "preview": _preview(text),
        "waited_s": round(waited_s, 3) if waited_s is not None else None,
    }
    trace("first.tts", **fields)
    trace("first.llm_text", **fields)


# In-call context summarisation prompt. Pipecat's default is generic and, in
# session VS-0D653BF9C3, produced a summary asserting the account was
# unresolved while a get_account_position result saying otherwise was still in
# the same context window — and the model repeated the summary. The rules below
# are the same shape as voice/memory.py's cross-call summariser: preserve
# commitments verbatim, never conclude anything about resolution.
_CONTEXT_SUMMARY_PROMPT = (
    "Summarise this collections call so far for the agent handling the rest of "
    "it.\n"
    "PRESERVE VERBATIM: every promise-to-pay (amount and date), every dispute "
    "raised, every callback booked, every document requested, and the caller's "
    "stated constraints or preferences.\n"
    "NEVER state or imply that anything was resolved, approved, waived, "
    "closed, cleared, settled, cancelled or refunded. Never restate a balance "
    "or due amount — those are held authoritatively elsewhere in the context "
    "and your text must not compete with them.\n"
    "If a tool result appears later in the conversation than something you are "
    "summarising, the tool result wins.\n"
    "Drop one-word or garbled STT fragments — they are not facts.\n"
    "Be factual and brief. Do not add advice or next steps."
)


def _bind_providers(call: Any) -> None:
    """Tuning, the Azure deployment, the setup trace, STT/TTS/LLM through the provider binder, and usage metering."""
    runner_args = call.runner_args
    session = call.session
    bundle = call.bundle
    bot_id = call.bot_id
    sink = call.sink
    system_instruction = call.system_instruction

    from pipecat.services.azure.stt import AzureSTTService

    from voice.tts_pool import KeepAliveAzureTTSService

    import db as _db

    vparams = voice_params_from_config(
        bundle.get("voiceConfig"),
        voice=bundle.get("voice"),
        tts_voice_id=bundle.get("ttsVoiceId"),
    )
    # AgentTuning.tts owns style/rate/pitch (Tuning Studio). Prompt Studio only
    # supplies the voice name at runtime — prosody was folded into tuning at
    # publish/save via apply_voice_config_overlay.
    tuning_clamps: list = []
    tuning = resolve_session_tuning(
        bundle.get("tuning"),
        voice_name=vparams.get("voiceName"),
        # The card's language, so the recogniser listens for what the Persona
        # tab chose. An explicit AgentTuning.stt.language still wins.
        persona_language=(
            (bundle.get("persona") or {}).get("language")
            if isinstance(bundle.get("persona"), dict)
            else None
        ),
        persona_fallback_languages=(
            (bundle.get("persona") or {}).get("fallbackLanguages")
            if isinstance(bundle.get("persona"), dict)
            else None
        ),
        out_clamps=tuning_clamps,
    )
    session.extra["tuning"] = tuning
    if tuning_clamps:
        session.extra["tuning_clamp"] = tuning_clamps

    deployment = voice_config.azure_openai_voice_deployment()
    speech_key = voice_config.azure_speech_key()
    speech_region = voice_config.azure_speech_region()

    logger.info(
        "Voice bot · session={} · deployment_id={} · llm={}@{} · tts_voice={} · style={} · barge_in={}",
        session.session_id,
        session.deployment_id,
        deployment,
        voice_config.azure_openai_voice_endpoint(),
        tuning["tts"].get("voice"),
        tuning["tts"].get("style"),
        tuning["interaction"].get("barge_in"),
    )

    def _setup_trace(name: str, **fields: Any) -> None:
        from voice.call_trace import event as _trace_event
        from voice.call_trace import session_fields

        started = getattr(runner_args, "setup_started_at", None)
        _trace_event(
            name,
            **session_fields(session),
            elapsed_s=round(time.monotonic() - started, 2) if started else None,
            **fields,
        )

    # STT and TTS resolve through the provider registry, so a provider chosen in
    # the Agent Studio is the provider that speaks. Each falls back to the Azure
    # construction below when nothing is bound — see voice/provider_bind.py for
    # why an unbound slot is a default rather than an error.
    from agent_core.tuning import normalize_tuning as _normalize_tuning
    from voice import provider_bind
    from voice.tuning_apply import stt_settings_kwargs, tts_settings_kwargs

    bind_locale = str(_normalize_tuning(tuning)["stt"].get("language") or "") or None

    # Measured STT TTFB p50 ~1.18s (logs.txt). Not part of AgentTuning — network fact.
    stt, stt_prov = provider_bind.bind(
        "stt",
        tenant_id=_db.current_tenant(),
        bot_id=bot_id,
        locale=bind_locale,
        session_id=session.session_id,
        settings=stt_settings_kwargs(tuning),
        ctor={"ttfs_p99_latency": 1.15},
        fallback=lambda: AzureSTTService(
            api_key=speech_key,
            region=speech_region,
            settings=build_stt_settings(tuning),
            ttfs_p99_latency=1.15,
        ),
    )
    provider_bind.record(session, stt_prov)
    from voice.tuning_apply import language_supported

    if bind_locale and not language_supported(bind_locale):
        # The recogniser is en-IN whatever the card said. On the record, so
        # the interaction says which language actually ran; the language-
        # switch tool and the fallback list handle the rest of the call.
        stt_prov["language_substituted"] = {"requested": bind_locale, "bound": "en-IN"}
        logger.warning(
            "STT language {} unsupported · session={} · bound en-IN",
            bind_locale,
            session.session_id,
        )

    tts, tts_prov = provider_bind.bind(
        "tts",
        tenant_id=_db.current_tenant(),
        bot_id=bot_id,
        locale=bind_locale,
        session_id=session.session_id,
        settings=tts_settings_kwargs(tuning),
        ctor={
            "text_aggregation_mode": text_aggregation_mode(tuning),
            # Parentheses and markdown are unspeakable, and Azure's word-boundary
            # events skip them — which made the sequencer emit the same span twice
            # and duplicated it into the transcript. See voice/spoken_text.py.
            # Per provider: Fish reads [square brackets] as directions.
            "text_filters": lambda binding: [SpokenTextFilter.for_provider(binding.provider_id)],
        },
        fallback=lambda: KeepAliveAzureTTSService(
            api_key=speech_key,
            region=speech_region,
            settings=build_tts_settings(tuning),
            text_aggregation_mode=text_aggregation_mode(tuning),
            text_filters=[SpokenTextFilter()],
        ),
    )
    provider_bind.record(session, tts_prov)
    _setup_trace(
        "setup.providers",
        stt=(stt_prov or {}).get("provider") if isinstance(stt_prov, dict) else None,
        tts=(tts_prov or {}).get("provider") if isinstance(tts_prov, dict) else None,
    )
    llm = KeepAliveAzureLLMService(
        api_key=voice_config.azure_openai_voice_api_key(),
        endpoint=voice_config.azure_openai_voice_endpoint(),
        api_version=voice_config.azure_openai_voice_api_version(),
        settings=KeepAliveAzureLLMService.Settings(
            **build_llm_settings_kwargs(
                tuning,
                model=deployment,
                system_instruction=system_instruction,
            )
        ),
    )

    # Name the models the meter will attribute spend to. Pipecat reports a model
    # on most usage metrics, but not on all of them, and the TTS metric names the
    # service rather than the neural voice that is actually priced — so the
    # resolved config is the reliable source.
    sink.usage.configure(
        llm_model=deployment,
        tts_voice=(tuning.get("tts") or {}).get("voice"),
        stt_language=(tuning.get("stt") or {}).get("language") or "en-IN",
    )

    call._setup_trace = _setup_trace
    call.deployment = deployment
    call.llm = llm
    call.stt = stt
    call.tts = tts
    call.tuning = tuning


def _build_context(call: Any) -> None:
    """The spoke-this-response probe, the idle timeout, the LLM context and its aggregator pair."""
    runner_args = call.runner_args
    sink = call.sink
    _spawn_bg = call._spawn_bg
    _setup_trace = call._setup_trace
    tuning = call.tuning

    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMAssistantAggregatorParams,
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )
    from pipecat.utils.context.llm_context_summarization import (
        LLMAutoContextSummarizationConfig,
        LLMContextSummaryConfig,
    )



    # Interlock between the two ways of covering tool latency, and the
    # authoritative bot-turn tap — see voice/turn_probe.py. Constructed here so
    # the filler handler below can close over it.
    #
    # record_bot_turn only enqueues, so awaiting it on the pipeline task is
    # safe; the CRM write happens on the sink's own drain.
    def _on_first_tts_text(text: str) -> None:
        origin = getattr(runner_args, "setup_started_at", None)
        waited = (time.monotonic() - origin) if origin else None
        emit_first_token_traces(_setup_trace, text=text, waited_s=waited)

    spoke_probe = SpokeThisResponseProbe(
        on_bot_turn=sink.record_bot_turn,
        on_first_tts=_on_first_tts_text,
    )

    _spawn_bg(prewarm_shared_client())

    idle_timeout = user_idle_timeout(tuning)
    user_params_kwargs: dict = {
        "vad_analyzer": SileroVADAnalyzer(params=build_vad_params(tuning)),
        "user_turn_strategies": build_user_turn_strategies(tuning),
        "user_mute_strategies": build_user_mute_strategies(tuning),
        # Disabled by default: filter_incomplete_user_turns injects ✓ / ◐ into the
        # LLM context (seen in logs as assistant content '◐'). Enable via
        # VOICE_FILTER_INCOMPLETE_TURNS=1 after India-EN prompt soak tests.
        "filter_incomplete_user_turns": voice_config.voice_filter_incomplete_turns(),
        "user_turn_stop_timeout": 5.0,
        # A Flows node transition swaps the advertised tool set, and the model
        # otherwise gets no signal that its capabilities changed — it can keep
        # reaching for a tool the previous node had. This appends a developer
        # message describing the delta when LLMSetToolsFrame fires.
        #
        # Set on BOTH aggregators rather than reasoning about frame direction:
        # pipecat's _maybe_add_tool_change_messages is dedupe-safe across the
        # pair (whichever sees the frame first computes a real diff; by the time
        # the other sees it the context already reflects the new tools, so its
        # diff is empty).
        "add_tool_change_messages": voice_config.voice_tool_change_messages(),
    }
    if idle_timeout is not None:
        user_params_kwargs["user_idle_timeout"] = idle_timeout

    context = LLMContext()
    # Native auto context-summarization (docs: context-summarization).
    # Threshold must stay well above a tool-heavy collections turn: each tool
    # call adds ~3 messages. Logs (VS-0D653BF9C3) showed summarization at 12
    # mid-get_account_position, producing a false "unresolved" summary that
    # contradicted the live tool result still in context.
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(**user_params_kwargs),
        assistant_params=LLMAssistantAggregatorParams(
            add_tool_change_messages=voice_config.voice_tool_change_messages(),
            enable_auto_context_summarization=True,
            auto_context_summarization_config=LLMAutoContextSummarizationConfig(
                max_context_tokens=8000,
                max_unsummarized_messages=36,
                summary_config=LLMContextSummaryConfig(
                    target_context_tokens=4000,
                    min_messages_after_summary=6,
                    # A collections-specific prompt, for the same reason
                    # customer_memory has one: the generic summariser is what
                    # produced the VS-0D653BF9C3 contradiction. Open
                    # commitments must survive verbatim, and the summary must
                    # never editorialise about whether anything was resolved —
                    # the CRM card and live tool results are authoritative and
                    # the summary sits in the same window as both.
                    summarization_prompt=_CONTEXT_SUMMARY_PROMPT,
                ),
            ),
        ),
    )
    user_aggregator = context_aggregator.user()
    assistant_aggregator = context_aggregator.assistant()
    sink.attach_aggregators(user_aggregator, assistant_aggregator)
    _setup_trace("setup.vad")

    call.context = context
    call.context_aggregator = context_aggregator
    call.idle_timeout = idle_timeout
    call.spoke_probe = spoke_probe
    call.user_aggregator = user_aggregator


def _build_kb_and_recording(call: Any) -> None:
    """The RTVI emitter, the KB cache and processors, the bot-turn observer, the audio buffer and turn audio."""
    runner_args = call.runner_args
    session = call.session
    bundle = call.bundle
    sandbox_session = call.sandbox_session
    _setup_trace = call._setup_trace

    from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor

    from voice.rtvi_events import RtviEmitter


    from voice.kb_enrich import KbCache, KbEnrichProcessor, KbSpeculationProcessor

    # Sandbox Live is the only surface with a UI listening for domain events; a
    # PSTN call has no client to render chips, so the emitter simply stays
    # unbound there and every send() is a no-op.
    emitter = RtviEmitter()
    kb_snapshot_id = bundle.get("kbSnapshotId")
    sandbox_persona = bundle.get("sandboxPersona") if isinstance(bundle.get("sandboxPersona"), dict) else None

    # ToolState is created inside build_authored_flow below; the getter reads
    # it lazily so KB corpus scope can follow the live Flows node.
    _flow_holder: dict[str, object] = {}

    def _current_product_keys() -> list[str] | None:
        from agent_core.context import product_keys_for_node

        state = _flow_holder.get("state")
        # Explicit scope wins. product_keys_for_node keys off _PRODUCT_NODES =
        # {"gated_upsell"}; an authored graph need not have that node, so
        # without this an insurance question would be answered out of the
        # collections corpus. `None` means "no hard product filter" — let
        # kb_retrieve steer by query tokens.
        if getattr(state, "product_scope", None) == "product":
            return None
        return product_keys_for_node(getattr(state, "current_node", None))

    # One cache, two processors. The speculator sits upstream of the user
    # aggregator (which swallows InterimTranscriptionFrame) and starts retrieval
    # while the caller is still talking; the injector stays where it was and
    # resolves through the cache with a bounded wait.
    kb_cache = KbCache(
        interaction_id_getter=lambda: session.interaction_id,
        product_keys_getter=_current_product_keys,
        kb_snapshot_id=kb_snapshot_id,
    )
    kb_speculator = KbSpeculationProcessor(kb_cache)
    kb_enrich = KbEnrichProcessor(kb_cache, emitter=emitter)

    # Constructed here rather than with the other observers further down: the
    # idle handler below closes over it, and a closure that resolves at call
    # time would only fail once, on a real call, in the branch nobody tests.
    from voice.bot_turn_state import BotTurnStateObserver

    def _on_first_speech() -> None:
        session.extra["first_bot_speech_done"] = True
        origin = getattr(runner_args, "setup_started_at", None) or bot_turn_state._call_started_at
        waited = (time.monotonic() - origin) if origin else None
        _setup_trace("first.speech", waited_s=round(waited, 3) if waited is not None else None)

    bot_turn_state = BotTurnStateObserver(on_first_speech=_on_first_speech)

    # Manual start after disclosure (plan §9.5) — never auto_start.
    # Optional chunked buffer for long calls: VOICE_AUDIO_BUFFER_SECS=30
    # Turn audio feeds Inspector playback (VOICE_TURN_AUDIO=1, default on for sandbox).
    _buf_secs = (os.getenv("VOICE_AUDIO_BUFFER_SECS") or "").strip()
    _turn_audio = voice_config.voice_turn_audio(sandbox=bool(sandbox_session))
    _audiobuf_kwargs: dict[str, Any] = {
        "num_channels": 2,
        "auto_start_recording": False,
        "enable_turn_audio": _turn_audio,
    }
    if _buf_secs:
        try:
            _audiobuf_kwargs["buffer_size"] = max(1, int(float(_buf_secs) * 16000))
        except ValueError:
            pass
    audiobuffer = AudioBufferProcessor(**_audiobuf_kwargs)
    attach_recording_handlers(
        audiobuffer,
        session,
        on_uploaded=lambda row: session.extra.update({"audio_media_id": row.get("mediaId")}),
    )

    if _turn_audio:

        async def _emit_turn_audio(kind: str, audio: bytes, sample_rate: int, _num_channels: int) -> None:
            import base64

            if not audio or len(audio) < 64:
                return
            # Cap payload for RTVI (~250ms @ 16k mono int16 ≈ 8KB).
            max_bytes = 16_000
            clip = bytes(audio[-max_bytes:]) if len(audio) > max_bytes else bytes(audio)
            try:
                await emitter.send(
                    "turn.audio",
                    {
                        "speaker": kind,
                        "sampleRate": int(sample_rate or 16000),
                        "encoding": "pcm_s16le",
                        "pcmBase64": base64.b64encode(clip).decode("ascii"),
                        "bytes": len(clip),
                    },
                )
            except Exception:
                logger.debug("turn.audio emit failed", exc_info=True)

        # First positional is the AudioBufferProcessor itself — pipecat's
        # _call_event_handler prepends it, exactly as the on_audio_data /
        # on_track_audio_data handlers in voice/recording.py already expect.
        # Declaring only (audio, sample_rate, num_channels) raised
        # "takes 3 positional arguments but 4 were given" on *every* turn, and
        # because pipecat swallows handler exceptions the only symptom was that
        # per-turn audio silently never reached the Inspector.
        @audiobuffer.event_handler("on_user_turn_audio_data")
        async def _on_user_turn_audio(buffer, audio, sample_rate, num_channels):  # noqa: ANN001
            await _emit_turn_audio("user", audio, sample_rate, num_channels)

        @audiobuffer.event_handler("on_bot_turn_audio_data")
        async def _on_bot_turn_audio(buffer, audio, sample_rate, num_channels):  # noqa: ANN001
            await _emit_turn_audio("bot", audio, sample_rate, num_channels)

    async def _start_recording() -> None:
        await audiobuffer.start_recording()
        logger.info("Recording started · session={}", session.session_id)

    call._flow_holder = _flow_holder
    call._start_recording = _start_recording
    call.audiobuffer = audiobuffer
    call.bot_turn_state = bot_turn_state
    call.emitter = emitter
    call.kb_cache = kb_cache
    call.kb_enrich = kb_enrich
    call.kb_snapshot_id = kb_snapshot_id
    call.kb_speculator = kb_speculator
    call.sandbox_persona = sandbox_persona


def build_services(call) -> None:
    """Tuning, STT/TTS/LLM, aggregators, KB, turn-state observer, recording."""
    _bind_providers(call)
    _build_context(call)
    _build_kb_and_recording(call)


async def build_pipeline(call) -> None:
    """AMD, IVR, the ordered stages, observers and the PipelineWorker."""
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.processors.frameworks.rtvi import (
        RTVIFunctionCallReportLevel,
        RTVIObserverParams,
    )

    transport = call.transport
    session = call.session
    bundle = call.bundle
    sink = call.sink
    is_twilio = call.is_twilio
    sandbox_session = call.sandbox_session
    tuning = call.tuning
    deployment = call.deployment
    _setup_trace = call._setup_trace
    stt = call.stt
    tts = call.tts
    llm = call.llm
    spoke_probe = call.spoke_probe
    context_aggregator = call.context_aggregator
    emitter = call.emitter
    kb_speculator = call.kb_speculator
    kb_enrich = call.kb_enrich
    bot_turn_state = call.bot_turn_state
    audiobuffer = call.audiobuffer

    # Outbound Twilio only — VoicemailDetector between STT and user agg, gate after TTS.
    voicemail_detector = None
    try:
        from voice import amd
        from voice.amd import attach_voicemail_handlers, should_enable_amd

        if should_enable_amd(session.extra, is_twilio=is_twilio):

            classifier_llm = KeepAliveAzureLLMService(
                api_key=voice_config.azure_openai_voice_api_key(),
                endpoint=voice_config.azure_openai_voice_endpoint(),
                api_version=voice_config.azure_openai_voice_api_version(),
                settings=KeepAliveAzureLLMService.Settings(
                    **build_llm_settings_kwargs(
                        tuning,
                        model=deployment,
                        system_instruction=(
                            "Classify whether the audio is a live human or a voicemail greeting. "
                            "Reply with the detector's required tokens only."
                        ),
                    )
                ),
            )
            # Not `VoicemailDetector(...)` directly: the flow's context updates
            # would reach the classifier branch and get read as evidence. See
            # `amd._ClassifierContextGuard`.
            voicemail_detector = amd.build_voicemail_detector(llm=classifier_llm, session=session)
            logger.info("AMD VoicemailDetector enabled · session={}", session.session_id)
            _setup_trace("setup.amd", enabled=True)
        else:
            if amd.is_demo_call(session.extra):
                from voice.call_trace import event as _trace

                _trace(
                    "amd.voicemail_skipped",
                    session=session.session_id,
                    reason="demo",
                    attempt=session.extra.get("attempt_id"),
                    objective=session.extra.get("objective"),
                )
            _setup_trace("setup.amd", enabled=False)
    except Exception:
        logger.exception("AMD setup failed — continuing without voicemail detection")
        voicemail_detector = None

    # Telephony only — partner-IVR traversal on outbound, keypad capture inbound
    # (voice plan §2.10). The navigator wraps `llm`, so it takes that stage's
    # slot and everything downstream (Flows, RTVI, CrmSink) is untouched.
    ivr_navigator = None
    dtmf_aggregator = None
    try:
        from voice import ivr as ivr_mod

        if ivr_mod.should_enable_ivr(session.extra, is_twilio=is_twilio):
            ivr_navigator = ivr_mod.build_ivr_navigator(
                llm=llm, session_extra=session.extra
            )
            if ivr_navigator is not None:
                logger.info("IVR navigation enabled · session={}", session.session_id)
        if ivr_mod.should_enable_dtmf_input(is_twilio=is_twilio):
            dtmf_aggregator = ivr_mod.build_dtmf_aggregator()
            if dtmf_aggregator is not None:
                logger.info("DTMF keypad input enabled · session={}", session.session_id)
    except Exception:
        logger.exception("IVR setup failed — continuing without IVR/DTMF")
        ivr_navigator = None
        dtmf_aggregator = None

    pipeline_stages: list[Any] = [transport.input(), stt]
    if dtmf_aggregator is not None:
        # After STT so aggregated digits join the same text stream the user
        # aggregator consumes, and before it so they land in the right turn.
        pipeline_stages.append(dtmf_aggregator)
    if voicemail_detector is not None:
        pipeline_stages.append(voicemail_detector.detector())
    pipeline_stages.extend(
        [
            # Must precede the user aggregator: LLMUserAggregator consumes
            # InterimTranscriptionFrame and does not push it downstream, so
            # nothing after it can start retrieval before the turn closes.
            # Placed after the voicemail detector so an answering-machine
            # greeting never burns an embed.
            kb_speculator,
            context_aggregator.user(),
            kb_enrich,
            ivr_navigator if ivr_navigator is not None else llm,
            # Between llm and tts: sees the response's text frames before they
            # are spoken, which is what the filler interlock needs.
            spoke_probe,
            tts,
        ]
    )
    if voicemail_detector is not None:
        pipeline_stages.append(voicemail_detector.gate())
    pipeline_stages.extend(
        [
            transport.output(),
            audiobuffer,
            context_aggregator.assistant(),
        ]
    )
    pipeline = Pipeline(pipeline_stages)
    _setup_trace("setup.pipeline", stages=len(pipeline_stages))

    observers = []
    metrics_obs = sink.build_observer()
    if metrics_obs is not None:
        observers.append(metrics_obs)

    # Built above, next to the idle state it guards.
    observers.append(bot_turn_state)

    # Per-service latency attribution. Prerequisite (enable_metrics=True) is
    # already set on PipelineParams below. The observer is passive — it only
    # reads pushed frames — so the handlers here must stay off the audio path:
    # the sink call is in-memory and the RTVI emit is fire-and-forget.
    if voice_config.voice_latency_observer():
        try:
            from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver

            from voice.tools import spawn_session_task

            latency_obs = UserBotLatencyObserver()

            @latency_obs.event_handler("on_latency_breakdown")
            async def _on_latency_breakdown(_obs, breakdown):  # noqa: ANN001
                try:
                    sink.record_latency_breakdown(breakdown)
                    spawn_session_task(
                        session.session_id,
                        emitter.send(
                            "latency.breakdown",
                            sink.latency_breakdown_payload(breakdown),
                        ),
                    )
                except Exception:
                    logger.exception("latency breakdown handler failed")

            @latency_obs.event_handler("on_latency_measured")
            async def _on_latency_measured(_obs, latency_seconds):  # noqa: ANN001
                try:
                    sink.record_user_bot_latency_ms(float(latency_seconds) * 1000.0)
                except Exception:
                    logger.debug("latency measure handler failed", exc_info=True)

            @latency_obs.event_handler("on_first_bot_speech_latency")
            async def _on_first_bot_speech(_obs, latency_seconds):  # noqa: ANN001
                # loguru formats with {}, not printf — the %s version printed
                # the format string literally and dropped both values.
                logger.info(
                    "first bot speech · session={} · {:.3f}s",
                    session.session_id,
                    float(latency_seconds),
                )
                session.extra["first_bot_speech_done"] = True
                # first.tts / first.speech are emitted by BotTurnStateObserver
                # so they still fire when this observer is disabled.

            observers.append(latency_obs)
        except Exception:
            logger.exception("latency observer unavailable — continuing without it")

    if voice_config.voice_startup_timing():
        try:
            from pipecat.observers.startup_timing_observer import StartupTimingObserver

            startup_obs = StartupTimingObserver()

            @startup_obs.event_handler("on_startup_timing_report")
            async def _on_startup_timing(_obs, report):  # noqa: ANN001
                logger.info("startup timing · session={} · {}", session.session_id, report)

            @startup_obs.event_handler("on_transport_timing_report")
            async def _on_transport_timing(_obs, report):  # noqa: ANN001
                logger.info("transport timing · session={} · {}", session.session_id, report)

            observers.append(startup_obs)
        except Exception:
            logger.exception("startup timing observer unavailable")

    # Sandbox gets FULL function-call reporting so the Inspector can show tool
    # args and results. A production call reports NAME only (voice plan §2.2 /
    # docs: RTVIFunctionCallReportLevel).
    #
    # This is a *map* of function name → level with "*" as the default, not a
    # bare level: RTVIObserver looks the function up with `levels.get("*", …)`,
    # so passing the enum itself raised AttributeError inside the observer's
    # task on the first tool call of every call, and no llm-function-call-*
    # event ever reached the client.
    #
    # verify_identity is pinned one notch tighter than the default in both
    # environments — its arguments are the caller's mobile digits, which must
    # not be shipped to a browser even in a rehearsal.
    report_levels = (
        {
            "*": RTVIFunctionCallReportLevel.FULL,
            "verify_identity": RTVIFunctionCallReportLevel.NAME,
        }
        if sandbox_session
        else {
            "*": RTVIFunctionCallReportLevel.NAME,
            "verify_identity": RTVIFunctionCallReportLevel.NONE,
        }
    )

    # cancel_on_idle_timeout=False so we can speak a farewell first
    # (docs: pipeline-idle-detection / pipeline-termination).
    # Twilio Media Streams are 8 kHz mono — set sample rates to avoid resample lag.
    pipeline_kwargs: dict[str, Any] = {
        "enable_metrics": True,
        "enable_usage_metrics": True,
    }
    if is_twilio:
        pipeline_kwargs["audio_in_sample_rate"] = 8000
        pipeline_kwargs["audio_out_sample_rate"] = 8000
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(**pipeline_kwargs),
        observers=observers or None,
        idle_timeout_secs=_WORKER_IDLE_TIMEOUT_SECS,
        cancel_on_idle_timeout=False,
        rtvi_observer_params=RTVIObserverParams(
            function_call_report_level=report_levels,
        ),
    )

    if voicemail_detector is not None:
        try:
            await attach_voicemail_handlers(
                voicemail_detector=voicemail_detector,
                session=session,
                sink=sink,
                worker=worker,
                # Deployment persona (the bot's own identity), not sandboxPersona
                # (the simulated caller) — the voicemail says who is calling.
                persona=bundle.get("persona") if isinstance(bundle.get("persona"), dict) else None,
                tuning=tuning,
                bot_turn_state=bot_turn_state,
            )
        except Exception:
            logger.exception("AMD handlers failed")

    if ivr_navigator is not None:
        try:
            from voice.ivr import attach_ivr_handlers

            await attach_ivr_handlers(
                navigator=ivr_navigator,
                session=session,
                sink=sink,
                worker=worker,
                emitter=emitter,
            )
        except Exception:
            logger.exception("IVR handlers failed")

    call.voicemail_detector = voicemail_detector
    call.ivr_navigator = ivr_navigator
    call.worker = worker
