"""Voice tools -- the recording disclosure and the call goal.

One section of the voice tool set: the handlers that used to be closures
inside ``voice.tools.build_tools``. ``build(ctx)`` receives the closure
scope as a ``ToolBuildContext`` and unpacks the names it reads, so every
handler body below is byte-for-byte what it was -- a move, pinned by
``tests/test_voice_tool_schemas_snapshot.py``.
"""

from __future__ import annotations

import asyncio
import time
import logging
from typing import Any

# Not `from pipecat.flows import ...` directly: this module is the trunk the
# built-in flow export hangs off, and the API image has no pipecat. See
# agent_core/tools/pipecat_compat.py — under pipecat these are pipecat's own
# objects and nothing about a call changes.
from agent_core.tools.pipecat_compat import flows_tool_options

from agent_core.intent import NON_GOAL_INTENTS
from agent_core.tools.catalog import (
    CATALOG,
)
from voice import persist

from voice.tool_state import (
    ToolBuildContext,
)

logger = logging.getLogger(__name__)

_RECORDING_UNAVAILABLE_CALLBACK = (
    "We cannot continue this call. Please call us back, and we will try you again."
)


async def _fail_closed_recording(
    flow_manager: Any,
    *,
    session: Any,
    greeting: str,
    already_spoke: bool,
) -> None:
    """The tape never started: they still hear the notice and a callback, then we hang up."""
    from pipecat.frames.frames import EndFrame, TTSSpeakFrame

    session.mark_ending("recording_unavailable")
    worker = getattr(flow_manager, "worker", None) or getattr(flow_manager, "_worker", None)
    if worker is not None:
        if not already_spoke:
            try:
                await worker.queue_frame(TTSSpeakFrame(greeting, append_to_context=False))
            except TypeError:
                await worker.queue_frame(TTSSpeakFrame(greeting))
            except Exception:
                logger.exception("recording-unavailable disclosure failed")
        try:
            await worker.queue_frame(
                TTSSpeakFrame(_RECORDING_UNAVAILABLE_CALLBACK, append_to_context=False)
            )
        except TypeError:
            await worker.queue_frame(TTSSpeakFrame(_RECORDING_UNAVAILABLE_CALLBACK))
        except Exception:
            logger.exception("recording-unavailable callback failed")
        try:
            await worker.queue_frame(EndFrame())
        except Exception:
            logger.exception("recording-unavailable EndFrame failed")
    attempt_id = (session.extra or {}).get("attempt_id")
    if not attempt_id:
        return

    def _mark() -> None:
        import db as dbmod
        import outbound

        with dbmod.engine.begin() as conn:
            outbound.mark(
                conn,
                str(attempt_id),
                state=outbound.STATE_RECORDING_UNAVAILABLE,
            )

    try:
        await asyncio.to_thread(_mark)
    except Exception:
        logger.exception("recording_unavailable attempt mark failed")


def build(ctx: ToolBuildContext) -> dict[str, Any]:
    """The tools of this section, keyed by the variable name build_tools used."""
    _FALLBACK_GREETING = ctx._FALLBACK_GREETING
    _node = ctx._node
    _spec = ctx._spec
    bot_id = ctx.bot_id
    inject_developer = ctx.inject_developer
    rtvi = ctx.rtvi
    session = ctx.session
    spoke_this_response = ctx.spoke_this_response
    start_recording = ctx.start_recording
    state = ctx.state



    @flows_tool_options(cancel_on_interruption=False)
    async def disclose_recording(flow_manager) -> tuple[Any, dict[str, Any] | None]:
        """Confirm the recording disclosure was spoken to the caller.

        Call this immediately after stating that the call is being recorded.
        """
        # Joining the CRM bind, not re-serialising it.
        #
        # The bind used to sit in front of the greeting and cost 5.92s of
        # silence; it was moved beside it, and it is genuinely concurrent with
        # the greeting's LLM turn and TTS. By the time the model emits this tool
        # call, the bind has had all of that to finish, so the residual wait is
        # usually zero -- and it cannot simply be dropped, because the
        # compliance record this tool writes is keyed on the interaction_id the
        # bind produces. Timing out would trade an audible pause for a missing
        # disclosure record, which is the wrong way round.
        #
        # So: measure it. If `bind_wait_ms` turns out to be non-trivial in
        # production, the fix is to start the bind earlier, not to abandon it.
        bind_task = (session.extra or {}).get("_crm_bind_task")
        if not session.interaction_id and bind_task is not None:
            waited_t0 = time.monotonic()
            try:
                await bind_task
            except Exception:
                logger.exception("crm bind failed before disclosure")
            waited_ms = (time.monotonic() - waited_t0) * 1000.0
            if waited_ms >= 100:
                try:
                    from voice.call_trace import event as _trace_event
                    from voice.call_trace import session_fields

                    _trace_event(
                        "disclose.bind_wait",
                        **session_fields(session),
                        bind_wait_ms=int(waited_ms),
                    )
                except Exception:
                    logger.debug("bind wait trace failed", exc_info=True)
        ix = session.interaction_id
        if not ix:
            return {"error": "no_interaction"}, None
        # This tool asserts that the caller HEARD the disclosure, and that
        # assertion becomes a compliance record. The model is supposed to speak
        # the greeting in the same reply as the call, and usually does — but on
        # VS-18FE21E37A it emitted the tool call with no text at all. Nothing
        # was said, the next node was listen-first, and the call sat mute for 77
        # seconds while the database recorded a disclosure that never happened.
        #
        # So say it here. This is the opening turn of a phone call: there is no
        # caller utterance to fall back on and no later turn that repairs it,
        # which makes it the one place a scripted line is more trustworthy than
        # an instruction.
        spoke = spoke_this_response is None or spoke_this_response()
        fallback_ok = False
        if spoke_this_response is not None and not spoke_this_response():
            # Same handle pause_for_caller speaks through — the FlowManager does
            # not expose the pipeline task directly.
            worker = getattr(flow_manager, "worker", None) or getattr(
                flow_manager, "_worker", None
            )
            if worker is None:
                logger.error("no worker to speak through — call will open silent")
            else:
                from pipecat.frames.frames import TTSSpeakFrame

                logger.warning(
                    "greeting was silent — model called disclose_recording without "
                    "speaking; delivering the disclosure directly"
                )
                try:
                    await worker.queue_frame(
                        TTSSpeakFrame(_FALLBACK_GREETING, append_to_context=False)
                    )
                    fallback_ok = True
                except TypeError:
                    await worker.queue_frame(TTSSpeakFrame(_FALLBACK_GREETING))
                    fallback_ok = True
                except Exception:
                    logger.exception("fallback greeting failed — call may open silent")
        if not (spoke or fallback_ok):
            return {
                "error": "disclosure_not_spoken",
                "say": (
                    "state that this call is recorded for quality and compliance, "
                    "then call disclose_recording again"
                ),
            }, None
        if not state.disclosure_done:
            if start_recording is not None:
                try:
                    await start_recording()
                except Exception:
                    logger.exception("start_recording failed")
                    await _fail_closed_recording(
                        flow_manager,
                        session=session,
                        greeting=_FALLBACK_GREETING,
                        already_spoke=bool(spoke or fallback_ok),
                    )
                    return {"error": "recording_unavailable", "disclosed": True}, None
            await asyncio.to_thread(
                persist.record_disclosure,
                interaction_id=ix,
                label="Recording disclosure",
                rule_id="rule-recording",
                read_at_sec=session.at_sec(),
                bot_id=bot_id,
            )
            state.disclosure_done = True
            # Close the loop deterministically rather than hoping the prompt
            # holds. The obligation is once-per-call, the tool is the moment it
            # is satisfied, and a standing developer note is the only signal
            # that survives every later node transition and context summary.
            # Without it a call disclosed at the greeting and then said it
            # twice more, four minutes apart (VS-92CDE3F088).
            if inject_developer is not None:
                try:
                    await inject_developer(
                        [
                            {
                                "role": "developer",
                                "content": (
                                    "The recording disclosure has been made and "
                                    "logged for this call. It is satisfied. Never "
                                    "state, repeat or re-confirm that the call is "
                                    "recorded again for the rest of this call, "
                                    "even if an instruction elsewhere says to "
                                    "always disclose it."
                                ),
                            }
                        ]
                    )
                except Exception:
                    logger.debug("disclosure note injection failed", exc_info=True)
        await rtvi.lifecycle(phase="disclosed", reason="recording_disclosure")
        # discover_intent asks what the caller needs before the verification
        # ceremony. `or _node("verify_identity")` is not defensive noise: a
        # caller that built tools with an older node registry would otherwise
        # get None back from _node and strand the call on the greeting.
        return {"ok": True, "disclosed": True}, (
            _node("discover_intent") or _node("verify_identity")
        )

    async def _capture_call_goal_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        args = CATALOG.normalize("capture_call_goal", args)
        goal = str(args.get("goal_summary") or "").strip()
        if not goal:
            return (
                {"error": "empty_goal", "say": "ask what they need, then call again"},
                None,
            )
        goal = goal[:200]

        # Intent classification, best available *now*. The LLM understanding for
        # this turn runs on the CrmSink analysis queue and usually lands a turn
        # or two later — _handle_understanding upgrades call_goal_intent when it
        # does. Until then the keyword baseline stands, which is the same
        # keyword-first / LLM-refines contract analyze_turn uses internally.
        intent: str | None = None
        try:
            from agent_core.understanding import keyword_understanding

            cached = session.understanding
            if cached is not None and session.understanding_turn_index >= session.turn_index:
                intent = getattr(cached, "intent", None)
            else:
                intent = keyword_understanding(goal).intent
        except Exception:
            logger.debug("call goal intent classification failed", exc_info=True)

        # A question about the call is not a reason for the call. Reuse the
        # classifier already running on every turn rather than pattern-matching
        # the phrasing: whatever it labels as meta stays unrecorded, the model
        # answers it, and discover_intent keeps listening for the real reason.
        # Asking for a person is not a question to answer and move past: it is the
        # request. Treated as meta, the tool told the model to "ask what they
        # actually need" and a caller who said "I want to speak to a human agent"
        # was asked why they called, then left in silence.
        if intent == "escalation":
            return (
                {
                    "ok": False,
                    "reason": "wants_a_human",
                    "say": "acknowledge in one short sentence, then call escalate_to_human now",
                },
                None,
            )
        if intent in NON_GOAL_INTENTS:
            return (
                {
                    "ok": False,
                    "reason": "not_a_call_goal",
                    "intent": intent,
                    "say": (
                        "answer their question directly, then ask what they "
                        "actually need help with today"
                    ),
                },
                None,
            )

        session.call_goal = goal
        session.call_goal_intent = intent
        session.call_goal_turn_index = session.turn_index

        await rtvi.lifecycle(phase="goal_captured", reason=goal)
        return (
            {"ok": True, "goal": goal, "say": "acknowledge briefly, then verify them"},
            _node("verify_identity"),
        )

    capture_call_goal = _spec("capture_call_goal", _capture_call_goal_handler)

    return {
        "disclose_recording": disclose_recording,
        "capture_call_goal": capture_call_goal,
    }
