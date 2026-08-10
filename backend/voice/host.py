"""Embedded voice worker host — run Pipecat bots inside the FastAPI process.

Closes the dual-port footgun in ``pipecat_unification_plan.md`` §2.6 / Phase E1:
today the CRM API listens on :8000 and a second ``python -m voice.bot`` process
listens on :7860, so a demo needs two processes started in the right order, two
tunnels (or the ``/ws`` proxy in :mod:`voice.ws_proxy`), and a browser whose
``/voice-rtc`` proxy points at the right one.

With ``VOICE_EMBEDDED_HOST=true`` the API serves the voice endpoints itself:

============================== ==========================================
``POST /voice-rtc/api/offer``  SmallWebRTC signalling (Sandbox Live)
``PATCH /voice-rtc/api/offer`` trickle ICE candidates
``/ws``                        Twilio Media Streams, served not proxied
============================== ==========================================

Both paths funnel into the *same* :func:`voice.bot.bot` entrypoint the
standalone runner uses, so transport construction, serializer wiring and the
Flows pipeline cannot drift between hosting modes. The only difference is
``runner_args.shared_runner``.

Every call joins one long-lived ``WorkerRunner(auto_end=False)`` — the pattern
:meth:`WorkerRunner.run` documents for exactly this case. ``auto_end=False``
matters: the default runner ends as soon as its last worker finishes, which for
a server means the host dies after the first call hangs up. ``handle_sigint=False``
matters too — the runner must not install signal handlers on uvicorn's event
loop and steal Ctrl-C from the API.

The standalone runner is unchanged and still the default; this is opt-in.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from env_loader import load_env

logger = logging.getLogger(__name__)

_runner: Any | None = None
_runner_task: asyncio.Task | None = None
_lock = asyncio.Lock()

# Strong refs for the per-call session tasks, matching _BG_TASKS in bot.py: the
# loop holds only a weak reference, so a task nobody references can be
# collected mid-call and cancelled without a trace.
_SESSION_TASKS: set[asyncio.Task] = set()


def embedded_host_enabled() -> bool:
    load_env()
    return (os.getenv("VOICE_EMBEDDED_HOST") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def get_runner() -> Any:
    """The process-wide runner, started on first use."""
    global _runner, _runner_task
    async with _lock:
        if _runner is not None:
            return _runner
        from pipecat.workers.runner import WorkerRunner

        runner = WorkerRunner(name="bigbound-voice-host", handle_sigint=False)
        # run() blocks until end()/cancel(); with auto_end=False it also blocks
        # while idle, which is what keeps the host alive between calls.
        _runner_task = asyncio.create_task(runner.run(auto_end=False))
        # Yield so run() gets a chance to start before the first add_workers.
        # Not load-bearing — add_workers on a not-yet-running runner queues the
        # worker and run()'s setup starts it — it just avoids the detour.
        await asyncio.sleep(0)
        _runner = runner
        logger.info("Embedded voice host runner started")
        return runner


async def shutdown() -> None:
    """Stop the host runner — called from the FastAPI lifespan."""
    global _runner, _runner_task
    async with _lock:
        runner, task = _runner, _runner_task
        _runner, _runner_task = None, None
    if runner is None:
        return
    try:
        await runner.cancel()
    except Exception:
        logger.exception("embedded voice host cancel failed")
    if task is not None:
        try:
            await asyncio.wait_for(task, timeout=10)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()
        except Exception:
            logger.exception("embedded voice host runner task failed")
    logger.info("Embedded voice host runner stopped")


async def release_worker(runner: Any, worker: Any) -> None:
    """Drop a finished call's worker from the runner's registry.

    ``WorkerRunner`` has no public detach and never prunes ``_entries`` itself —
    harmless in a one-call process, a slow leak in a host that outlives thousands
    of calls. Best-effort and version-tolerant: a Pipecat release that renames
    these internals costs us the pruning, not the call.
    """
    name = getattr(worker, "name", None)
    if not name:
        return
    try:
        entries = getattr(runner, "_entries", None)
        if isinstance(entries, dict):
            entries.pop(name, None)
        registry = getattr(runner, "_registry", None)
        unwatch = getattr(registry, "unwatch", None)
        if callable(unwatch):
            result = unwatch(name)
            if asyncio.iscoroutine(result):
                await result
    except Exception:
        logger.debug("worker registry prune failed for %s", name, exc_info=True)


def register_routes(app: Any) -> None:
    """Mount the SmallWebRTC signalling endpoints. No-op when disabled."""
    if not embedded_host_enabled():
        return
    try:
        from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
        from pipecat.transports.smallwebrtc.request_handler import (
            SmallWebRTCPatchRequest,
            SmallWebRTCRequest,
            SmallWebRTCRequestHandler,
        )
    except ImportError:
        logger.error(
            "VOICE_EMBEDDED_HOST=true but the SmallWebRTC transport is not installed — "
            "voice endpoints not mounted; run the standalone worker instead"
        )
        return

    handler = SmallWebRTCRequestHandler()

    async def _offer(request: SmallWebRTCRequest, session_id: str | None = None):
        # ``session_id`` mirrors the query parameter ``pipecat.runner.run``'s
        # own /api/offer accepts, and is how the browser's session id actually
        # arrives: the JS transport posts custom data as camelCase
        # ``requestData``, which FastAPI does not map onto the
        # ``SmallWebRTCRequest`` dataclass's ``request_data`` field. Reading
        # both keeps this route behaving identically to the standalone runner.
        async def _on_connection(connection: SmallWebRTCConnection) -> None:
            # Spawned rather than awaited: the bot coroutine lives for the whole
            # call, and the SDP answer has to be returned now.
            task = asyncio.create_task(
                _run_webrtc_session(connection, request.request_data, session_id)
            )
            _SESSION_TASKS.add(task)
            task.add_done_callback(_SESSION_TASKS.discard)

        return await handler.handle_web_request(
            request=request, webrtc_connection_callback=_on_connection
        )

    async def _ice_candidate(request: SmallWebRTCPatchRequest):
        await handler.handle_patch_request(request)
        return {"status": "success"}

    # Both paths: ``/api/offer`` is what the standalone runner serves, so a dev
    # proxy that strips the ``/voice-rtc`` prefix keeps working when its target
    # is switched from :7860 to the API. ``/voice-rtc/api/offer`` is what the
    # browser asks for when there is no proxy at all (production, same origin).
    for path in ("/api/offer", "/voice-rtc/api/offer"):
        app.post(path, include_in_schema=False)(_offer)
        app.patch(path, include_in_schema=False)(_ice_candidate)

    logger.info("Embedded voice host: /api/offer + /voice-rtc/api/offer mounted")


def _session_id_from(request_data: Any, query_session_id: str | None = None) -> str | None:
    """Session id for this connection: request body first, then the query param.

    ``voice.bot`` validates whatever lands here against the canonical ``VS-``
    shape, so passing a non-sandbox id through is harmless — it is simply
    ignored rather than mistaken for one of ours.
    """
    if isinstance(request_data, dict):
        sid = request_data.get("sessionId") or request_data.get("session_id")
        if sid:
            return str(sid)
    return str(query_session_id) if query_session_id else None


async def _run_webrtc_session(
    connection: Any, request_data: Any, query_session_id: str | None = None
) -> None:
    from pipecat.runner.types import SmallWebRTCRunnerArguments

    runner_args = SmallWebRTCRunnerArguments(
        webrtc_connection=connection,
        body=request_data,
        session_id=_session_id_from(request_data, query_session_id),
    )
    await _dispatch(runner_args, "webrtc")


async def run_websocket_session(websocket: Any) -> None:
    """Serve a Twilio Media Streams socket in-process (the ``/ws`` route).

    ``create_transport`` reads the provider handshake off the accepted socket
    and picks the serializer, so this only has to accept and hand over — the
    same sequence the standalone runner's ``/ws`` route performs.
    """
    from pipecat.runner.types import WebSocketRunnerArguments

    await websocket.accept()
    runner_args = WebSocketRunnerArguments(websocket=websocket)
    await _dispatch(runner_args, "media-stream")


async def _dispatch(runner_args: Any, label: str) -> None:
    from voice.bot import bot

    runner_args.handle_sigint = False
    runner_args.shared_runner = await get_runner()
    try:
        await bot(runner_args)
    except Exception:
        logger.exception("embedded %s session failed", label)
