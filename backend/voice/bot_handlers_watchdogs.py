"""Voice handlers -- the max-duration and dead-air watchdogs.

One section of ``voice.bot_handlers.register_handlers``: the decorated
handlers that used to be closures inside it. ``build(scope)`` receives the
closure scope as a ``HandlerScope`` and unpacks what it reads; the six
mutable scalars the closures shared through ``nonlocal`` live on
``scope.hs`` (``HandlerState``). Bodies are otherwise byte-for-byte what
they were -- a move, pinned by ``tests/test_run_bot_pipeline_snapshot.py``.
"""

from __future__ import annotations

import asyncio

from loguru import logger


from voice.bot_handlers_scope import HandlerScope
from voice.bot_handlers_scope import (
    _DEADAIR_GRACE_SECS,
    _DEADAIR_MIN_SECS,
    _DEADAIR_POLL_SECS,
    _MAX_CALL_DURATION_SECS,
)


def build(scope: HandlerScope) -> None:
    """Register this section's handlers on the call's objects."""
    EndFrame = scope.EndFrame
    TTSSpeakFrame = scope.TTSSpeakFrame
    _claim_end = scope._claim_end
    _setup_trace = scope._setup_trace
    bot_turn_state = scope.bot_turn_state
    idle_timeout = scope.idle_timeout
    on_user_turn_idle = scope.on_user_turn_idle
    session = scope.session
    user_aggregator = scope.user_aggregator
    worker = scope.worker
    hs = scope.hs


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
                if hs.ending or session.extra.get("ending"):
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

    # Read by a later section, through the same scope object.
    scope._deadair_watchdog = _deadair_watchdog
    scope._max_duration_watchdog = _max_duration_watchdog
