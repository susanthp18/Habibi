"""What the call does once it is running -- the event half of run_bot.

A pure move out of :mod:`voice.bot`: the filler interlock, the silence ladder
and its two watchdogs, the live compliance handlers, Studio tuning deltas,
connect/disconnect, and the single-flight finalize. One closure, as before, so
the shared call state (``ending``, ``finalized``, the strike count, the
watchdog tasks) stays where every handler can reach it.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

from voice import budget
from voice.context_edit import replace_developer_block
from voice.crm_sink import bind_session_start, mark_crm_degraded
from voice.llm_pool import KeepAliveAzureLLMService
from voice.natural import filler_for_function_names
from voice.tuning_apply import apply_live_tuning_delta

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


def make_developer_injectors(call) -> None:
    """The two ways a fact reaches the model between turns."""
    from pipecat.frames.frames import LLMMessagesAppendFrame

    context = call.context
    user_aggregator = call.user_aggregator

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

    call._inject_developer = _inject_developer
    call._replace_developer = _replace_developer


def register_handlers(call) -> None:
    """Every handler on the transport, worker, aggregators and LLM."""
    from pipecat.flows.exceptions import (
        ActionError,
        FlowError,
        FlowInitializationError,
        FlowTransitionError,
        InvalidFunctionError,
    )
    from pipecat.frames.frames import EndFrame, EndWorkerFrame, LLMMessagesAppendFrame, TTSSpeakFrame

    transport = call.transport
    runner_args = call.runner_args
    bg_tasks = call.bg_tasks
    session = call.session
    sink = call.sink
    bundle = call.bundle
    bot_id = call.bot_id
    is_twilio = call.is_twilio
    transport_name = call.transport_name
    sandbox_session = call.sandbox_session
    sandbox_load_error = call.sandbox_load_error
    _store = call._store
    tuning = call.tuning
    idle_timeout = call.idle_timeout
    _setup_trace = call._setup_trace
    stt = call.stt
    tts = call.tts
    llm = call.llm
    user_aggregator = call.user_aggregator
    spoke_probe = call.spoke_probe
    emitter = call.emitter
    sandbox_persona = call.sandbox_persona
    _flow_holder = call._flow_holder
    kb_cache = call.kb_cache
    bot_turn_state = call.bot_turn_state
    audiobuffer = call.audiobuffer
    _inject_developer = call._inject_developer
    initial_node = call.initial_node
    voicemail_detector = call.voicemail_detector
    worker = call.worker
    flow_manager = call.flow_manager

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

    # Silence ladder (§6) — escalate nudge → direct → close.
    idle_strikes = 0
    # When the ladder last fired. Two independent timers can now reach it —
    # Pipecat's UserIdleController and the dead-air watchdog below — and a
    # strike raised twice for one silence would skip a rung and hang up early.
    last_idle_fired = 0.0
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

    @user_aggregator.event_handler("on_user_turn_stopped")
    async def on_user_turn_stopped_max_turns(aggregator, strategy, message=None):
        """The card's ``guardrails.maxTurns``, on the sink's customer-turn count.

        The sink subscribed first (``build_pipeline``), so by the time this runs
        the count includes the turn that just ended. Spoken sign-off and the
        same single-flight end as the duration watchdog; the model's reply to
        this turn is not awaited, because a cap that lets one more answer
        through is a cap of N+1.
        """
        cap = int(session.extra.get("guardrail_max_turns") or 0)
        if cap <= 0 or sink.customer_turns() < cap:
            return
        if not _claim_end("max_turns"):
            return
        logger.info(
            "Max turns reached · session={} · turns={} · cap={}",
            session.session_id,
            sink.customer_turns(),
            cap,
        )
        try:
            await worker.queue_frame(
                TTSSpeakFrame(
                    "We've covered what we can on this call. Thank you, goodbye.",
                    append_to_context=False,
                )
            )
        except TypeError:
            await worker.queue_frame(
                TTSSpeakFrame("We've covered what we can on this call. Thank you, goodbye.")
            )
        await worker.queue_frame(EndFrame())

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
        """Hard cap on call length with spoken sign-off (docs: Maximum Call Duration).

        The card's ``guardrails.maxSeconds`` narrows the platform cap and can
        never widen it, so a slider left at its maximum changes nothing and a
        slider pulled down is honoured.
        """
        cap = _MAX_CALL_DURATION_SECS
        authored = int(session.extra.get("guardrail_max_seconds") or 0)
        if authored > 0:
            cap = min(cap, authored)
        try:
            await asyncio.sleep(cap)
            if not _claim_end("max_duration"):
                return
            logger.info(
                "Max call duration reached · session={} · secs={} · authored={}",
                session.session_id,
                cap,
                authored or "none",
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
        briefing = session.extra.get("mission_briefing")
        if briefing:
            await _inject_developer([{"role": "developer", "content": str(briefing)}])
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
        worker, its shared-runner registry entry and the RTVI task set all
        leaked.

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
