"""Voice handlers -- what happens when the client connects.

One section of ``voice.bot_handlers.register_handlers``: the decorated
handlers that used to be closures inside it. ``build(scope)`` receives the
closure scope as a ``HandlerScope`` and unpacks what it reads; the six
mutable scalars the closures shared through ``nonlocal`` live on
``scope.hs`` (``HandlerState``). Bodies are otherwise byte-for-byte what
they were -- a move, pinned by ``tests/test_run_bot_pipeline_snapshot.py``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

from voice import budget
from voice.crm_sink import bind_session_start, mark_crm_degraded

from voice.bot_handlers_scope import HandlerScope
from voice.bot_handlers_scope import (
    _LOOP_LLM_BUDGET,
    _SLOW_SETUP_WARN_SECS,
)


async def _bind_crm_session(
    scope: HandlerScope,
    *,
    provider_call_id: str | None,
    mission_customer: str | None,
    direction: str,
    attempt_id: str | None,
) -> None:
    """The CRM bind, run beside the greeting as a task (see on_client_connected).

    Was a closure inside the handler; lifted out unchanged, reading the call's
    objects through the scope and the four values the handler derived."""
    _flow_holder = scope._flow_holder
    _inject_developer = scope._inject_developer
    _store = scope._store
    bot_id = scope.bot_id
    bundle = scope.bundle
    emitter = scope.emitter
    sandbox_session = scope.sandbox_session
    session = scope.session
    sink = scope.sink
    transport_name = scope.transport_name

    try:
        from voice import persist as _persist

        if mission_customer:
            mission_customer = await asyncio.to_thread(
                _persist.resolve_known_customer,
                mission_customer,
            )
            if mission_customer:
                logger.info(
                    "{} customer bound · customer={} · objective={} · attempt={}",
                    "Outbound mission" if direction == "outbound" else "Inbound ANI",
                    mission_customer,
                    session.extra.get("objective") or "?",
                    attempt_id or "?",
                )
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


def build(scope: HandlerScope) -> None:
    """Register this section's handlers on the call's objects."""
    ActionError = scope.ActionError
    EndFrame = scope.EndFrame
    FlowError = scope.FlowError
    FlowInitializationError = scope.FlowInitializationError
    FlowTransitionError = scope.FlowTransitionError
    InvalidFunctionError = scope.InvalidFunctionError
    TTSSpeakFrame = scope.TTSSpeakFrame
    _deadair_watchdog = scope._deadair_watchdog
    _flow_holder = scope._flow_holder
    _inject_developer = scope._inject_developer
    _max_duration_watchdog = scope._max_duration_watchdog
    _store = scope._store
    bot_id = scope.bot_id
    bot_turn_state = scope.bot_turn_state
    bundle = scope.bundle
    emitter = scope.emitter
    flow_manager = scope.flow_manager
    initial_node = scope.initial_node
    is_twilio = scope.is_twilio
    runner_args = scope.runner_args
    sandbox_load_error = scope.sandbox_load_error
    sandbox_persona = scope.sandbox_persona
    session = scope.session
    transport = scope.transport
    voicemail_detector = scope.voicemail_detector
    worker = scope.worker
    hs = scope.hs


    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        hs.idle_strikes = 0
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
        hs.duration_task = asyncio.create_task(_max_duration_watchdog())
        hs.deadair_task = asyncio.create_task(_deadair_watchdog())

        async def _loop_trip_watchdog() -> None:
            try:
                while True:
                    await asyncio.sleep(1.0)
                    if hs.ending or session.extra.get("ending"):
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
        # Existence check is a DB round-trip. It used to sit in front of
        # FlowManager.initialize, so the greeting waited on it. The bind
        # already runs beside the greeting and is the only consumer.
        mission_customer = raw_customer

        if raw_customer:
            from voice.tools_verify import start_crm_prefetch

            mission = session.extra.get("mission")
            mission = mission if isinstance(mission, dict) else {}
            start_crm_prefetch(
                session,
                customer_id=raw_customer,
                channel="sandbox_live" if sandbox_session else "voice",
                interaction_id=session.interaction_id,
                account_id=mission.get("accountId"),
                kb_snapshot_id=(bundle.get("kbSnapshotId") if isinstance(bundle, dict) else None),
                bot_id=bot_id,
                persona=sandbox_persona if isinstance(sandbox_persona, dict) else (
                    (bundle.get("persona") if isinstance(bundle, dict) else None)
                ),
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

        crm_bind_task = asyncio.create_task(
            _bind_crm_session(
                scope,
                provider_call_id=provider_call_id,
                mission_customer=mission_customer,
                direction=direction,
                attempt_id=attempt_id,
            )
        )
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

