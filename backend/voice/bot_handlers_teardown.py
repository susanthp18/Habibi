"""Voice handlers -- finalizing the call exactly once.

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
    _FINALIZE_BUDGET_SECS,
    _drain_tasks,
)


def build(scope: HandlerScope) -> None:
    """Register this section's handlers on the call's objects."""
    _setup_trace = scope._setup_trace
    audiobuffer = scope.audiobuffer
    bg_tasks = scope.bg_tasks
    emitter = scope.emitter
    kb_cache = scope.kb_cache
    runner_args = scope.runner_args
    session = scope.session
    sink = scope.sink
    transport = scope.transport
    worker = scope.worker
    hs = scope.hs



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
        if hs.finalized:
            return
        hs.finalized = True
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

            try:
                from voice.tools_verify import drop_crm_prefetch

                drop_crm_prefetch(session)
            except Exception:
                logger.debug("crm prefetch drop failed", exc_info=True)

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
                if hs.duration_task is not None and not hs.duration_task.done():
                    hs.duration_task.cancel()
                if hs.deadair_task is not None and not hs.deadair_task.done():
                    hs.deadair_task.cancel()
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

