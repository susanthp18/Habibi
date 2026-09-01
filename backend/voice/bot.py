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
import json
import sys
import time
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
from prompt_render import render_system_prompt, strip_unrendered_crm_tokens
from voice import config as voice_config
from voice.context_edit import replace_developer_block
from voice.crm_sink import CrmSink, bind_session_start, mark_crm_degraded
from voice.flows import build_collections_flow
from voice.latency import KeepAliveAzureLLMService, prewarm_llm_connection
from voice.natural import build_voice_system_prompt, filler_for_function_names
from voice.recording import attach_recording_handlers
from voice.session import VoiceSession
from voice import budget
from voice import log_bridge
from voice.spoken_text import SpokenTextFilter
from voice.turn_probe import SpokeThisResponseProbe
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


def _persona_context(bundle: dict) -> dict[str, str]:
    """Operator-token values this card implies, for the system-prompt render.

    Only ``{language}`` is card-dependent; ``{agent_name}`` and ``{bank_name}``
    are tenant environment and ``{time_of_day}`` is the clock. It exists as a
    function because the previous arrangement — an optional ``context``
    parameter that the one caller never passed — meant every voice call
    substituted ``default_context``'s ``"English"`` no matter what the Persona
    tab said. Deriving the context from the bundle removes the opportunity to
    forget rather than adding a caller who must remember.
    """
    persona = bundle.get("persona") if isinstance(bundle.get("persona"), dict) else {}
    name = str(persona.get("language") or "").strip()
    return {"language": name} if name else {}


def _system_instruction_from_bundle(bundle: dict, context: dict | None = None) -> str:
    """Lean voice system prompt — authored prompt + persona + guardrails + voice rules.

    ``context`` overlays the card's own values, for callers (tests, the sandbox)
    that need to pin a token.
    """
    ctx = default_context({**_persona_context(bundle), **(context or {})})
    # System policy takes operator tokens only. This used to call render_prompt,
    # which substitutes CRM fields straight into the system string — the one
    # thing prompt_render.py exists to prevent, and the reason the call-start
    # defaults leaked out as "account XXXX". The real values reach the model on
    # the untrusted developer card (ctx.crm_card_message), refreshed as the call
    # learns who it is talking to, so nothing is lost by leaving them out here.
    rendered = render_system_prompt(bundle.get("prompt") or "", ctx)
    rendered = strip_unrendered_crm_tokens(rendered)
    prompt = build_voice_system_prompt(
        rendered,
        bundle.get("guardrails") or {},
        persona=bundle.get("persona") if isinstance(bundle.get("persona"), dict) else None,
    )
    from agent_core.skills.runtime import resolve_mouth

    prefix = resolve_mouth(bundle.get("agentCard") or {}).prompt().prefix
    if prefix:
        prompt = prompt.rstrip() + "\n\n" + prefix
    return prompt


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

#: How long end-of-call bookkeeping may take before teardown proceeds without
#: it. Generous — a healthy finalize is well under a second, and the slowest
#: real one observed was six — but finite, which is the point: past this, the
#: records lose and the worker gets cancelled. The alternative is what actually
#: happened, which is that one drain that never returned kept a whole session
#: alive and made every later call on the process fail.
_FINALIZE_BUDGET_SECS = 20.0

#: Above this, the caller has been holding a silent line long enough that the
#: call is at risk. Healthy setup on a warm process is well under a second; the
#: run that started this investigation took 16.5s and Twilio hung up at 0.5s
#: past ready. Warned rather than enforced — refusing the call outright would
#: turn a degraded call into no call.
_SLOW_SETUP_WARN_SECS = 4.0

#: Conversation + classifier LLM starts before the callee has said a real
#: word. VS-4D8667B522 burned 46 turns on one "Hello." Six is already a loop.
_LOOP_LLM_BUDGET = 6

# Dead-air watchdog.
#
# Pipecat's UserIdleController starts its timer on BotStoppedSpeakingFrame and
# re-arms nowhere else. Every silence that follows a bot turn is therefore
# covered — and every silence that does NOT is invisible to it. A transition
# into a listen-first node, a tool call that resolves without a reply, or a
# chain of transition tools that never reaches speech all leave no timer
# running at all: on VS-92CDE3F088 the line was mute for 24 seconds with the
# ladder configured and not one strike logged.
#
# This watchdog measures silence itself, from frames, and feeds the same ladder.
# The poll interval is deliberately coarse — it is a backstop, not a turn timer.
_DEADAIR_POLL_SECS = 1.0
#: Added to the configured idle timeout before the watchdog acts, so the
#: aggregator's own timer always wins when it is armed and the watchdog only
#: speaks for the silences nothing else can see.
_DEADAIR_GRACE_SECS = 2.0
#: Floor for the watchdog, independent of tuning. A 2s idle_timeout is a
#: turn-taking preference; hanging on it as a dead-air threshold would nudge
#: over ordinary thinking pauses.
_DEADAIR_MIN_SECS = 6.0
#: One quiet stretch must not burn two rungs of the ladder just because two
#: timers noticed it.
_IDLE_REFIRE_GUARD_SECS = 4.0

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


async def _drain_tasks(tasks: set[asyncio.Task], *, label: str, timeout: float = 2.0) -> None:
    """Settle a call's fire-and-forget tasks, then cancel whatever is left.

    Mirrors voice.tools.drain_background_tasks. Best-effort work must not hold
    up the hangup path, but it also must not be abandoned pending — that is
    what logs "Task was destroyed but it is pending!" at interpreter exit.
    """
    pending = [t for t in tasks if not t.done()]
    if not pending:
        return
    done, still_pending = await asyncio.wait(pending, timeout=timeout)
    for task in still_pending:
        task.cancel()
    if still_pending:
        await asyncio.gather(*still_pending, return_exceptions=True)
    for task in done:
        if not task.cancelled() and task.exception() is not None:
            logger.debug("{} task failed: {}", label, task.exception())


def _sandbox_session_id_from(runner_args, is_session_id) -> str | None:
    """Pull the Sandbox Live session id out of the transport's request data.

    The browser sends it as SmallWebRTC ``requestData``, which the runner puts on
    ``runner_args.body``; the ``/start`` runner path nests the same dict one level
    deeper under ``body``, and a client that posts raw JSON leaves it a string.
    All three shapes are accepted.

    ``runner_args.session_id`` is deliberately *validated*, not trusted: the
    embedded host (:mod:`voice.host`) sets it to our ``VS-`` id, but the
    standalone ``pipecat.runner`` mints ``str(uuid4())`` for every offer. Taking
    that as a sandbox id raised ``invalid_session_id`` on every single call and
    dropped the whole Live configuration.
    """
    body = getattr(runner_args, "body", None)
    if isinstance(body, (str, bytes)):
        try:
            body = json.loads(body)
        except (ValueError, TypeError):
            body = None

    seen: list[str] = []
    for source in (body, (body or {}).get("body") if isinstance(body, dict) else None):
        if not isinstance(source, dict):
            continue
        for key in ("sessionId", "session_id"):
            value = source.get(key)
            if isinstance(value, str) and value:
                seen.append(value)

    transport_sid = getattr(runner_args, "session_id", None)
    if isinstance(transport_sid, str) and transport_sid:
        seen.append(transport_sid)

    for candidate in seen:
        if is_session_id(candidate):
            return candidate
    if seen:
        # A non-canonical id here is a client bug worth naming, not silence.
        logger.warning(
            "ignoring non-sandbox session identifiers on this connection: {}",
            ", ".join(sorted(set(seen))),
        )
    return None


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

    # Strong refs for this call's fire-and-forget tasks — the loop only holds a
    # weak ref, so without this a prewarm task can be GC'd mid-flight and
    # silently cancelled. Per-call (not module-level) so an embedded host running
    # two calls cannot have one teardown reach into the other's tasks, and so the
    # set dies with the call instead of accumulating for the process lifetime.
    bg_tasks: set[asyncio.Task] = set()

    def _spawn_bg(coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        bg_tasks.add(task)
        task.add_done_callback(bg_tasks.discard)
        return task

    # Prefer Sandbox Live session config (written by POST /voice/sandbox/start).
    # Session id arrives via SmallWebRTC request_data → runner_args.body. Never
    # use a shared "latest" pointer — that races between concurrent calls.
    sandbox_session = None
    _store = None
    call_data = getattr(runner_args, "call_data", None)
    transport_type = (
        getattr(runner_args, "transport_type", None)
        or getattr(call_data, "provider", None)
        or ""
    )
    if not transport_type and call_data is not None:
        transport_type = "twilio"
    is_twilio = str(transport_type).lower() in {"twilio", "telnyx", "plivo", "exotel"}
    sandbox_load_error: str | None = None
    try:
        import voice_session_store as _store
    except Exception:
        logger.exception("voice session store unimportable — Live config unavailable")
        sandbox_load_error = "store_unimportable"

    if _store is not None:
        sid = _sandbox_session_id_from(runner_args, _store.is_session_id)
        if sid:
            try:
                sandbox_session = _store.read(sid)
                if not sandbox_session:
                    # The API minted this id, so an empty read means the two
                    # processes are not looking at the same store.
                    sandbox_load_error = "session_not_found"
                    logger.error(
                        "voice sandbox session {} not found in {} store — Live call will "
                        "run with the production bundle, not the sandbox config",
                        sid,
                        _store.backend(),
                    )
            except _store.SessionStoreUnavailable:
                sandbox_load_error = "store_unavailable"
                logger.exception("voice sandbox session store unavailable for {}", sid)
            except ValueError:
                # Guarded by is_session_id above; only reachable if the two
                # validators ever diverge.
                sandbox_load_error = "invalid_session_id"
                logger.exception("rejected malformed sandbox session id {}", sid)
        elif not is_twilio:
            sandbox_load_error = "no_session_id"
            logger.warning(
                "No sandbox sessionId in the WebRTC offer — the client must connect with "
                "webrtcRequestParams.requestData = {{sessionId}}. Falling back to the "
                "production bundle; persona / KB snapshot / tuning will not apply."
            )

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

    bot_id = (
        bundle.get("botId")
        or (bundle.get("promptVersion") or {}).get("botId")
        or _db.DEFAULT_BOT_ID
    )
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
            # The mission has to be known *here*, not in on_client_connected:
            # the flow graph is compiled further down this function and the
            # objective is what chooses which node the call starts at. Reading
            # it at connect time would mean every outbound mission compiled
            # against the inbound entry and then arrived too late to matter.
            if str(body_params.get("call_type") or "").strip().lower() == "outbound":
                session.extra["attempt_id"] = (
                    str(body_params.get("attempt_id") or "").strip() or None
                )
                session.extra["objective"] = (
                    str(body_params.get("objective") or "").strip() or None
                )
                # Closes the arc: this id was already being written into the
                # stream parameters and read by nothing, so an outcome could
                # never attach to the decision that caused the call.
                session.extra["treatment_decision_id"] = (
                    str(body_params.get("treatment_decision_id") or "").strip() or None
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
    # A bundle carrying a sandbox persona is a rehearsal: the "caller" is a
    # tester reading a script and no customer is contacted. The contact rules
    # (calling window, DND) must not judge it — flagging a 20:43 rehearsal as an
    # RBI hours breach cost a high-severity self-correction on turn one.
    is_simulated = isinstance(bundle.get("sandboxPersona"), dict)
    sink = CrmSink(
        session,
        guardrails=bundle.get("guardrails") or {},
        direction=str(bundle.get("callDirection") or "inbound"),
        simulated=is_simulated,
    )
    system_instruction = _system_instruction_from_bundle(bundle)

    # The mission briefing. Appended to the persona rather than replacing it:
    # who the agent *is* comes from the published card, and why they are on this
    # particular call comes from the decision that placed it. Both are needed and
    # neither is the other.
    #
    # Loaded here because the flow graph is compiled a few lines below and the
    # briefing has to be in the system prompt before the first turn is built. A
    # missing or unreadable mission degrades to the ordinary script, which is
    # what an outbound call did until now anyway.
    _mission: dict[str, Any] | None = None
    if session.extra.get("attempt_id"):
        try:
            import mission as mission_mod

            def _load_mission() -> dict[str, Any] | None:
                import db as _db

                with _db.engine.connect() as conn:
                    return mission_mod.load(conn, str(session.extra["attempt_id"]))

            _mission = await asyncio.to_thread(_load_mission)
        except Exception:
            logger.exception("mission load failed — continuing without a briefing")
        if _mission:
            session.extra["mission"] = _mission
            # The card's entry node wins over the objective lookup when both
            # exist; they agree unless someone edited one of them, and G-OB2
            # blocks publishing that state.
            if _mission.get("entryNode"):
                session.extra["entry_node"] = _mission["entryNode"]
            if _mission.get("allowedOffers") == []:
                # Same latch the hardship interlock uses. A mission with no
                # allowed offers must not be able to reach a product pitch by
                # any route, prompt included.
                session.extra["upsell_blocked"] = "mission_forbids_offers"
            if _mission.get("maxDurationSec"):
                session.extra["max_duration_sec"] = int(_mission["maxDurationSec"])
            if _mission.get("customerName"):
                session.extra["expected_customer_name"] = _mission["customerName"]
            try:
                system_instruction = (
                    system_instruction.rstrip()
                    + chr(10) * 2
                    + mission_mod.briefing(_mission)
                )
            except Exception:
                logger.exception("mission briefing render failed")
            system_instruction = system_instruction.replace(
                "inbound collections voice agent",
                "outbound collections voice agent",
            )

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
        # The card's language, so the recogniser listens for what the Persona
        # tab chose. An explicit AgentTuning.stt.language still wins.
        persona_language=(
            (bundle.get("persona") or {}).get("language")
            if isinstance(bundle.get("persona"), dict)
            else None
        ),
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
            "text_filters": [SpokenTextFilter()],
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

    # Interlock between the two ways of covering tool latency, and the
    # authoritative bot-turn tap — see voice/turn_probe.py. Constructed here so
    # the filler handler below can close over it.
    #
    # record_bot_turn only enqueues, so awaiting it on the pipeline task is
    # safe; the CRM write happens on the sink's own drain.
    def _on_first_tts_text(text: str) -> None:
        from voice.call_trace import preview as _preview

        origin = getattr(runner_args, "setup_started_at", None)
        waited = (time.monotonic() - origin) if origin else None
        _setup_trace(
            "first.tts",
            preview=_preview(text),
            waited_s=round(waited, 3) if waited is not None else None,
        )

    spoke_probe = SpokeThisResponseProbe(
        on_bot_turn=sink.record_bot_turn,
        on_first_tts=_on_first_tts_text,
    )

    # Mask CRM/tool latency with a short spoken filler (plan §6) — but only when
    # the model did NOT already acknowledge in this same response. The role
    # message now asks for acknowledge-then-call, so on the good path the
    # caller is already hearing something and this filler would talk over it.
    @llm.event_handler("on_function_calls_started")
    async def _on_function_calls_started(service, function_calls):
        if spoke_probe.spoke_this_response:
            return
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

    from voice.kb_enrich import KbCache, KbEnrichProcessor, KbSpeculationProcessor

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

    async def _replace_developer(prefix: str, message: dict[str, str]) -> None:
        """Re-inject a developer block, evicting the previous one first.

        ``_inject_developer`` is append-only, which is right for one-shot deltas
        but wrong for the CRM card: refreshing it after every write would leave N
        cards in context, and once auto-summarisation folds them together the
        model can assert a stale balance over a fresh one. Same failure class as
        the VS-0D653BF9C3 incident noted above.
        """
        if not message:
            return
        replace_developer_block(
            context.get_messages,
            context.set_messages,
            prefix=prefix,
            message=message,
        )

    # ToolState is created inside build_collections_flow below; the getter reads
    # it lazily so KB corpus scope can follow the live Flows node.
    _flow_holder: dict[str, object] = {}

    def _current_product_keys() -> list[str] | None:
        from agent_core.context import product_keys_for_node

        state = _flow_holder.get("state")
        # Explicit scope wins. product_keys_for_node keys off _PRODUCT_NODES =
        # {"gated_upsell"}; under VOICE_FLOW_GRAPH=hub that node does not exist,
        # so without this an insurance question would be answered out of the
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

    # Silence ladder (§6) — escalate nudge → direct → close.
    idle_strikes = 0
    # When the ladder last fired. Two independent timers can now reach it —
    # Pipecat's UserIdleController and the dead-air watchdog below — and a
    # strike raised twice for one silence would skip a rung and hang up early.
    last_idle_fired = 0.0
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
    idle_ladder = list(tuning["interaction"].get("idle_ladder") or ["nudge", "direct", "close"])
    # Single-flight end: idle ladder / worker idle / max-duration must not stack
    # with each other or with Flows end_conversation (feedback #4).
    ending = False
    duration_task: asyncio.Task | None = None
    deadair_task: asyncio.Task | None = None

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
        # Read back by on_pipeline_finished so the finalized interaction records
        # why the call ended rather than a generic "bot_ended".
        session.extra.setdefault("ending_reason", reason)
        if duration_task is not None and not duration_task.done():
            duration_task.cancel()
        if deadair_task is not None and not deadair_task.done():
            deadair_task.cancel()
        return True

    @user_aggregator.event_handler("on_user_turn_idle")
    async def on_user_turn_idle(aggregator):
        nonlocal idle_strikes, last_idle_fired
        # `ending` covers a call the *bot* is winding down. `finalized` covers a
        # call that is already over — chiefly the caller hanging up, which is the
        # ending this handler used to talk straight through. On VS-BEDB3F54D7 the
        # caller disconnected at 12:20:54 and this watchdog fired seven seconds
        # later, generating and synthesising "Are you still there?" into a dead
        # socket: billed LLM and TTS spend nobody could hear, a CRM drain pushed
        # past its timeout, and an admission slot held 121.1s for a 103.3s call.
        if finalized or ending or session.extra.get("ending"):
            return
        # Two timers, one ladder. The aggregator's timer and the dead-air
        # watchdog cover different silences and overlap in the middle; without
        # this, one quiet stretch can burn two rungs and close a call that had
        # only gone quiet once.
        now = time.monotonic()
        if last_idle_fired and (now - last_idle_fired) < _IDLE_REFIRE_GUARD_SECS:
            return
        last_idle_fired = now
        # Whose silence is it?
        #
        # The aggregator's timer measures silence on the wire, and the bot
        # thinking is silence on the wire. A node transition plus a context
        # summarisation can take six seconds, and firing a nudge into that gap
        # requests a second turn while the first is still being generated — the
        # caller then hears two replies two seconds apart. Do not count a strike
        # either: the caller has not failed to respond to anything yet.
        if bot_turn_state.busy():
            logger.debug(
                "idle suppressed · session={} · bot mid-turn",
                session.session_id,
            )
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
            # Goal-aware re-engagement. "Are you still there?" treats silence as
            # a connection problem; when we know why they called, the useful
            # move is to pick that thread back up. Rungs 2 and 3 stay generic —
            # by then silence probably IS a dropped caller.
            goal = (getattr(session, "call_goal", None) or "").strip()
            # The length and no-restating clauses are load-bearing. Without
            # them the model treated the nudge as a fresh prompt and re-answered
            # its own previous turn almost verbatim — twice on call
            # VS-6B252E0479 — which is what the caller experienced as the bot
            # repeating itself.
            brevity = (
                " Say at most fifteen words. Do NOT restate, re-summarise or "
                "rephrase anything you have already told them — they heard it. "
                "Ask one short question and stop."
            )
            content = (
                (
                    f"The caller has gone quiet. They called about: {goal}. "
                    "Warmly pick that thread back up with one short question "
                    "that helps them move it forward — do not simply ask if "
                    "they are still there." + brevity
                )
                if goal
                else (
                    "The caller has gone quiet. Politely ask if they're still "
                    "there." + brevity
                )
            )
            msg = {"role": "developer", "content": content}
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

    def _on_upsell_engaged() -> None:
        """Activate the insurance specialist when the caller engages a pitch.

        Under the legacy graph this is a ``gated_upsell`` node pre_action. A
        merged hub has no node-entry hook, so the eligibility handler calls this
        instead — which is arguably more accurate: it fires when the caller
        actually engages, not when the graph says they have.
        """

        async def _run() -> None:
            try:
                from voice import mesh_bus

                role = await mesh_bus.activate_and_publish(
                    "insurance",
                    session_id=session.session_id,
                    customer_id=session.customer_id,
                    interaction_id=session.interaction_id,
                    bot_id=bot_id,
                )
                logger.info(
                    "mesh role after upsell engagement → {} · session={}",
                    role,
                    session.session_id,
                )
            except Exception:
                logger.exception("upsell mesh activation failed (non-fatal)")

        from voice.tools import spawn_session_task

        spawn_session_task(session.session_id, _run())

    from agent_core.skills.runtime import resolve_mouth as _resolve_mouth

    _mouth = _resolve_mouth(bundle.get("agentCard") or {})
    # Not `_tool_state`: build_collections_flow returns its own turn state under
    # that name a few lines below, and they are unrelated types.
    _grant = _mouth.tools()
    _allowed_tools = _grant.allowed
    _attached_skills = list(_mouth.packs)

    _tool_state, _tools, initial_node, global_fns = build_collections_flow(
        session,
        role_message=system_instruction,
        bot_id=bot_id,
        start_recording=_start_recording,
        emitter=emitter,
        kb_snapshot_id=kb_snapshot_id,
        inject_developer=_inject_developer,
        replace_developer=_replace_developer,
        persona=sandbox_persona,
        channel="sandbox_live" if sandbox_session else "voice",
        on_kb_tool_used=kb_enrich.suppress,
        spoke_this_response=lambda: spoke_probe.spoke_this_response,
        on_upsell_engaged=_on_upsell_engaged,
        sink=sink,
        allowed_tool_names=_allowed_tools,
        attached_skills=_attached_skills,
    )

    # Authored Prompt Studio graph when the published version has nodes, unless
    # VOICE_FLOW_GRAPH=legacy|hub is an explicit kill-switch. Built after the
    # hardcoded flow rather than instead of it, so any failure — empty graph,
    # compile error — keeps the call on the flow that was already working.
    _authored = bundle.get("flow")
    _flow_override = session.extra.get("flowGraph")
    if voice_config.voice_uses_authored_flow(_authored, override=_flow_override):
        try:
            from voice.flows_dynamic import build_authored_flow

            _tool_state, _tools, initial_node, global_fns = build_authored_flow(
                session,
                _authored,
                role_message=system_instruction,
                bot_id=bot_id,
                start_recording=_start_recording,
                emitter=emitter,
                kb_snapshot_id=kb_snapshot_id,
                inject_developer=_inject_developer,
                replace_developer=_replace_developer,
                persona=sandbox_persona,
                channel="sandbox_live" if sandbox_session else "voice",
                on_kb_tool_used=kb_enrich.suppress,
                spoke_this_response=lambda: spoke_probe.spoke_this_response,
                on_upsell_engaged=_on_upsell_engaged,
                sink=sink,
                allowed_tool_names=_allowed_tools,
                attached_skills=_attached_skills,
                objective=session.extra.get("objective") or None,
                entry_node=session.extra.get("entry_node") or None,
            )
            logger.info(
                "voice flow: using authored graph · mission={}",
                session.extra.get("objective") or "inbound",
            )
        except Exception:
            if voice_config.voice_flow_required():
                # Under `required` the studio is the only source of truth, so a
                # graph that will not compile is a broken deployment, not a call
                # to serve some other way. Falling back here is what let a card
                # be edited and published without changing anything the caller
                # heard.
                logger.exception(
                    "authored flow failed to compile and VOICE_FLOW_GRAPH=required "
                    "· bot={} · refusing the call",
                    bot_id,
                )
                raise
            logger.exception(
                "authored flow failed to compile — falling back to the built-in flow"
            )
    elif voice_config.voice_flow_required():
        # No published graph at all. Same reasoning: under `required` this is a
        # configuration error with a name attached, not something to paper over.
        raise RuntimeError(
            f"voice_flow_required: bot {bot_id!r} has no published Agent Studio "
            "flow (publish one, or set VOICE_FLOW_GRAPH=auto to allow the "
            "built-in script)"
        )

    _flow_holder["state"] = _tool_state
    # The tool map too: the budget watchdog's hard stop needs `end_call`, and
    # reaching for it through the holder keeps the watchdog from closing over a
    # dict that the authored-graph branch above may have replaced.
    _flow_holder["tools"] = _tools
    expected_name = session.extra.get("expected_customer_name")
    if expected_name and not _tool_state.customer_name:
        _tool_state.customer_name = str(expected_name)

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
            from agent_core.cards.handoff_policy import insurance_handoff_allowed

            if not insurance_handoff_allowed(bot_id, bundle.get("agentCard")):
                logger.info("insurance handoff not on card — skip mesh_activate_insurance")
                return

            role = await mesh_bus.activate_and_publish(
                "insurance",
                session_id=session.session_id,
                customer_id=session.customer_id,
                interaction_id=session.interaction_id,
                bot_id=bot_id,
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

        from voice.tuning_apply import normalize_language

        if action.get("action") == "switch" and action.get("language"):
            requested = str(action["language"])
            # The sink stores what STT was actually set to. Storing the raw
            # request instead made the next resolve_language_action compare an
            # un-normalised current_language against normalised fallbacks and
            # re-trigger a switch that had already happened.
            lang = normalize_language(requested)
            try:
                # The *bound* recogniser's Settings class, not Azure's. Once STT
                # can be bound to Deepgram or Speechmatics, hardcoding Azure here
                # would hand a foreign settings object to the running service and
                # turn a language switch into a mid-call failure.
                await worker.queue_frame(
                    STTUpdateSettingsFrame(delta=type(stt).Settings(language=lang))
                )
                sink.set_stt_language(lang)
                logger.info(
                    "STT language switched · session={} · requested={} · lang={}",
                    session.session_id,
                    requested,
                    lang,
                )
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

    async def _live_correction(correction) -> None:
        """Inject one self-correction directive for the next turn.

        run_llm=False is the whole point: the turn that went wrong has already
        been spoken, so this must not trigger inference and make the bot
        announce its own mistake. It sits in context and steers the next reply,
        exactly like the CRM card and the post-write deltas.
        """
        try:
            await _inject_developer([correction.to_message()])
            await emitter.lifecycle(phase="self_correction", reason=correction.kind)
        except Exception:
            logger.debug("self-correction injection failed", exc_info=True)

    async def _live_turn(payload: dict) -> None:
        """Stream one turn's classification and timings to the Inspector."""
        try:
            await emitter.turn_analysis(payload)
        except Exception:
            logger.debug("turn analysis emit failed", exc_info=True)

    sink.configure_live_handlers(
        on_escalate=_live_escalate,
        on_hold=_live_hold,
        on_language=_live_language,
        on_correction=_live_correction,
        on_turn=_live_turn,
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

    @user_aggregator.event_handler("on_user_turn_stopped")
    async def on_user_turn_stopped_rearm_idle(aggregator, strategy, message=None):
        # Local Smart Turn can hand back strategy=None after a barge. The idle
        # controller only arms on BotStoppedSpeaking, so that silence never
        # starts a timer. Re-arm here so the ladder can see the gap.
        if strategy is not None:
            return
        if ending or session.extra.get("ending") or session.extra.get("on_hold"):
            return
        from pipecat.frames.frames import UserIdleTimeoutUpdateFrame

        restore = idle_timeout if idle_timeout is not None else 6.0
        try:
            await worker.queue_frame(UserIdleTimeoutUpdateFrame(timeout=float(restore)))
        except Exception:
            logger.debug("rearm idle after unstrategied user turn failed", exc_info=True)

    async def _handle_tune_message(message) -> None:
        delta = _extract_tune_delta(message)
        if not delta:
            return
        applied = await apply_live_tuning_delta(
            worker,
            delta,
            llm_settings_cls=KeepAliveAzureLLMService.Settings,
            # The bound synthesiser's own class — a live tuning delta must reach
            # whichever provider is actually speaking, not Azure by assumption.
            tts_settings_cls=type(tts).Settings,
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

    async def _deadair_watchdog() -> None:
        """Break silences Pipecat's idle timer structurally cannot see.

        ``UserIdleController`` arms on ``BotStoppedSpeakingFrame`` and re-arms
        nowhere else, so a turn in which the bot never speaks leaves no timer
        running: a transition into a listen-first node, a tool that resolved
        without a reply, or a run of transition tools that never reaches speech.
        The measurement here is of the audio itself, so it holds regardless of
        which of those produced the gap.

        Deliberately routed through ``on_user_turn_idle`` rather than speaking
        on its own: one ladder, one strike count, one place that decides when a
        quiet line becomes a goodbye.
        """
        base = idle_timeout if idle_timeout is not None else 6.0
        if base <= 0:
            return  # idle detection switched off; the watchdog respects that
        threshold = max(_DEADAIR_MIN_SECS, float(base) + _DEADAIR_GRACE_SECS)
        try:
            while True:
                await asyncio.sleep(_DEADAIR_POLL_SECS)
                if ending or session.extra.get("ending"):
                    return
                # busy() covers the legitimate quiet: generating, mid-tool, or
                # between stages. Only silence the bot does not already owe a
                # turn for counts as dead air.
                if bot_turn_state.busy():
                    continue
                if bot_turn_state.silent_for() < threshold:
                    continue
                silent_s = bot_turn_state.silent_for()
                logger.info(
                    "Dead air · session={} · silent={:.1f}s · no idle timer was armed",
                    session.session_id,
                    silent_s,
                )
                _setup_trace(
                    "deadair.nudge",
                    silent_s=round(silent_s, 2),
                    generating=bot_turn_state._generating,
                    tool_calls=bot_turn_state._tool_calls,
                    user_speaking=bot_turn_state._user_speaking,
                )
                await on_user_turn_idle(user_aggregator)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("dead-air watchdog failed")

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        nonlocal idle_strikes, duration_task, deadair_task
        idle_strikes = 0
        started_at = getattr(runner_args, "setup_started_at", None)
        if started_at is None:
            logger.info("Client connected · session={}", session.session_id)
        else:
            setup_secs = time.monotonic() - started_at
            # The caller has been holding an open line for this long with
            # nothing on it. Twilio gives up well before the worst case we have
            # measured (16.5s), so this is a warning, not a statistic.
            log = logger.warning if setup_secs > _SLOW_SETUP_WARN_SECS else logger.info
            log(
                "Client connected · session={} · caller waited {:.1f}s for the "
                "pipeline{}",
                session.session_id,
                setup_secs,
                " — long enough that a carrier may already have hung up"
                if setup_secs > _SLOW_SETUP_WARN_SECS
                else "",
            )
            # The single number that decides whether a carrier waits. Traced
            # with the ids so it joins the dial and the socket into one story.
            from voice.call_trace import event as _trace

            _trace(
                "pipeline.ready",
                session=session.session_id,
                waited_s=round(setup_secs, 2),
                objective=session.extra.get("objective") or "inbound",
                attempt=session.extra.get("attempt_id"),
                over_budget=setup_secs > _SLOW_SETUP_WARN_SECS,
            )
        # Starts the silence clock. Until this, a call that never makes a sound
        # has no origin to measure from and the dead-air watchdog cannot see it
        # — which is exactly how VS-18FE21E37A stayed mute for 77 seconds.
        bot_turn_state.mark_call_started()
        duration_task = asyncio.create_task(_max_duration_watchdog())
        deadair_task = asyncio.create_task(_deadair_watchdog())

        async def _loop_trip_watchdog() -> None:
            try:
                while True:
                    await asyncio.sleep(1.0)
                    if ending or session.extra.get("ending"):
                        return
                    if bot_turn_state.callee_spoke():
                        session.extra["amd_callee_speech"] = True
                        return
                    if bot_turn_state.llm_response_starts <= _LOOP_LLM_BUDGET:
                        continue
                    if session.extra.get("loop_tripped"):
                        return
                    session.extra["loop_tripped"] = True
                    session.extra["amd_closed"] = True
                    guard = getattr(voicemail_detector, "_habibi_guard", None)
                    if guard is not None:
                        guard.closed = True
                    from voice.call_trace import event as _trace
                    from voice.call_trace import session_fields

                    _trace(
                        "loop.trip",
                        **session_fields(session),
                        llm_starts=bot_turn_state.llm_response_starts,
                        reason="llm_turns_before_callee_speech",
                    )
                    logger.warning(
                        "loop.trip · session={} · {} LLM starts before callee speech",
                        session.session_id,
                        bot_turn_state.llm_response_starts,
                    )
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("loop-trip watchdog failed")

        from voice.tools import spawn_session_task

        spawn_session_task(session.session_id, _loop_trip_watchdog())

        # The carrier's own id for this call, and which way it was placed.
        # ``voice_sessions.provider_call_id`` and its unique index have existed
        # since sql/12_crosscutting.sql, and every layer between here and the
        # INSERT already carried the argument — it was simply never supplied, so
        # the column was NULL on every row ever written. Without it a call in
        # the carrier's logs and the interaction in the CRM cannot be joined:
        # no cost attribution, no recording lookup, no way to answer "which
        # customer was CA…?" after the fact.
        #
        # ``call_sid`` is populated in the transport-detection block above from
        # ``call_data`` or the stream's custom parameters; SmallWebRTC sandbox
        # calls legitimately have none, which is why the index is partial.
        provider_call_id = str(session.extra.get("call_sid") or "").strip() or None
        twilio_params = session.extra.get("twilio_params")
        call_type = str(
            (twilio_params or {}).get("call_type")
            if isinstance(twilio_params, dict)
            else session.extra.get("call_type") or ""
        ).strip().lower()
        direction = "outbound" if call_type == "outbound" else "inbound"

        # We chose this borrower, this number and this moment — and until now
        # the call opened as UNKNOWN-CALLER anyway, because `customer_id` was a
        # parameter `bind_session_start` accepted and nobody supplied. The
        # consequence was not cosmetic: the agent re-verified identity from
        # zero on a line it had dialled itself, and the interaction could not be
        # joined to the decision that caused it.
        mission_customer: str | None = None
        attempt_id: str | None = session.extra.get("attempt_id")
        from voice import persist as _persist

        raw_customer = _persist.customer_id_for_bind(
            direction=direction,
            twilio_params=twilio_params if isinstance(twilio_params, dict) else None,
            pstn_customer=(
                session.extra.get("pstn_customer")
                if isinstance(session.extra.get("pstn_customer"), dict)
                else None
            ),
        )
        if raw_customer:
            mission_customer = await asyncio.to_thread(
                _persist.resolve_known_customer,
                raw_customer,
            )
            if mission_customer:
                logger.info(
                    "{} customer bound · customer={} · objective={} · attempt={}",
                    "Outbound mission" if direction == "outbound" else "Inbound ANI",
                    mission_customer,
                    session.extra.get("objective") or "?",
                    attempt_id or "?",
                )

        # What this bind resolved, kept where teardown can reach it. If the bind
        # below fails, CrmSink files the minimal row itself and has no other way
        # to learn which bot answered or which way the call went — and a
        # degraded row filed against the default bot as "inbound" is a second
        # wrong record rather than a thin true one.
        session.extra["bot_id"] = bot_id
        session.extra["call_direction"] = direction

        # The CRM bind runs *beside* the greeting, not in front of it.
        #
        # `bind_session_start` writes the interaction row, and `sink.start()`,
        # the attempt→interaction bind and the sandbox id patch are three more
        # round-trips behind it. Pipecat awaits this handler before the
        # FlowManager initialises, so every one of those writes sat between the
        # borrower answering and the bot's first word. Measured on a loaded
        # host: 5.92s of silence on an answered call, with the greeting ready
        # and waiting the whole time.
        #
        # None of it is needed to speak. The row is bookkeeping; the greeting is
        # the product. So it runs as a task, and the things that genuinely need
        # an interaction id — `session_bound`, and teardown — await the task
        # rather than the caller awaiting the database.
        async def _bind_crm_session() -> None:
            try:
                row = await asyncio.to_thread(
                    bind_session_start,
                    session,
                    deployment_id=bundle.get("deploymentId"),
                    transport=transport_name,
                    provider_call_id=provider_call_id,
                    customer_id=mission_customer,
                    direction=direction,
                    bot_id=bot_id,
                )
                await sink.start()
                logger.info(
                    "CRM session live · interaction={} · customer={}",
                    row["interactionId"],
                    row["customerId"],
                )
                # The mission's time budget. Started here rather than at pipeline
                # build because the clock should run from the moment the borrower
                # answered, not from the moment we started dialling — ring time is
                # not their conversation.
                _budget = budget.budget_for(session)
                if _budget > 0:
                    from voice.tools import spawn_session_task

                    async def _nudge(textmsg: str) -> None:
                        await _inject_developer([{"role": "developer", "content": textmsg}])

                    async def _hard_stop() -> None:
                        tools_map = (_flow_holder.get("tools") or {})
                        ender = tools_map.get("end_call")
                        if ender is not None:
                            await ender(None)

                    spawn_session_task(
                        session.session_id,
                        budget.watch(session, nudge=_nudge, end_call=_hard_stop),
                    )
                    logger.info("mission budget armed · {}s", _budget)

                # Media connected: join the attempt to the conversation it produced.
                # Without this the dial and the call sit in two tables with nothing
                # between them, which is exactly the state the product was in.
                if direction == "outbound" and (attempt_id or provider_call_id):

                    def _bind_attempt() -> None:
                        import db as _db
                        import outbound as _outbound

                        with _db.engine.begin() as conn:
                            _outbound.bind_interaction(
                                conn,
                                attempt_id=attempt_id,
                                provider_call_id=provider_call_id,
                                interaction_id=row["interactionId"],
                            )

                    try:
                        await asyncio.to_thread(_bind_attempt)
                    except Exception:
                        logger.exception("attempt→interaction bind failed (non-fatal)")
                # Deep-link keys for Sandbox → Customer 360. voiceSessionId equals
                # sessionId after unification; both written so clients can rely on
                # either field without guessing.
                if _store is not None and sandbox_session and sandbox_session.get("sessionId"):

                    def _bind_ids(cur: dict[str, Any]) -> dict[str, Any]:
                        return {
                            **cur,
                            "voiceSessionId": session.session_id,
                            "interactionId": row["interactionId"],
                            # A stop that landed first is terminal — re-marking the
                            # session live would resurrect a closed run.
                            "status": "live" if cur.get("status") != "stopped" else "stopped",
                            "updatedAt": time.time(),
                        }

                    try:
                        # to_thread like bind_session_start above: the store is a
                        # Postgres round-trip now, and this runs on the connect path
                        # where blocking the loop delays the greeting.
                        await asyncio.to_thread(
                            _store.mutate, str(sandbox_session["sessionId"]), _bind_ids
                        )
                    except Exception:
                        logger.exception("sandbox session CRM id patch failed (non-fatal)")
            except Exception as bind_exc:
                # "The call continues without DB" was the bug, not the mitigation:
                # session.interaction_id stayed None, every CRM job for the rest of
                # the call was dropped by the interaction_id guards, and a
                # collections call completed with no record that it ever happened.
                #
                # Degrade, do not abort — hanging up on a borrower mid-disclosure to
                # protect a database is not a trade this call gets to make. The flag
                # is read at teardown, where CrmSink.stop files a minimal
                # interaction row (start, end, disposition=crm_degraded) so the call
                # is at least auditable.
                mark_crm_degraded(session, bind_exc)

            # Emitted from in here, after the ids are real. Firing it on the
            # connect path would have published interaction_id=None and given
            # the studio a deep link to nothing.
            await emitter.session_bound(
                interaction_id=session.interaction_id,
                customer_id=session.customer_id,
            )

        crm_bind_task = asyncio.create_task(_bind_crm_session())
        # Teardown waits on this; see `_finalize_call`. Held on the session so
        # the completion record cannot be filed before the row it belongs to.
        session.extra['_crm_bind_task'] = crm_bind_task

        await emitter.lifecycle(phase="connected", reason=session.session_id)

        # A Live call that silently ran the production bundle looked identical
        # in the UI to one that honoured the Tuning Studio. Say so instead.
        if sandbox_load_error and not is_twilio:
            await emitter.lifecycle(
                phase="sandbox_config_unavailable", reason=sandbox_load_error
            )

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
            # Same terminal outcome as the FlowError branch: without a flow the
            # call is connected but deaf, and the caller sits on silence until
            # they hang up (still billed for the leg).
            logger.exception("FlowManager initialize failed")
            await worker.queue_frame(EndFrame())

    finalized = False

    async def _finalize_call(reason: str) -> None:
        """Close out the call exactly once, whoever ended it.

        This used to live inline in ``on_client_disconnected``, which fires only
        when the *remote* peer goes away. A call the bot itself ends — a
        terminal Flows node with an ``end_conversation`` post-action, the
        ``end_call`` tool, the idle ladder, the duration cap — tears down via
        EndFrame and never reaches that handler, so none of this ran: the
        interaction stayed ``active`` forever with no ended_at, duration,
        summary or disposition, no transcript export was written, and the
        worker, its shared-runner registry entry, the mesh session and the
        RTVI task set all leaked.

        Reached from both ``on_client_disconnected`` and ``on_pipeline_finished``
        so either ending wins; ``finalized`` makes the loser a no-op (the
        disconnect path calls ``worker.cancel()`` below, which re-enters here
        through the pipeline event).
        """
        nonlocal finalized
        if finalized:
            return
        finalized = True
        logger.info(
            "Finalizing call · session={} · reason={}", session.session_id, reason
        )
        _setup_trace(
            "call.ended",
            reason=reason,
            ending_reason=session.extra.get("ending_reason"),
            node=session.extra.get("flow_node"),
        )
        # Bookkeeping is bounded; teardown is not optional.
        #
        # Every step below is guarded against *raising*. None was guarded
        # against *hanging*, and `worker.cancel()` sat at the end behind a CRM
        # write and two background-task drains. One drain that never returned
        # meant the worker was never cancelled: the session kept its STT, LLM
        # and TTS attachments and its admission slot for the life of the
        # process. A single leaked session pushed later call setup from 0.4s to
        # 16.5s -- past the point where Twilio waits -- so every subsequent
        # call connected and then heard silence.
        #
        # So: the records are best-effort and time-boxed, the teardown always
        # runs. Losing a summary is a bad call; leaking a worker is a bad hour.
        async def _bookkeeping() -> None:
            # The CRM bind now runs beside the greeting rather than in front of
            # it, so on a short call teardown can arrive first. Wait for it here
            # — bounded, like everything else in this function — or the
            # completion record is filed against an interaction id that does not
            # exist yet and `crm_sink` drops it as "interaction_id unset".
            task = session.extra.get("_crm_bind_task")
            if task is not None and not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=8.0)
                except asyncio.TimeoutError:
                    logger.warning(
                        "crm bind still running at teardown · session={}", session.session_id
                    )
                except Exception:
                    logger.exception("crm bind failed before teardown")

            # Every step is guarded, including the first two. The RTVI transport is
            # usually already gone by the time this runs, so an unguarded lifecycle
            # emit raised straight out of the handler and skipped worker.cancel() /
            # release_worker() below — leaking a worker and a shared-runner registry
            # entry on every disconnected call.
            try:
                await emitter.lifecycle(phase="ended", reason=reason)
            except Exception:
                logger.exception("lifecycle emit on disconnect failed")
            try:
                # Unbind this session from every key pool. The binding is sticky for
                # the life of a call so one turn cannot be voiced by a different
                # account than the next; without releasing it the map is append-only
                # — one entry per call, per provider, for the life of the process.
                from agent_core.providers import pool as _pool

                _pool.release_session(session.session_id)
            except Exception:
                logger.debug("provider key release failed", exc_info=True)
            try:
                if duration_task is not None and not duration_task.done():
                    duration_task.cancel()
                if deadair_task is not None and not deadair_task.done():
                    deadair_task.cancel()
            except Exception:
                logger.exception("duration task cancel failed")
            try:
                if getattr(audiobuffer, "is_recording", None) and audiobuffer.is_recording():
                    await audiobuffer.stop_recording()
                elif hasattr(audiobuffer, "stop_recording"):
                    await audiobuffer.stop_recording()
            except Exception:
                logger.exception("stop_recording failed")
            try:
                # Hit rate is the only evidence that can justify flipping
                # KB_ENRICH_FALLBACK to spec_only later, so log it per call.
                logger.info(
                    "kb speculation · session={} · {}", session.session_id, kb_cache.stats()
                )
            except Exception:
                logger.debug("kb stats log failed", exc_info=True)
            try:
                await sink.stop(final_status="completed")
            except Exception:
                logger.exception("CRM sink stop failed")
            try:
                from voice.tools import drain_background_tasks, release_session_tasks

                # Scoped to THIS call: an embedded host runs concurrent sessions in
                # one process, and an unscoped drain cancelled the other call's
                # in-flight emits.
                await drain_background_tasks(session.session_id)
                release_session_tasks(session.session_id)
            except Exception:
                logger.exception("rtvi emit drain failed")
            try:
                await _drain_tasks(bg_tasks, label="voice bg")
            except Exception:
                logger.exception("background task drain failed")
            try:
                from voice.mesh import release_session

                release_session(session.session_id)
            except Exception:
                logger.exception("mesh session release failed")

        try:
            await asyncio.wait_for(_bookkeeping(), timeout=_FINALIZE_BUDGET_SECS)
        except asyncio.TimeoutError:
            logger.error(
                "finalize bookkeeping exceeded {}s -- tearing down anyway "
                "(session={} reason={})",
                _FINALIZE_BUDGET_SECS, session.session_id, reason,
            )
        except Exception:
            logger.exception("finalize bookkeeping failed -- tearing down anyway")
        finally:
            try:
                await worker.cancel()
            except Exception:
                logger.exception("worker cancel failed")
            # A shared runner keeps a registry entry per worker for its whole life
            # and has no public detach, so an embedded host would accumulate one
            # dead entry per call until the API process is restarted.
            shared = getattr(runner_args, "shared_runner", None)
            if shared is not None:
                try:
                    from voice.host import release_worker

                    await release_worker(shared, worker)
                except Exception:
                    logger.exception("shared runner release failed")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected · session={}", session.session_id)
        await _finalize_call("client_disconnected")

    @worker.event_handler("on_pipeline_finished")
    async def on_pipeline_finished(worker_ref, frame):
        # The bot-initiated ending. Terminal Flows nodes, end_call, the idle
        # ladder and the duration cap all converge on EndFrame, which reaches
        # here but never reaches on_client_disconnected. `ending_reason` is set
        # by whichever path claimed the end so the interaction records *why* it
        # ended rather than a generic "bot_ended".
        await _finalize_call(str(session.extra.get("ending_reason") or "bot_ended"))

    # Embedded host (voice/host.py): a single long-lived runner owns every call,
    # so this session must join it instead of standing up a runner that owns the
    # process — a per-call runner would install signal handlers on the API's
    # event loop and end when its one worker finished.
    shared_runner = getattr(runner_args, "shared_runner", None)
    if shared_runner is not None:
        await shared_runner.add_workers(worker)
        # add_workers starts the worker on an already-running runner; the call
        # then lives until disconnect/idle cancels it above.
        return

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)
    await runner.run()


async def bot(runner_args):
    """Single entry point for every hosting mode — and so the admission gate.

    Both the embedded host (``voice.host._dispatch``) and the standalone
    ``python -m voice.bot`` runner land here, which is why the concurrency cap
    lives at this level rather than in the host: gating only the host would
    leave the compose stack's voice worker uncapped, and gating both would let
    one call consume two slots.
    """
    from voice import admission

    # Before create_transport: refusing after the transport is up means the
    # expensive part (STT/TTS connections, flow build) already happened, and the
    # caller has already heard the line open.
    try:
        slot_token = admission.acquire(label="voice")
    except admission.AtCapacity as exc:
        logger.warning("refusing call: {}", exc)
        await admission.refuse(runner_args, label="voice")
        return

    # The socket is already accepted by the time we get here: the caller is
    # connected and waiting while the pipeline is built. That readiness window
    # is therefore a hard limit on whether the call works at all — Twilio tears
    # the media stream down long before a slow build finishes, and the symptom
    # is a call that connects and then plays silence, with every status callback
    # still reporting success.
    #
    # Stamped here so `on_client_connected` can say how long the caller waited.
    # It is the one number that distinguishes "the bot is broken" from "the bot
    # was not ready in time", and nothing was measuring it.
    try:
        runner_args.setup_started_at = time.monotonic()
    except Exception:
        logger.debug("could not stamp setup start on runner_args", exc_info=True)

    try:
        await _bot_session(runner_args)
    finally:
        # finally, not after the await: a cancelled session (deploy drain,
        # client vanishing) must return its slot too, or the effective cap
        # ratchets down until the process serves nothing.
        admission.release(slot_token)


async def _bot_session(runner_args):
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


def _warm_before_serving() -> None:
    """Pay the cold-start before a caller can arrive, not during their call.

    The first call after a restart runs every one-time cost inside the window
    the browser is waiting on: WebRTC has already sent its offer and is holding
    an unanswered handshake. On VS-22F820E252 the pipeline took 61s to become
    ready, the client re-offered at 70s, that renegotiation tore down the
    in-flight connection, and the call died at "Starting live voice session…"
    without ever connecting. The largest single number in that window was a
    62-second Azure warm-up.

    Doing it here costs the operator a slower `python -m voice.bot` and costs
    the first caller nothing. Best-effort: a runner that cannot reach Azure at
    boot must still start and serve.
    """
    try:
        import azure_openai

        ms = azure_openai.prewarm(force=True)
        if ms:
            logger.info("voice runner warm · azure {:.0f} ms · ready to take calls", ms)
    except Exception:
        logger.warning("startup warm failed — the first call pays it instead", exc_info=True)

    # The Postgres side of retrieval is cold too, and nothing warmed it: the
    # first vector query of a process builds a plan and pulls the HNSW index and
    # the TOASTed vectors off disk (182ms cold vs 0.84ms warm on the live
    # corpus). Separately, the cross-encoder — when it is switched on at all —
    # holds a one-off ONNX graph load that must not land inside a turn.
    try:
        import kb_retrieve

        kb_ms = kb_retrieve.prewarm()
        if kb_ms:
            logger.info("kb retrieval warm · {:.0f} ms", kb_ms)
    except Exception:
        logger.warning("kb warm failed — the first question pays it instead", exc_info=True)

    try:
        from agent_core.tools import kb_rerank

        if kb_rerank.prewarm():
            logger.info("kb reranker warm · model={}", kb_rerank.model_name())
    except Exception:
        logger.debug("kb reranker warm skipped", exc_info=True)

    # Silero VAD and Smart Turn v3 are ONNX models rebuilt per session, paid
    # inside the window the caller is holding an open, silent line.
    #
    # They cannot simply be shared between sessions: both carry per-stream
    # state, so two concurrent calls would analyse each other's audio. What *is*
    # shareable is everything underneath — the onnxruntime library, its thread
    # pools, and the model files in the OS page cache. Building one of each here
    # and discarding it pays for that once, at boot, where it costs the operator
    # a slower start and the caller nothing.
    #
    # Measured on this machine, cold build vs. warm rebuild:
    #     silero-vad   1374 ms -> 327 ms
    #     smart-turn    386 ms -> 215 ms
    # so roughly 1.2s comes off every call's setup. That is not the difference
    # between a fast call and a slow one; at the margin it is the difference
    # between a call and a carrier hanging up on a pipeline that was not ready.
    import time as _time

    # Imports first: they are the largest single cost and the one that made the
    # first call after every restart fail outright.
    started = _time.monotonic()
    warmed = _warm_run_bot_imports()
    logger.info(
        "voice runner warm · imports {}/{} modules {:.0f} ms",
        warmed, len(_RUN_BOT_MODULES), (_time.monotonic() - started) * 1000,
    )

    for label, build in (
        ("llm-service", _warm_llm_service),
        ("silero-vad", _warm_silero),
        ("smart-turn", _warm_smart_turn),
    ):
        started = _time.monotonic()
        try:
            build()
            # loguru, not stdlib logging: this module's logger formats with
            # `{}`. A `%s` here does not raise, it just prints the format string
            # — which is how the line above shipped reading "azure %.0f ms".
            logger.info(
                "voice runner warm · {} {:.0f} ms", label, (_time.monotonic() - started) * 1000
            )
        except Exception:
            logger.warning(
                "startup warm for {} failed — every call pays it instead", label
            )


#: Every module :func:`run_bot` imports on entry.
#:
#: They are function-local there on purpose — importing them at module scope
#: pulls the whole pipeline runtime into anything that merely touches
#: ``voice.bot`` — but the cost has to be paid *somewhere*, and the default was
#: "inside the first caller's window". Measured on this machine that was **32.7
#: seconds**, against a carrier that stops waiting after a few. The first call
#: after every restart was therefore guaranteed to fail, and the second to
#: succeed, which is exactly the shape that gets misdiagnosed as flakiness.
#:
#: Loading them here only populates ``sys.modules``; ``run_bot``'s own imports
#: then hit the cache. It does not change what ``run_bot`` does, only when the
#: bill arrives. ``test_voice_session_teardown`` reads ``run_bot``'s AST and
#: fails if this list drifts behind it.
_RUN_BOT_MODULES: tuple[str, ...] = (
    "pipecat.audio.vad.silero",
    "pipecat.extensions.voicemail.voicemail_detector",
    "pipecat.flows",
    "pipecat.flows.exceptions",
    "pipecat.frames.frames",
    "pipecat.observers.startup_timing_observer",
    "pipecat.observers.user_bot_latency_observer",
    "pipecat.pipeline.pipeline",
    "pipecat.pipeline.worker",
    "pipecat.processors.aggregators.llm_context",
    "pipecat.processors.aggregators.llm_response_universal",
    "pipecat.processors.audio.audio_buffer_processor",
    "pipecat.processors.frameworks.rtvi",
    "pipecat.services.azure.stt",
    "pipecat.utils.context.llm_context_summarization",
    "pipecat.workers.runner",
    "agent_core.cards.handoff_policy",
    "agent_core.context",
    "agent_core.deployment",
    "agent_core.providers",
    "agent_core.skills.runtime",
    "agent_core.tuning",
    "db",
    "mission",
    "outbound",
    "voice",
    "voice.amd",
    "voice.bot_turn_state",
    "voice.call_trace",
    "voice.flows_dynamic",
    "voice.host",
    "voice.ivr",
    "voice.kb_enrich",
    "voice.mesh",
    "voice.rtvi_events",
    "voice.tools",
    "voice.tts_pool",
    "voice.tuning_apply",
    "voice_session_store",
)


def _warm_run_bot_imports() -> int:
    """Import what the first call would otherwise import while someone waits.

    Best-effort per module: a runner that cannot import one optional dependency
    must still start and serve, and the call will pay for that one alone.
    """
    import importlib

    warmed = 0
    for name in _RUN_BOT_MODULES:
        try:
            importlib.import_module(name)
            warmed += 1
        except Exception:
            logger.warning("startup warm: {} would not import", name)
    return warmed


def _warm_llm_service() -> None:
    """Pay the LLM service's one-time class init at boot, not in a call.

    ``KeepAliveAzureLLMService(...)`` costs **2.46s on the first construction of
    the process and 0.00s on every one after it** -- measured, three builds in a
    row. The cost is lazy setup underneath the OpenAI SDK (client plumbing, TLS
    trust store), keyed to the process rather than the instance, so it is paid
    exactly once and then never again.

    Nothing warmed it. ``azure_openai.prewarm`` above warms the *HTTP* path, not
    this constructor, so the first caller after every restart wore the whole
    2.46s inside their setup window -- it was the single largest item in an
    8.38s time-to-greeting on session VS-BEDB3F54D7, larger than the VAD and
    Smart Turn model builds put together.

    Constructed with throwaway settings and discarded: only the process-wide
    initialisation is wanted, and no call is placed.
    """
    KeepAliveAzureLLMService(
        api_key=voice_config.azure_openai_voice_api_key(),
        endpoint=voice_config.azure_openai_voice_endpoint(),
        api_version=voice_config.azure_openai_voice_api_version(),
        settings=KeepAliveAzureLLMService.Settings(
            model=voice_config.azure_openai_voice_deployment(),
            system_instruction="warm",
        ),
    )


def _warm_silero() -> None:
    from pipecat.audio.vad.silero import SileroVADAnalyzer

    SileroVADAnalyzer()


def _warm_smart_turn() -> None:
    from voice.tuning_apply import build_smart_turn_analyzer

    build_smart_turn_analyzer({})


if __name__ == "__main__":
    _ensure_utf8_stdio()
    # Before anything imports and starts logging: without this the product's
    # standard-library loggers never reach loguru's sink. See voice/log_bridge.py.
    log_bridge.install()
    _warm_before_serving()
    from pipecat.runner.run import main

    main()
