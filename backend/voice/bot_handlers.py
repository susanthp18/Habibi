"""What the call does once it is running -- the event half of run_bot.

A pure move out of :mod:`voice.bot`: the filler interlock, the silence ladder
and its two watchdogs, the live compliance handlers, Studio tuning deltas,
connect/disconnect, and the single-flight finalize. One closure, as before, so
the shared call state (``ending``, ``finalized``, the strike count, the
watchdog tasks) stays where every handler can reach it.
"""

from __future__ import annotations

import asyncio
from typing import Any

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


def _tts_busy(tts: Any) -> bool:
    """True while TTS is still synthesising or draining a stop.

    After barge-in the previous utterance can still be in ``stop_speaking``.
    Queuing a filler then talks over the caller. Do not call ``Connection.open``
    here — that is the 41s deadlock class.
    """
    if getattr(tts, "_processing_text", False):
        return True
    if getattr(tts, "_playing_context_id", None):
        return True
    has_ctx = getattr(tts, "has_active_audio_context", None)
    if callable(has_ctx):
        try:
            return bool(has_ctx())
        except Exception:
            return False
    return False


def should_skip_filler(spoke_probe: Any, tts: Any) -> bool:
    """Whether the automatic tool-latency filler would talk over someone."""
    if spoke_probe.spoke_this_response:
        return True
    if spoke_probe.interrupted_this_response:
        return True
    return _tts_busy(tts)


def make_developer_injectors(call) -> None:
    """The two ways a fact reaches the model between turns."""
    from pipecat.frames.frames import LLMMessagesAppendFrame

    context = call.context

    async def _inject_developer(messages: list[Any]) -> None:
        """Append developer messages (CRM card, persona, deltas) to the context.

        run_llm=False: these are facts for the *next* turn, not a prompt to
        speak now. Letting them trigger inference would make the bot narrate
        its own CRM lookup.

        Queued on the worker, never pushed from a processor. The transport
        fires ``on_client_connected`` before ``StartFrame`` has reached the user
        aggregator, and Pipecat's ``push_frame`` on a processor that has not
        started logs an ERROR and *drops* the frame. That is where every
        outbound mission briefing went on VS-8C1B760F1B and VS-E6043500C0: the
        model never saw the open promise, the balance, or "do NOT mention any
        product", and read nine insurance products to a borrower on a call the
        mission forbade offers on. The worker queue sits behind ``StartFrame``
        and is FIFO with the flow's own node messages, so a message injected
        before ``FlowManager.initialize`` also lands before the first node.
        """
        if not messages:
            return
        worker = getattr(call, "worker", None)
        if worker is None:
            # Nothing can carry a frame before the pipeline exists. Raising is
            # the honest outcome; a silent drop is the bug this replaced.
            raise RuntimeError("developer message injected before the pipeline was built")
        await worker.queue_frame(LLMMessagesAppendFrame(messages, run_llm=False))

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
    # A 40ms verify on VS-E6043500C0 still spoke "Thanks, just confirming"
    # and then the model opened with "Thanks" again. Wait, and speak only
    # if the tool is still running and the model has not started talking.
    _FILLER_WAIT_SECS = 0.8
    # ...except when the caller has already waited this long. A turn that
    # chains tools is a run of LLM round trips with no audio between them, and
    # every tool in it can be fast: on VS-8C1B760F1B capture_nonpayment_reason
    # (33ms) and revise_promise_to_pay (87ms) sat inside 6.3s of silence made
    # of three ~1.7s generations. The still-running rule never fired because
    # no tool was ever still running. By the second tool of such a turn the
    # caller has been waiting well past this, so the filler speaks at once.
    _CALLER_WAIT_FILLER_SECS = 2.0

    async def _speak_filler(phrase: str) -> None:
        try:
            await tts.queue_frame(TTSSpeakFrame(phrase, append_to_context=False))
        except TypeError:
            await tts.queue_frame(TTSSpeakFrame(phrase))
        except Exception:
            logger.exception("filler TTS failed")

    @llm.event_handler("on_function_calls_started")
    async def _on_function_calls_started(service, function_calls):
        calls = tuple(function_calls or ())
        try:
            from voice.call_trace import event, safe_tool_name, session_fields

            traced_names = [
                safe_tool_name(
                    getattr(call, "function_name", None) or getattr(call, "name", None)
                )
                for call in calls
            ]
            event(
                "tool.started",
                **session_fields(session),
                tools=",".join(name for name in traced_names if name) or None,
                count=len(calls),
            )
        except Exception as exc:
            logger.debug("tool start trace unavailable: {}", type(exc).__name__)
        if should_skip_filler(spoke_probe, tts):
            return
        names = []
        for call in calls:
            names.append(
                getattr(call, "function_name", None)
                or getattr(call, "name", None)
                or str(call)
            )
        phrase = filler_for_function_names([str(n) for n in names if n])
        if not phrase:
            return

        if bot_turn_state.caller_waiting_for() >= _CALLER_WAIT_FILLER_SECS:
            await _speak_filler(phrase)
            return

        async def _speak_if_still_waiting() -> None:
            try:
                await asyncio.sleep(_FILLER_WAIT_SECS)
            except asyncio.CancelledError:
                return
            if should_skip_filler(spoke_probe, tts):
                return
            if getattr(bot_turn_state, "_tool_calls", 0) <= 0:
                return
            await _speak_filler(phrase)

        asyncio.create_task(_speak_if_still_waiting())

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
