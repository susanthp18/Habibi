"""Production voice bot — Flows + CRM tools + persistence + recording (V3).

Shared brain from agent_core. Pipeline constructed from AgentTuning (§4.7).
Collections script via Pipecat Flows. Persistence via CrmSink (off audio path).
Audio after disclosure only.

Run:
  $env:PYTHONIOENCODING='utf-8'
  .\\.venv\\Scripts\\python.exe -m voice.bot
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import os

os.environ.setdefault("DB_PROCESS_ROLE", "voice")

from loguru import logger

from agent_core import default_context, default_tuning, load_active_bundle, voice_params_from_config
from prompt_render import render_prompt
from voice import config as voice_config
from voice.crm_sink import CrmSink, bind_session_start
from voice.flows import build_collections_flow
from voice.latency import KeepAliveAzureLLMService, prewarm_llm_connection
from voice.natural import build_voice_system_prompt, filler_for_function_names
from voice.recording import attach_recording_handlers
from voice.session import VoiceSession
from voice.tuning_apply import (
    apply_live_tuning_delta,
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


def _system_instruction_from_bundle(bundle: dict, context: dict | None = None) -> str:
    """Lean voice system prompt — authored prompt + guardrails + voice rules only."""
    ctx = default_context(context)
    rendered = render_prompt(bundle.get("prompt") or "", ctx)
    # Call-start defaults are XXXX / 0 / empty due_date. Leaving those lines in
    # the system prompt makes the model speak them literally (seen in logs:
    # "account XXXX"). Strip unresolved CRM placeholders until real values exist.
    rendered = _strip_unresolved_crm_placeholders(rendered)
    return build_voice_system_prompt(rendered, bundle.get("guardrails") or {})


def _strip_unresolved_crm_placeholders(text: str) -> str:
    kept: list[str] = []
    for line in (text or "").splitlines():
        low = line.lower()
        if "xxxx" in low:
            continue
        if "overdue amount of 0" in low or "overdue amount of {overdue_amount}" in low:
            continue
        if "due on ." in low or low.rstrip().endswith("due on"):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


_TUNE_MSG_TYPES = frozenset({"tune", "agent_tuning", "tuning", "tuning_delta"})


def _delta_from_payload(data) -> dict | None:
    """Normalize a tune payload into an AgentTuning delta dict."""
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("tuning"), dict):
        return data["tuning"]
    return data


def _extract_tune_delta(message) -> dict | None:
    """Accept Studio deltas from transport app-message or RTVI client-message shapes.

    Wire formats handled:
    - Bare AgentTuning / ``{tuning: {...}}``
    - ``{type: "tuning_delta"|"tune"|..., data|payload: {...}}``
    - RTVI client-message: ``{type: "client-message", data: {t: "tuning_delta", d: {...}}}``
    - ``RTVIClientMessageFrame`` / ClientMessage objects (``.type`` + ``.data``)
    """
    if message is None:
        return None
    if isinstance(message, dict):
        if isinstance(message.get("tuning"), dict):
            return message["tuning"]

        outer = message.get("type")
        data = message.get("data") if "data" in message else message.get("payload")

        # RTVI wire: sendClientMessage("tuning_delta", delta) →
        # {type: "client-message", data: {t: "tuning_delta", d: delta}}
        if outer == "client-message" and isinstance(data, dict):
            inner_t = data.get("t") or data.get("type")
            inner_d = data["d"] if "d" in data else data.get("data")
            if inner_t in _TUNE_MSG_TYPES:
                return _delta_from_payload(inner_d)
            return None

        if outer in _TUNE_MSG_TYPES:
            return _delta_from_payload(data if isinstance(data, dict) else {})

        # Bare AgentTuning sections
        if any(k in message for k in ("llm", "tts", "vad", "turn", "interaction", "stt")):
            return message
        return None

    # RTVI ClientMessage / RTVIClientMessageFrame
    msg_type = getattr(message, "type", None) or getattr(message, "msg_type", None)
    data = getattr(message, "data", None)
    if msg_type in _TUNE_MSG_TYPES:
        return _delta_from_payload(data)
    return None


# Collections voice calls: hard cap then spoken sign-off (docs: pipeline-termination).
_MAX_CALL_DURATION_SECS = 10 * 60
# Worker-level silence backstop under the aggregator idle ladder.
_WORKER_IDLE_TIMEOUT_SECS = 180

# Strong refs for fire-and-forget tasks — the loop only holds a weak ref, so
# without this a prewarm task can be GC'd mid-flight and silently cancelled.
_BG_TASKS: set[asyncio.Task] = set()


def _spawn_bg(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task


async def run_bot(transport, runner_args) -> None:
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.flows import FlowManager
    from pipecat.flows.exceptions import (
        ActionError,
        FlowError,
        FlowInitializationError,
        FlowTransitionError,
        InvalidFunctionError,
    )
    from pipecat.frames.frames import EndFrame, EndWorkerFrame, LLMMessagesAppendFrame, TTSSpeakFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMAssistantAggregatorParams,
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )
    from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
    from pipecat.processors.frameworks.rtvi import (
        RTVIFunctionCallReportLevel,
        RTVIObserverParams,
    )
    from pipecat.services.azure.stt import AzureSTTService
    from pipecat.utils.context.llm_context_summarization import (
        LLMAutoContextSummarizationConfig,
        LLMContextSummaryConfig,
    )
    from pipecat.workers.runner import WorkerRunner

    from voice.rtvi_events import RtviEmitter
    from voice.tts_pool import KeepAliveAzureTTSService

    import db as _db

    # Prefer Sandbox Live session config (written by POST /voice/sandbox/start).
    # Session id arrives via SmallWebRTC request_data → runner_args.body (or
    # runner_args.session_id). Never use a shared "latest" pointer — that races.
    sandbox_session = None
    _vsb = None
    call_data = getattr(runner_args, "call_data", None)
    transport_type = (
        getattr(runner_args, "transport_type", None)
        or getattr(call_data, "provider", None)
        or ""
    )
    if not transport_type and call_data is not None:
        transport_type = "twilio"
    is_twilio = str(transport_type).lower() in {"twilio", "telnyx", "plivo", "exotel"}
    try:
        import voice_sandbox as _vsb

        body = getattr(runner_args, "body", None)
        sid = None
        if isinstance(body, dict):
            sid = body.get("sessionId") or body.get("session_id")
        if not sid:
            sid = getattr(runner_args, "session_id", None)
        if sid:
            sandbox_session = _vsb.read_session(str(sid))
            if not sandbox_session:
                logger.warning("voice sandbox session not found: %s", sid)
        elif not is_twilio:
            logger.warning(
                "No sessionId in runner_args.body — sandbox Live config unavailable"
            )
    except Exception:
        logger.exception("failed to load voice sandbox session")
        sandbox_session = None
        _vsb = None

    try:
        if sandbox_session and sandbox_session.get("promptVersionId"):
            from agent_core.deployment import resolve_prompt_bundle

            bundle = resolve_prompt_bundle(
                prompt_version_id=sandbox_session["promptVersionId"],
                environment="sandbox",
                fallback_environments=("production",),
            )
            # Prefer version tuning when present; session tuning overlays.
            ver_tuning = (bundle.get("promptVersion") or {}).get("tuning")
            if isinstance(ver_tuning, dict) and ver_tuning:
                from agent_core.tuning import normalize_tuning

                bundle["tuning"] = normalize_tuning(ver_tuning)
            if sandbox_session.get("tuning"):
                from agent_core.tuning import merge_tuning_delta

                bundle["tuning"] = merge_tuning_delta(
                    bundle.get("tuning") or default_tuning(),
                    sandbox_session["tuning"],
                )
            if sandbox_session.get("kbSnapshotId"):
                bundle["kbSnapshotId"] = sandbox_session["kbSnapshotId"]
        else:
            bundle = load_active_bundle("production", fallback_environments=("sandbox",))
    except KeyError:
        logger.warning("No active deployment — using minimal fallback instruction")
        bundle = {
            "deploymentId": None,
            "prompt": "You are Priya, an HDFC collections voice agent. Be brief.",
            "persona": {},
            "guardrails": {},
            "voice": {},
            "voiceConfig": {},
            "ttsVoiceId": None,
            "tuning": default_tuning(),
        }

    if sandbox_session and isinstance(sandbox_session.get("persona"), dict):
        bundle = {**bundle, "sandboxPersona": sandbox_session["persona"]}

    bot_id = _db.DEFAULT_BOT_ID
    # Sandbox Live: reuse the VS- id minted by voice_sandbox.start_voice_sandbox
    # so the session file, voice_sessions row, and CRM interaction join on one key.
    # Non-sandbox transports keep a fresh uuid4 id.
    if sandbox_session and sandbox_session.get("sessionId"):
        session_id = str(sandbox_session["sessionId"])
    else:
        session_id = f"VS-{uuid.uuid4().hex[:10].upper()}"
    transport_name = "twilio" if is_twilio else "smallwebrtc"
    session = VoiceSession(
        session_id=session_id,
        deployment_id=bundle.get("deploymentId"),
        transport=transport_name,
    )
    # Twilio CallSid + caller ANI for warm transfer / CRM prefill.
    if call_data is not None:
        session.extra["call_sid"] = getattr(call_data, "call_id", None) or (
            call_data.get("call_id") if isinstance(call_data, dict) else None
        )
        session.extra["from_number"] = getattr(call_data, "from_number", None) or (
            call_data.get("from") if isinstance(call_data, dict) else None
        )
        session.extra["to_number"] = getattr(call_data, "to_number", None) or (
            call_data.get("to") if isinstance(call_data, dict) else None
        )
        body_params = getattr(call_data, "body", None) or {}
        if isinstance(body_params, dict):
            session.extra["twilio_params"] = body_params
            session.extra["call_sid"] = session.extra.get("call_sid") or body_params.get(
                "call_sid"
            )
            session.extra["from_number"] = session.extra.get("from_number") or body_params.get(
                "from"
            )
    if is_twilio and session.extra.get("from_number"):
        try:
            from voice import twilio_ops

            matched = twilio_ops.lookup_customer_for_caller(session.extra["from_number"])
            if matched:
                session.extra["pstn_customer"] = matched
                logger.info(
                    "Twilio caller matched customer=%s dpd=%s",
                    matched.get("customerId"),
                    matched.get("dpd"),
                )
        except Exception:
            logger.exception("Twilio caller lookup failed")
    sink = CrmSink(session, guardrails=bundle.get("guardrails") or {})
    system_instruction = _system_instruction_from_bundle(bundle)
    vparams = voice_params_from_config(
        bundle.get("voiceConfig"),
        voice=bundle.get("voice"),
        tts_voice_id=bundle.get("ttsVoiceId"),
    )
    # AgentTuning.tts owns style/rate/pitch (Tuning Studio). Prompt Studio only
    # supplies the voice name at runtime — prosody was folded into tuning at
    # publish/save via apply_voice_config_overlay.
    tuning = resolve_session_tuning(
        bundle.get("tuning"),
        voice_name=vparams.get("voiceName"),
    )
    session.extra["tuning"] = tuning

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

    # Measured STT TTFB p50 ~1.18s (logs.txt). Not part of AgentTuning — network fact.
    stt = AzureSTTService(
        api_key=speech_key,
        region=speech_region,
        settings=build_stt_settings(tuning),
        ttfs_p99_latency=1.15,
    )

    tts = KeepAliveAzureTTSService(
        api_key=speech_key,
        region=speech_region,
        settings=build_tts_settings(tuning),
        text_aggregation_mode=text_aggregation_mode(tuning),
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

    # Mask CRM/tool latency with a short spoken filler (plan §6).
    @llm.event_handler("on_function_calls_started")
    async def _on_function_calls_started(service, function_calls):
        names = []
        for call in function_calls or []:
            names.append(
                getattr(call, "function_name", None)
                or getattr(call, "name", None)
                or str(call)
            )
        phrase = filler_for_function_names([str(n) for n in names if n])
        if not phrase:
            return
        try:
            await tts.queue_frame(TTSSpeakFrame(phrase, append_to_context=False))
        except TypeError:
            await tts.queue_frame(TTSSpeakFrame(phrase))
        except Exception:
            logger.exception("filler TTS failed")

    _spawn_bg(prewarm_llm_connection())

    idle_timeout = user_idle_timeout(tuning)
    user_params_kwargs: dict = {
        "vad_analyzer": SileroVADAnalyzer(params=build_vad_params(tuning)),
        "user_turn_strategies": build_user_turn_strategies(tuning),
        "user_mute_strategies": build_user_mute_strategies(tuning),
        # Disabled by default: filter_incomplete_user_turns injects ✓ / ◐ into the
        # LLM context (seen in logs as assistant content '◐'). Enable via
        # VOICE_FILTER_INCOMPLETE_TURNS=1 after India-EN prompt soak tests.
        "filter_incomplete_user_turns": (
            (os.getenv("VOICE_FILTER_INCOMPLETE_TURNS") or "").strip().lower()
            in {"1", "true", "yes", "on"}
        ),
        "user_turn_stop_timeout": 5.0,
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
            enable_auto_context_summarization=True,
            auto_context_summarization_config=LLMAutoContextSummarizationConfig(
                max_context_tokens=8000,
                max_unsummarized_messages=36,
                summary_config=LLMContextSummaryConfig(
                    target_context_tokens=4000,
                    min_messages_after_summary=6,
                ),
            ),
        ),
    )
    user_aggregator = context_aggregator.user()
    assistant_aggregator = context_aggregator.assistant()
    sink.attach_aggregators(user_aggregator, assistant_aggregator)

    from voice.kb_enrich import KbEnrichProcessor

    # Sandbox Live is the only surface with a UI listening for domain events; a
    # PSTN call has no client to render chips, so the emitter simply stays
    # unbound there and every send() is a no-op.
    emitter = RtviEmitter()
    kb_snapshot_id = bundle.get("kbSnapshotId")
    sandbox_persona = bundle.get("sandboxPersona") if isinstance(bundle.get("sandboxPersona"), dict) else None

    async def _inject_developer(messages: list[dict]) -> None:
        """Append developer messages (CRM card, persona, deltas) to the context.

        run_llm=False: these are facts for the *next* turn, not a prompt to
        speak now. Letting them trigger inference would make the bot narrate
        its own CRM lookup.
        """
        if not messages:
            return
        await user_aggregator.push_frame(LLMMessagesAppendFrame(messages, run_llm=False))

    # ToolState is created inside build_collections_flow below; the getter reads
    # it lazily so KB corpus scope can follow the live Flows node.
    _flow_holder: dict[str, object] = {}

    def _current_product_keys() -> list[str] | None:
        from agent_core.context import product_keys_for_node

        state = _flow_holder.get("state")
        return product_keys_for_node(getattr(state, "current_node", None))

    kb_enrich = KbEnrichProcessor(
        interaction_id_getter=lambda: session.interaction_id,
        product_keys_getter=_current_product_keys,
        kb_snapshot_id=kb_snapshot_id,
        emitter=emitter,
    )

    # Silence ladder (§6) — escalate nudge → direct → close.
    idle_strikes = 0
    idle_ladder = list(tuning["interaction"].get("idle_ladder") or ["nudge", "direct", "close"])
    # Single-flight end: idle ladder / worker idle / max-duration must not stack
    # with each other or with Flows end_conversation (feedback #4).
    ending = False
    duration_task: asyncio.Task | None = None

    def _claim_end(reason: str) -> bool:
        nonlocal ending
        if ending or session.extra.get("ending"):
            logger.info(
                "Skip duplicate end · reason={} · session={}",
                reason,
                session.session_id,
            )
            return False
        ending = True
        session.extra["ending"] = True
        if duration_task is not None and not duration_task.done():
            duration_task.cancel()
        return True

    @user_aggregator.event_handler("on_user_turn_idle")
    async def on_user_turn_idle(aggregator):
        nonlocal idle_strikes
        if ending or session.extra.get("ending"):
            return
        idle_strikes += 1
        step_idx = min(idle_strikes - 1, len(idle_ladder) - 1)
        step = idle_ladder[step_idx]
        logger.info(
            "User idle · session={} · strike={} · step={}",
            session.session_id,
            idle_strikes,
            step,
        )
        try:
            if hasattr(sink, "enqueue_alert"):
                await sink.enqueue_alert("silence", f"idle_strike_{idle_strikes}")
        except Exception:
            pass
        await emitter.lifecycle(phase="idle", reason=f"{step}:{idle_strikes}")

        if step == "nudge":
            msg = {
                "role": "developer",
                "content": "The user has gone quiet. Politely and briefly ask if they're still there.",
            }
            await aggregator.push_frame(LLMMessagesAppendFrame([msg], run_llm=True))
            return
        if step == "direct":
            msg = {
                "role": "developer",
                "content": (
                    "The user is still silent. Ask one short direct question to continue "
                    "(e.g. can they hear you / still on the line)."
                ),
            }
            await aggregator.push_frame(LLMMessagesAppendFrame([msg], run_llm=True))
            return
        # close — polite goodbye then end the worker.
        if not _claim_end("idle_ladder_close"):
            return
        try:
            await tts.queue_frame(
                TTSSpeakFrame(
                    "I'll let you go for now. Feel free to call us back anytime. Goodbye.",
                    append_to_context=False,
                )
            )
        except TypeError:
            await tts.queue_frame(
                TTSSpeakFrame("I'll let you go for now. Feel free to call us back anytime. Goodbye.")
            )
        except Exception:
            logger.exception("idle close TTS failed")
        await worker.queue_frame(EndWorkerFrame())

    # Manual start after disclosure (plan §9.5) — never auto_start.
    # Optional chunked buffer for long calls: VOICE_AUDIO_BUFFER_SECS=30
    # Turn audio feeds Inspector playback (VOICE_TURN_AUDIO=1, default on for sandbox).
    _buf_secs = (os.getenv("VOICE_AUDIO_BUFFER_SECS") or "").strip()
    _turn_audio = (os.getenv("VOICE_TURN_AUDIO") or ("1" if sandbox_session else "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
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

        @audiobuffer.event_handler("on_user_turn_audio_data")
        async def _on_user_turn_audio(buffer, sample_rate, num_channels):
            await _emit_turn_audio("user", buffer, sample_rate, num_channels)

        @audiobuffer.event_handler("on_bot_turn_audio_data")
        async def _on_bot_turn_audio(buffer, sample_rate, num_channels):
            await _emit_turn_audio("bot", buffer, sample_rate, num_channels)

    async def _start_recording() -> None:
        await audiobuffer.start_recording()
        logger.info("Recording started · session={}", session.session_id)

    _tool_state, _tools, initial_node, global_fns = build_collections_flow(
        session,
        role_message=system_instruction,
        bot_id=bot_id,
        start_recording=_start_recording,
        emitter=emitter,
        kb_snapshot_id=kb_snapshot_id,
        inject_developer=_inject_developer,
        persona=sandbox_persona,
        channel="sandbox_live" if sandbox_session else "voice",
        on_kb_tool_used=kb_enrich.suppress,
        sink=sink,
    )
    _flow_holder["state"] = _tool_state

    # Outbound Twilio only — VoicemailDetector between STT and user agg, gate after TTS.
    voicemail_detector = None
    try:
        from voice.amd import attach_voicemail_handlers, should_enable_amd

        if should_enable_amd(session.extra, is_twilio=is_twilio):
            from pipecat.extensions.voicemail.voicemail_detector import VoicemailDetector

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
            voicemail_detector = VoicemailDetector(llm=classifier_llm)
            logger.info("AMD VoicemailDetector enabled · session={}", session.session_id)
    except Exception:
        logger.exception("AMD setup failed — continuing without voicemail detection")
        voicemail_detector = None

    pipeline_stages: list[Any] = [transport.input(), stt]
    if voicemail_detector is not None:
        pipeline_stages.append(voicemail_detector.detector())
    pipeline_stages.extend(
        [
            context_aggregator.user(),
            kb_enrich,
            llm,
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

    observers = []
    metrics_obs = sink.build_observer()
    if metrics_obs is not None:
        observers.append(metrics_obs)

    # Sandbox gets FULL function-call reporting so the Inspector can show tool
    # args and results. A production call reports NAME only: verify_identity
    # args are the caller's mobile digits and must not be shipped to a client
    # (voice plan §2.2 / docs: RTVIFunctionCallReportLevel).
    report_level = (
        RTVIFunctionCallReportLevel.FULL
        if sandbox_session
        else RTVIFunctionCallReportLevel.NAME
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
            function_call_report_level=report_level,
        ),
    )

    if voicemail_detector is not None:
        try:
            from voice.amd import attach_voicemail_handlers

            await attach_voicemail_handlers(
                voicemail_detector=voicemail_detector,
                session=session,
                sink=sink,
                worker=worker,
            )
        except Exception:
            logger.exception("AMD handlers failed")

    flow_manager = FlowManager(
        llm=llm,
        context_aggregator=context_aggregator,
        worker=worker,
        transport=transport,
        global_functions=global_fns,
    )

    async def _summarize_context_action(action: dict) -> None:
        """Collapse history on a topic hop (voice plan §2.15).

        Uses the native summarizer frame rather than Flows' deprecated
        RESET_WITH_SUMMARY context strategy. Best-effort: a failed summarize
        must leave the call running on the full context, not break the hop.
        """
        from pipecat.frames.frames import LLMSummarizeContextFrame

        try:
            await worker.queue_frame(LLMSummarizeContextFrame())
            logger.debug("Topic-hop summarize queued · session={}", session.session_id)
        except Exception:
            logger.exception("summarize_context action failed (non-fatal)")

    try:
        flow_manager.register_action("summarize_context", _summarize_context_action)
    except Exception:
        logger.warning("could not register summarize_context action", exc_info=True)

    async def _mesh_activate_insurance_action(action: dict) -> None:
        try:
            from voice import mesh_bus

            role = await mesh_bus.activate_and_publish(
                "insurance", session_id=session.session_id
            )
            logger.info("mesh role after upsell hop → {} · session={}", role, session.session_id)
        except Exception:
            logger.exception("mesh_activate_insurance failed (non-fatal)")

    try:
        flow_manager.register_action(
            "mesh_activate_insurance", _mesh_activate_insurance_action
        )
    except Exception:
        logger.warning("could not register mesh_activate_insurance", exc_info=True)

    @worker.event_handler("on_idle_timeout")
    async def on_worker_idle_timeout(worker_ref):
        if not _claim_end("worker_idle"):
            return
        logger.info("Worker idle timeout · session={}", session.session_id)
        try:
            await worker_ref.queue_frame(
                TTSSpeakFrame(
                    "I haven't heard from you for a while, so I'll end the call now. Goodbye.",
                    append_to_context=False,
                )
            )
        except TypeError:
            await worker_ref.queue_frame(
                TTSSpeakFrame(
                    "I haven't heard from you for a while, so I'll end the call now. Goodbye."
                )
            )
        except Exception:
            logger.exception("worker idle farewell TTS failed")
        await worker_ref.queue_frame(EndFrame())

    async def _live_escalate(reason: str, detail: str) -> None:
        """Force escalate_to_human via a developer nudge (edges 11/13/14/22)."""
        msg = {
            "role": "developer",
            "content": (
                f"IMMEDIATE compliance action: call escalate_to_human with "
                f"reason='{reason}' (detail: {detail}). Speak one short reassurance, "
                "then escalate — do not continue negotiation."
            ),
        }
        await user_aggregator.push_frame(LLMMessagesAppendFrame([msg], run_llm=True))

    async def _live_hold() -> None:
        """Caller said hold on — acknowledge + relax idle (edge #17)."""
        from pipecat.frames.frames import UserIdleTimeoutUpdateFrame

        session.extra["on_hold"] = True
        try:
            await worker.queue_frame(
                TTSSpeakFrame("Of course, take your time.", append_to_context=False)
            )
        except TypeError:
            await worker.queue_frame(TTSSpeakFrame("Of course, take your time."))
        await worker.queue_frame(UserIdleTimeoutUpdateFrame(timeout=45.0))

    async def _live_language(action: dict) -> None:
        """Mid-call language handling within AgentTuning.stt.fallback_languages (edge #16)."""
        from pipecat.frames.frames import STTUpdateSettingsFrame

        from voice.tuning_apply import _language

        if action.get("action") == "switch" and action.get("language"):
            lang = str(action["language"])
            try:
                await worker.queue_frame(
                    STTUpdateSettingsFrame(
                        delta=AzureSTTService.Settings(language=_language(lang))
                    )
                )
                sink._stt_language = lang
                logger.info("STT language switched · session={} · lang={}", session.session_id, lang)
            except Exception:
                logger.exception("STT language switch failed")
                msg = {
                    "role": "developer",
                    "content": (
                        "Caller may be speaking another language. Briefly ask if they "
                        "can continue in English, or call escalate_to_human."
                    ),
                }
                await user_aggregator.push_frame(LLMMessagesAppendFrame([msg], run_llm=True))
            return
        msg = {
            "role": "developer",
            "content": (
                "Caller appears to be speaking a language outside the configured "
                "fallbacks. Briefly offer to connect them to a human agent "
                "(escalate_to_human) or continue in English."
            ),
        }
        await user_aggregator.push_frame(LLMMessagesAppendFrame([msg], run_llm=True))

    sink.configure_live_handlers(
        on_escalate=_live_escalate,
        on_hold=_live_hold,
        on_language=_live_language,
        stt_language=str((tuning.get("stt") or {}).get("language") or "en-IN"),
        fallback_languages=list((tuning.get("stt") or {}).get("fallback_languages") or ["hi-IN", "en-IN"]),
    )

    @user_aggregator.event_handler("on_user_turn_started")
    async def on_user_turn_started(aggregator, strategy):
        nonlocal idle_strikes
        idle_strikes = 0
        if session.extra.get("on_hold"):
            session.extra["on_hold"] = False
            from pipecat.frames.frames import UserIdleTimeoutUpdateFrame

            restore = idle_timeout if idle_timeout is not None else 6.0
            try:
                await worker.queue_frame(UserIdleTimeoutUpdateFrame(timeout=float(restore)))
            except Exception:
                logger.debug("restore idle timeout failed", exc_info=True)

    async def _handle_tune_message(message) -> None:
        delta = _extract_tune_delta(message)
        if not delta:
            return
        applied = await apply_live_tuning_delta(
            worker,
            delta,
            llm_settings_cls=KeepAliveAzureLLMService.Settings,
            tts_settings_cls=KeepAliveAzureTTSService.Settings,
        )
        if applied:
            # Keep session snapshot in sync for logging / next-call restart path.
            from agent_core.tuning import merge_tuning_delta

            session.extra["tuning"] = merge_tuning_delta(session.extra.get("tuning") or tuning, applied)
            logger.info("Live tuning applied · session={} · delta={}", session.session_id, applied)

    # Prefer worker.rtvi (PipelineWorker enable_rtvi=True) — unwraps
    # client-message → ClientMessage(type="tuning_delta", data=delta).
    try:
        rtvi = worker.rtvi
        # Domain events (crm.entity / rag.hits / flow.node / lifecycle) ride the
        # same processor as tuning deltas.
        emitter.bind(rtvi)

        @rtvi.event_handler("on_client_message")
        async def on_rtvi_client_message(rtvi_proc, message):
            await _handle_tune_message(message)
    except Exception:
        logger.debug("worker.rtvi on_client_message not available", exc_info=True)

    # Fallback: raw data-channel JSON still arrives here as
    # {type: "client-message", data: {t, d}} before/alongside RTVIProcessor.
    @transport.event_handler("on_app_message")
    async def on_app_message(transport, message, sender=None):
        await _handle_tune_message(message)

    async def _max_duration_watchdog() -> None:
        """Hard cap on call length with spoken sign-off (docs: Maximum Call Duration)."""
        try:
            await asyncio.sleep(_MAX_CALL_DURATION_SECS)
            if not _claim_end("max_duration"):
                return
            logger.info(
                "Max call duration reached · session={} · secs={}",
                session.session_id,
                _MAX_CALL_DURATION_SECS,
            )
            try:
                await worker.queue_frame(
                    TTSSpeakFrame(
                        "We've reached our time limit for this call. Thank you, goodbye.",
                        append_to_context=False,
                    )
                )
            except TypeError:
                await worker.queue_frame(
                    TTSSpeakFrame(
                        "We've reached our time limit for this call. Thank you, goodbye."
                    )
                )
            await worker.queue_frame(EndFrame())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("max-duration watchdog failed")

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        nonlocal idle_strikes, duration_task
        idle_strikes = 0
        logger.info("Client connected · session={}", session.session_id)
        _spawn_bg(prewarm_llm_connection(force=True))
        duration_task = asyncio.create_task(_max_duration_watchdog())

        try:
            row = await asyncio.to_thread(
                bind_session_start,
                session,
                deployment_id=bundle.get("deploymentId"),
                transport="smallwebrtc",
                bot_id=bot_id,
            )
            await sink.start()
            logger.info(
                "CRM session live · interaction={} · customer={}",
                row["interactionId"],
                row["customerId"],
            )
            # Deep-link keys for Sandbox → Customer 360. voiceSessionId equals
            # sessionId after unification; both written so clients can rely on
            # either field without guessing.
            if _vsb is not None and sandbox_session and sandbox_session.get("sessionId"):
                try:
                    _vsb.patch_session(
                        str(sandbox_session["sessionId"]),
                        {
                            "voiceSessionId": session.session_id,
                            "interactionId": row["interactionId"],
                            "status": "live",
                        },
                    )
                except Exception:
                    logger.exception("sandbox session CRM id patch failed (non-fatal)")
        except Exception:
            logger.exception("Failed to start CRM persistence — call continues without DB")

        await emitter.lifecycle(phase="connected", reason=session.session_id)

        # Persona describes the simulated caller the tester is playing. It was
        # written into the session file but never read — the bot had no idea who
        # it was talking to in a rehearsal.
        if sandbox_persona:
            try:
                from agent_core.context import CallContext

                persona_msg = CallContext(
                    channel="sandbox_live", persona=sandbox_persona
                ).persona_message()
                if persona_msg:
                    await _inject_developer([persona_msg])
                    logger.info(
                        "Sandbox persona applied · session={} · name={}",
                        session.session_id,
                        sandbox_persona.get("name"),
                    )
            except Exception:
                logger.exception("persona injection failed (non-fatal)")

        try:
            await flow_manager.initialize(initial_node())
        except (FlowInitializationError, FlowTransitionError, ActionError, InvalidFunctionError) as exc:
            logger.exception("FlowManager initialize failed ({})", type(exc).__name__)
            try:
                await worker.queue_frame(
                    TTSSpeakFrame(
                        "I'm having trouble starting this call. Please try again shortly.",
                        append_to_context=False,
                    )
                )
            except Exception:
                pass
            await worker.queue_frame(EndFrame())
        except FlowError:
            logger.exception("FlowManager initialize failed (FlowError)")
            await worker.queue_frame(EndFrame())
        except Exception:
            logger.exception("FlowManager initialize failed")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected · session={}", session.session_id)
        await emitter.lifecycle(phase="ended", reason="client_disconnected")
        if duration_task is not None and not duration_task.done():
            duration_task.cancel()
        try:
            if getattr(audiobuffer, "is_recording", None) and audiobuffer.is_recording():
                await audiobuffer.stop_recording()
            elif hasattr(audiobuffer, "stop_recording"):
                await audiobuffer.stop_recording()
        except Exception:
            logger.exception("stop_recording failed")
        try:
            await sink.stop(final_status="completed")
        except Exception:
            logger.exception("CRM sink stop failed")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)
    await runner.run()


async def bot(runner_args):
    from pipecat.evals.transport import EvalTransportParams
    from pipecat.runner.utils import create_transport
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams

    transport_params = {
        "eval": lambda: EvalTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
        "twilio": lambda: FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
        "webrtc": lambda: TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    }
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


def _ensure_utf8_stdio() -> None:
    """Pipecat banner uses box-drawing chars; Windows cp1252 cannot print them."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


if __name__ == "__main__":
    _ensure_utf8_stdio()
    from pipecat.runner.run import main

    main()
