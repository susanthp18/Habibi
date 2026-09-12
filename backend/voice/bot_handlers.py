"""What the call does once it is running -- the event half of run_bot.

A pure move out of :mod:`voice.bot`: the filler interlock, the silence ladder
and its two watchdogs, the live compliance handlers, Studio tuning deltas,
connect/disconnect, and the single-flight finalize. One closure, as before, so
the shared call state (``ending``, ``finalized``, the strike count, the
watchdog tasks) stays where every handler can reach it.
"""

from __future__ import annotations


from loguru import logger

from voice.context_edit import replace_developer_block
from voice.natural import filler_for_function_names
from voice.bot_handlers_scope import (  # noqa: F401  -- re-exported: callers import from here
    _DEADAIR_GRACE_SECS,
    _DEADAIR_MIN_SECS,
    _DEADAIR_POLL_SECS,
    _FINALIZE_BUDGET_SECS,
    _IDLE_REFIRE_GUARD_SECS,
    _LOOP_LLM_BUDGET,
    _MAX_CALL_DURATION_SECS,
    _SLOW_SETUP_WARN_SECS,
    _TUNE_MSG_TYPES,
    _delta_from_payload,
    _drain_tasks,
    _extract_tune_delta,
    HandlerScope,
    HandlerState,
)
from voice import (
    bot_handlers_idle,
    bot_handlers_turns,
    bot_handlers_watchdogs,
    bot_handlers_connect,
    bot_handlers_teardown,
)


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

    # The closure scope, as an object the sections can read, and the six
    # scalars they used to share through `nonlocal`.
    scope = HandlerScope(
        transport=transport,
        runner_args=runner_args,
        bg_tasks=bg_tasks,
        session=session,
        sink=sink,
        bundle=bundle,
        bot_id=bot_id,
        is_twilio=is_twilio,
        transport_name=transport_name,
        sandbox_session=sandbox_session,
        sandbox_load_error=sandbox_load_error,
        _store=_store,
        tuning=tuning,
        idle_timeout=idle_timeout,
        _setup_trace=_setup_trace,
        stt=stt,
        tts=tts,
        llm=llm,
        user_aggregator=user_aggregator,
        spoke_probe=spoke_probe,
        emitter=emitter,
        sandbox_persona=sandbox_persona,
        _flow_holder=_flow_holder,
        kb_cache=kb_cache,
        bot_turn_state=bot_turn_state,
        audiobuffer=audiobuffer,
        _inject_developer=_inject_developer,
        initial_node=initial_node,
        voicemail_detector=voicemail_detector,
        worker=worker,
        flow_manager=flow_manager,
        _on_function_calls_started=_on_function_calls_started,
        ActionError=ActionError,
        FlowError=FlowError,
        FlowInitializationError=FlowInitializationError,
        FlowTransitionError=FlowTransitionError,
        InvalidFunctionError=InvalidFunctionError,
        EndFrame=EndFrame,
        EndWorkerFrame=EndWorkerFrame,
        LLMMessagesAppendFrame=LLMMessagesAppendFrame,
        TTSSpeakFrame=TTSSpeakFrame,
        hs=HandlerState(),
    )
    # Source order: teardown's _finalize_call is read by connect through the
    # scope only after it is built, so the order is the order it always was.
    bot_handlers_idle.build(scope)
    bot_handlers_turns.build(scope)
    bot_handlers_watchdogs.build(scope)
    bot_handlers_connect.build(scope)
    bot_handlers_teardown.build(scope)
