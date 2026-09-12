"""Voice handlers -- the silence ladder and the live-QA hooks.

One section of ``voice.bot_handlers.register_handlers``: the decorated
handlers that used to be closures inside it. ``build(scope)`` receives the
closure scope as a ``HandlerScope`` and unpacks what it reads; the six
mutable scalars the closures shared through ``nonlocal`` live on
``scope.hs`` (``HandlerState``). Bodies are otherwise byte-for-byte what
they were -- a move, pinned by ``tests/test_run_bot_pipeline_snapshot.py``.
"""

from __future__ import annotations

import time

from loguru import logger


from voice.bot_handlers_scope import HandlerScope
from voice.bot_handlers_scope import (
    _IDLE_REFIRE_GUARD_SECS,
)


def build(scope: HandlerScope) -> None:
    """Register this section's handlers on the call's objects."""
    EndFrame = scope.EndFrame
    EndWorkerFrame = scope.EndWorkerFrame
    LLMMessagesAppendFrame = scope.LLMMessagesAppendFrame
    TTSSpeakFrame = scope.TTSSpeakFrame
    _inject_developer = scope._inject_developer
    bot_turn_state = scope.bot_turn_state
    emitter = scope.emitter
    session = scope.session
    sink = scope.sink
    stt = scope.stt
    tts = scope.tts
    tuning = scope.tuning
    user_aggregator = scope.user_aggregator
    worker = scope.worker
    hs = scope.hs


    # Silence ladder (§6) — escalate nudge → direct → close.
    # When the ladder last fired. Two independent timers can now reach it —
    # Pipecat's UserIdleController and the dead-air watchdog below — and a
    # strike raised twice for one silence would skip a rung and hang up early.
    idle_ladder = list(tuning["interaction"].get("idle_ladder") or ["nudge", "direct", "close"])
    # Single-flight end: idle ladder / worker idle / max-duration must not stack
    # with each other or with Flows end_conversation (feedback #4).

    def _claim_end(reason: str) -> bool:
        if hs.ending or session.extra.get("ending"):
            logger.info(
                "Skip duplicate end · reason={} · session={}",
                reason,
                session.session_id,
            )
            return False
        hs.ending = True
        session.extra["ending"] = True
        # Read back by on_pipeline_finished so the finalized interaction records
        # why the call ended rather than a generic "bot_ended".
        session.extra.setdefault("ending_reason", reason)
        if hs.duration_task is not None and not hs.duration_task.done():
            hs.duration_task.cancel()
        if hs.deadair_task is not None and not hs.deadair_task.done():
            hs.deadair_task.cancel()
        return True

    @user_aggregator.event_handler("on_user_turn_idle")
    async def on_user_turn_idle(aggregator):
        # `ending` covers a call the *bot* is winding down. `finalized` covers a
        # call that is already over — chiefly the caller hanging up, which is the
        # ending this handler used to talk straight through. On VS-BEDB3F54D7 the
        # caller disconnected at 12:20:54 and this watchdog fired seven seconds
        # later, generating and synthesising "Are you still there?" into a dead
        # socket: billed LLM and TTS spend nobody could hear, a CRM drain pushed
        # past its timeout, and an admission slot held 121.1s for a 103.3s call.
        if hs.finalized or hs.ending or session.extra.get("ending"):
            return
        # Two timers, one ladder. The aggregator's timer and the dead-air
        # watchdog cover different silences and overlap in the middle; without
        # this, one quiet stretch can burn two rungs and close a call that had
        # only gone quiet once.
        now = time.monotonic()
        if hs.last_idle_fired and (now - hs.last_idle_fired) < _IDLE_REFIRE_GUARD_SECS:
            return
        hs.last_idle_fired = now
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
        hs.idle_strikes += 1
        step_idx = min(hs.idle_strikes - 1, len(idle_ladder) - 1)
        step = idle_ladder[step_idx]
        logger.info(
            "User idle · session={} · strike={} · step={}",
            session.session_id,
            hs.idle_strikes,
            step,
        )
        try:
            if hasattr(sink, "enqueue_alert"):
                await sink.enqueue_alert("silence", f"idle_strike_{hs.idle_strikes}")
        except Exception:
            pass
        await emitter.lifecycle(phase="idle", reason=f"{step}:{hs.idle_strikes}")

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

    # Read by a later section, through the same scope object.
    scope._claim_end = _claim_end
    scope._live_correction = _live_correction
    scope._live_escalate = _live_escalate
    scope._live_hold = _live_hold
    scope._live_language = _live_language
    scope._live_turn = _live_turn
    scope.on_user_turn_idle = on_user_turn_idle
