"""Voice handlers -- user turns, the turn cap, and live tuning messages.

One section of ``voice.bot_handlers.register_handlers``: the decorated
handlers that used to be closures inside it. ``build(scope)`` receives the
closure scope as a ``HandlerScope`` and unpacks what it reads; the six
mutable scalars the closures shared through ``nonlocal`` live on
``scope.hs`` (``HandlerState``). Bodies are otherwise byte-for-byte what
they were -- a move, pinned by ``tests/test_run_bot_pipeline_snapshot.py``.
"""

from __future__ import annotations


from loguru import logger

from voice.llm_pool import KeepAliveAzureLLMService
from voice.tuning_apply import apply_live_tuning_delta

from voice.bot_handlers_scope import HandlerScope
from voice.bot_handlers_scope import (
    _extract_tune_delta,
)


def build(scope: HandlerScope) -> None:
    """Register this section's handlers on the call's objects."""
    EndFrame = scope.EndFrame
    _claim_end = scope._claim_end
    _live_correction = scope._live_correction
    _live_escalate = scope._live_escalate
    _live_force_escalate = scope._live_force_escalate
    _live_hold = scope._live_hold
    _live_language = scope._live_language
    _live_turn = scope._live_turn
    emitter = scope.emitter
    idle_timeout = scope.idle_timeout
    session = scope.session
    sink = scope.sink
    transport = scope.transport
    tts = scope.tts
    tuning = scope.tuning
    user_aggregator = scope.user_aggregator
    worker = scope.worker
    flow_manager = scope.flow_manager
    _flow_holder = scope._flow_holder
    hs = scope.hs
    bot_turn_state = getattr(scope, "bot_turn_state", None)


    sink.configure_live_handlers(
        on_escalate=_live_escalate,
        on_force_escalate=_live_force_escalate,
        on_hold=_live_hold,
        on_language=_live_language,
        on_correction=_live_correction,
        on_turn=_live_turn,
        stt_language=str((tuning.get("stt") or {}).get("language") or "en-IN"),
        fallback_languages=list((tuning.get("stt") or {}).get("fallback_languages") or ["hi-IN", "en-IN"]),
    )

    @user_aggregator.event_handler("on_user_turn_started")
    async def on_user_turn_started(aggregator, strategy):
        hs.idle_strikes = 0
        if session.extra.get("on_hold"):
            session.extra["on_hold"] = False
            from pipecat.frames.frames import UserIdleTimeoutUpdateFrame

            restore = idle_timeout if idle_timeout is not None else 6.0
            try:
                await worker.queue_frame(UserIdleTimeoutUpdateFrame(timeout=float(restore)))
            except Exception:
                logger.debug("restore idle timeout failed", exc_info=True)

    @user_aggregator.event_handler("on_user_turn_started")
    async def on_user_turn_started_note_barge(aggregator, strategy):
        # Read before the interruption lands: speaking() still reports the
        # audio the caller just talked over.
        hs.turn_cut_bot = bool(bot_turn_state is not None and bot_turn_state.speaking())

    @user_aggregator.event_handler("on_user_turn_stopped")
    async def on_user_turn_stopped_false_barge(aggregator, strategy, message=None):
        """Resume the bot when a barge-in turns out to have had no words in it.

        VAD opens a turn on sound, not speech. On VS-58097BA530 line noise cut
        the bot one second into "could you share the last four digits", the
        turn closed on the backstop with no transcript, and nothing spoke
        again: the caller sat in 12s of silence, then said "Hello?". The only
        recovery was the idle ladder, which is for a caller who went quiet,
        not for a question the caller never heard.
        """
        cut, hs.turn_cut_bot = hs.turn_cut_bot, False
        words = str(getattr(message, "content", "") or "").strip()
        if words:
            hs.false_barges = 0
            return
        if not cut or hs.ending or session.extra.get("ending") or session.extra.get("on_hold"):
            return
        hs.false_barges += 1
        from voice.call_trace import event as _trace
        from voice.call_trace import session_fields

        # Two in a row is a noisy line, not a cut-off sentence: stop repeating
        # and let the idle ladder, which asks whether they can hear us, take it.
        resumed = hs.false_barges <= 2
        _trace("barge.false", **session_fields(session), n=hs.false_barges, resumed=int(resumed))
        if not resumed:
            return
        from pipecat.frames.frames import LLMMessagesAppendFrame

        msg = {
            "role": "developer",
            "content": (
                "Background noise cut you off and the caller did not hear the end of "
                "your last reply; they have said nothing. Say the part they missed "
                "again in one short sentence, ending with your question if you had "
                "one. Do not apologise or mention the noise."
            ),
        }
        await aggregator.push_frame(LLMMessagesAppendFrame([msg], run_llm=True))

    @user_aggregator.event_handler("on_user_turn_stopped")
    async def on_user_turn_stopped_rearm_idle(aggregator, strategy, message=None):
        # Local Smart Turn can hand back strategy=None after a barge. The idle
        # controller only arms on BotStoppedSpeaking, so that silence never
        # starts a timer. Re-arm here so the ladder can see the gap.
        if strategy is not None:
            return
        if hs.ending or session.extra.get("ending") or session.extra.get("on_hold"):
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
        session.extra["flow_node"] = "wrap_up"
        try:
            wrap = None
            state = (_flow_holder or {}).get("state") if isinstance(_flow_holder, dict) else None
            nodes = getattr(state, "nodes", None) or {}
            factory = nodes.get("wrap_up")
            if callable(factory):
                wrap = factory()
            if wrap is None:
                wrap = {
                    "name": "wrap_up",
                    "task_messages": [
                        {
                            "role": "developer",
                            "content": (
                                "Summarise what was agreed in one short sentence and thank them. "
                                "Do not ask new questions."
                            ),
                        }
                    ],
                    "functions": [],
                    "respond_immediately": True,
                    "post_actions": [{"type": "end_conversation"}],
                }
            await flow_manager.set_node_from_config(wrap)
            return
        except Exception:
            logger.exception("max_turns wrap_up failed")
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

            clamps: list = []
            session.extra["tuning"] = merge_tuning_delta(
                session.extra.get("tuning") or tuning, applied, out_clamps=clamps
            )
            if clamps:
                session.extra["tuning_clamp"] = clamps
                applied = {**applied, "tuning_clamp": clamps}
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
    # Only the WebRTC sandbox has a data channel. Twilio and Asterisk
    # transports have no such event, and registering one there logged
    # "event handler on_app_message not registered" on every phone call.
    if scope.transport_name == "smallwebrtc":

        @transport.event_handler("on_app_message")
        async def on_app_message(transport, message, sender=None):
            await _handle_tune_message(message)

