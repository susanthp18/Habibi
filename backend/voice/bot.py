"""Production voice bot — Flows + CRM tools + persistence + recording (V3).

Shared brain from agent_core. Pipeline constructed from AgentTuning (§4.7).
Collections script via Pipecat Flows. Persistence via CrmSink (off audio path).
Audio after disclosure only.

Run:
  $env:PYTHONIOENCODING='utf-8'
  .\\.venv\\Scripts\\python.exe -m voice.bot
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import os

os.environ.setdefault("DB_PROCESS_ROLE", "voice")

from env_loader import load_env

load_env()

from loguru import logger

from voice import bot_flow, bot_handlers, bot_pipeline
from voice import config as voice_config
from voice import log_bridge
from voice.llm_pool import KeepAliveAzureLLMService

# The names tests and voice/host.py reach through this module. Their code
# moved with the functions that use them; the module keeps its surface.
from voice.bot_flow import (  # noqa: F401
    _persona_context,
    _sandbox_session_id_from,
    _system_instruction_from_bundle,
)
from voice.bot_handlers import (  # noqa: F401
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
)
from voice.bot_pipeline import _CONTEXT_SUMMARY_PROMPT, _WORKER_IDLE_TIMEOUT_SECS  # noqa: F401


async def run_bot(transport, runner_args) -> None:
    """One call, end to end: resolve, build, wire, run.

    The work lives in three siblings -- :mod:`voice.bot_flow` (which card and
    which conversation), :mod:`voice.bot_pipeline` (the services and the stages
    they form) and :mod:`voice.bot_handlers` (what happens once it is running).
    They share one per-call namespace, ``call``, in the order below; each step
    reads what the earlier ones wrote.
    """
    from pipecat.workers.runner import WorkerRunner

    # Strong refs for this call's fire-and-forget tasks — the loop only holds a
    # weak ref, so without this a prewarm task can be GC'd mid-flight and
    # silently cancelled. Per-call (not module-level) so an embedded host running
    # two calls cannot have one teardown reach into the other's tasks, and so the
    # set dies with the call instead of accumulating for the process lifetime.
    bg_tasks: set[asyncio.Task] = set()

    def _spawn_bg(coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        bg_tasks.add(task)
        task.add_done_callback(bg_tasks.discard)
        return task

    call = SimpleNamespace(
        transport=transport,
        runner_args=runner_args,
        bg_tasks=bg_tasks,
        _spawn_bg=_spawn_bg,
    )
    bot_flow.resolve_call(call)
    await bot_flow.load_mission(call)
    bot_pipeline.build_services(call)
    bot_handlers.make_developer_injectors(call)
    bot_flow.build_flow(call)
    await bot_pipeline.build_pipeline(call)
    bot_flow.make_flow_manager(call)
    bot_handlers.register_handlers(call)
    worker = call.worker

    # Embedded host (voice/host.py): a single long-lived runner owns every call,
    # so this session must join it instead of standing up a runner that owns the
    # process — a per-call runner would install signal handlers on the API's
    # event loop and end when its one worker finished.
    shared_runner = getattr(runner_args, "shared_runner", None)
    if shared_runner is not None:
        await shared_runner.add_workers(worker)
        # add_workers starts the worker on an already-running runner; the call
        # then lives until disconnect/idle cancels it above.
        return

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)
    await runner.run()


async def bot(runner_args):
    """Single entry point for every hosting mode — and so the admission gate.

    Both the embedded host (``voice.host._dispatch``) and the standalone
    ``python -m voice.bot`` runner land here, which is why the concurrency cap
    lives at this level rather than in the host: gating only the host would
    leave the compose stack's voice worker uncapped, and gating both would let
    one call consume two slots.
    """
    from voice import admission

    # Before create_transport: refusing after the transport is up means the
    # expensive part (STT/TTS connections, flow build) already happened, and the
    # caller has already heard the line open.
    try:
        slot_token = admission.acquire(label="voice")
    except admission.AtCapacity as exc:
        logger.warning("refusing call: {}", exc)
        await admission.refuse(runner_args, label="voice")
        return

    # The socket is already accepted by the time we get here: the caller is
    # connected and waiting while the pipeline is built. That readiness window
    # is therefore a hard limit on whether the call works at all — Twilio tears
    # the media stream down long before a slow build finishes, and the symptom
    # is a call that connects and then plays silence, with every status callback
    # still reporting success.
    #
    # Stamped here so `on_client_connected` can say how long the caller waited.
    # It is the one number that distinguishes "the bot is broken" from "the bot
    # was not ready in time", and nothing was measuring it.
    try:
        runner_args.setup_started_at = time.monotonic()
    except Exception:
        logger.debug("could not stamp setup start on runner_args", exc_info=True)

    try:
        await _bot_session(runner_args)
    finally:
        # finally, not after the await: a cancelled session (deploy drain,
        # client vanishing) must return its slot too, or the effective cap
        # ratchets down until the process serves nothing.
        admission.release(slot_token)


async def _bot_session(runner_args):
    from pipecat.evals.transport import EvalTransportParams
    from pipecat.runner.utils import create_transport
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams

    transport_params = {
        "eval": lambda: EvalTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
        "twilio": lambda: FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
        "webrtc": lambda: TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    }
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


def _ensure_utf8_stdio() -> None:
    """Pipecat banner uses box-drawing chars; Windows cp1252 cannot print them."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _warm_before_serving() -> None:
    """Pay the cold-start before a caller can arrive, not during their call.

    The first call after a restart runs every one-time cost inside the window
    the browser is waiting on: WebRTC has already sent its offer and is holding
    an unanswered handshake. On VS-22F820E252 the pipeline took 61s to become
    ready, the client re-offered at 70s, that renegotiation tore down the
    in-flight connection, and the call died at "Starting live voice session…"
    without ever connecting. The largest single number in that window was a
    62-second Azure warm-up.

    Doing it here costs the operator a slower `python -m voice.bot` and costs
    the first caller nothing. Best-effort: a runner that cannot reach Azure at
    boot must still start and serve.
    """
    try:
        import azure_openai

        ms = azure_openai.prewarm(force=True)
        if ms:
            logger.info("voice runner warm · azure {:.0f} ms · ready to take calls", ms)
    except Exception:
        logger.warning("startup warm failed — the first call pays it instead", exc_info=True)

    # The Postgres side of retrieval is cold too, and nothing warmed it: the
    # first vector query of a process builds a plan and pulls the HNSW index and
    # the TOASTed vectors off disk (182ms cold vs 0.84ms warm on the live
    # corpus). Separately, the cross-encoder — when it is switched on at all —
    # holds a one-off ONNX graph load that must not land inside a turn.
    try:
        import kb_retrieve

        kb_ms = kb_retrieve.prewarm()
        if kb_ms:
            logger.info("kb retrieval warm · {:.0f} ms", kb_ms)
    except Exception:
        logger.warning("kb warm failed — the first question pays it instead", exc_info=True)

    try:
        from agent_core.tools import kb_rerank

        if kb_rerank.prewarm():
            logger.info("kb reranker warm · model={}", kb_rerank.model_name())
    except Exception:
        logger.debug("kb reranker warm skipped", exc_info=True)

    # Silero VAD and Smart Turn v3 are ONNX models rebuilt per session, paid
    # inside the window the caller is holding an open, silent line.
    #
    # They cannot simply be shared between sessions: both carry per-stream
    # state, so two concurrent calls would analyse each other's audio. What *is*
    # shareable is everything underneath — the onnxruntime library, its thread
    # pools, and the model files in the OS page cache. Building one of each here
    # and discarding it pays for that once, at boot, where it costs the operator
    # a slower start and the caller nothing.
    #
    # Measured on this machine, cold build vs. warm rebuild:
    #     silero-vad   1374 ms -> 327 ms
    #     smart-turn    386 ms -> 215 ms
    # so roughly 1.2s comes off every call's setup. That is not the difference
    # between a fast call and a slow one; at the margin it is the difference
    # between a call and a carrier hanging up on a pipeline that was not ready.
    import time as _time

    # Imports first: they are the largest single cost and the one that made the
    # first call after every restart fail outright.
    started = _time.monotonic()
    warmed = _warm_run_bot_imports()
    logger.info(
        "voice runner warm · imports {}/{} modules {:.0f} ms",
        warmed, len(_RUN_BOT_MODULES), (_time.monotonic() - started) * 1000,
    )

    for label, build in (
        ("llm-service", _warm_llm_service),
        ("silero-vad", _warm_silero),
        ("smart-turn", _warm_smart_turn),
    ):
        started = _time.monotonic()
        try:
            build()
            # loguru, not stdlib logging: this module's logger formats with
            # `{}`. A `%s` here does not raise, it just prints the format string
            # — which is how the line above shipped reading "azure %.0f ms".
            logger.info(
                "voice runner warm · {} {:.0f} ms", label, (_time.monotonic() - started) * 1000
            )
        except Exception:
            logger.warning(
                "startup warm for {} failed — every call pays it instead", label
            )


#: Every module :func:`run_bot` imports on entry -- through :mod:`voice.bot_flow`,
#: :mod:`voice.bot_pipeline` and :mod:`voice.bot_handlers`, which hold its body.
#:
#: They are function-local there on purpose — importing them at module scope
#: pulls the whole pipeline runtime into anything that merely touches
#: ``voice.bot`` — but the cost has to be paid *somewhere*, and the default was
#: "inside the first caller's window". Measured on this machine that was **32.7
#: seconds**, against a carrier that stops waiting after a few. The first call
#: after every restart was therefore guaranteed to fail, and the second to
#: succeed, which is exactly the shape that gets misdiagnosed as flakiness.
#:
#: Loading them here only populates ``sys.modules``; ``run_bot``'s own imports
#: then hit the cache. It does not change what ``run_bot`` does, only when the
#: bill arrives. ``test_voice_session_teardown`` reads the AST of ``run_bot``
#: and its three siblings and fails if this list drifts behind them.
_RUN_BOT_MODULES: tuple[str, ...] = (
    "flow_graph",
    "pipecat.audio.vad.silero",
    "pipecat.extensions.voicemail.voicemail_detector",
    "pipecat.flows",
    "pipecat.flows.exceptions",
    "pipecat.frames.frames",
    "pipecat.observers.startup_timing_observer",
    "pipecat.observers.user_bot_latency_observer",
    "pipecat.pipeline.pipeline",
    "pipecat.pipeline.worker",
    "pipecat.processors.aggregators.llm_context",
    "pipecat.processors.aggregators.llm_response_universal",
    "pipecat.processors.audio.audio_buffer_processor",
    "pipecat.processors.frameworks.rtvi",
    "pipecat.services.azure.stt",
    "pipecat.utils.context.llm_context_summarization",
    "pipecat.workers.runner",
    "agent_core.cards.routing",
    "agent_core.context",
    "agent_core.deployment",
    "agent_core.providers",
    "agent_core.skills.runtime",
    # WP-031 step 1: the runtimes now forward channel_tools, so run_bot
    # reaches the catalog and its schema on the first call. Warm them or
    # that import cost lands mid-conversation.
    "agent_core.tools.catalog",
    "agent_core.tools.schema",
    "agent_core.tuning",
    "bank_boundary",
    "bank_boundary.snapshots",
    "db",
    "mission",
    "outbound",
    "sqlalchemy",
    "voice",
    "voice.amd",
    "voice.bot_turn_state",
    "voice.call_trace",
    "voice.flows_dynamic",
    "voice.host",
    "voice.ivr",
    "voice.kb_enrich",
    "voice.rtvi_events",
    "voice.tools",
    "voice.tts_pool",
    "voice.tuning_apply",
    "voice_session_store",
)


def _warm_run_bot_imports() -> int:
    """Import what the first call would otherwise import while someone waits.

    Best-effort per module: a runner that cannot import one optional dependency
    must still start and serve, and the call will pay for that one alone.
    """
    import importlib

    warmed = 0
    for name in _RUN_BOT_MODULES:
        try:
            importlib.import_module(name)
            warmed += 1
        except Exception:
            logger.warning("startup warm: {} would not import", name)
    return warmed


def _warm_llm_service() -> None:
    """Pay the LLM service's one-time class init at boot, not in a call.

    ``KeepAliveAzureLLMService(...)`` costs **2.46s on the first construction of
    the process and 0.00s on every one after it** -- measured, three builds in a
    row. The cost is lazy setup underneath the OpenAI SDK (client plumbing, TLS
    trust store), keyed to the process rather than the instance, so it is paid
    exactly once and then never again.

    Nothing warmed it. ``azure_openai.prewarm`` above warms the *HTTP* path, not
    this constructor, so the first caller after every restart wore the whole
    2.46s inside their setup window -- it was the single largest item in an
    8.38s time-to-greeting on session VS-BEDB3F54D7, larger than the VAD and
    Smart Turn model builds put together.

    Constructed with throwaway settings and discarded: only the process-wide
    initialisation is wanted, and no call is placed.
    """
    KeepAliveAzureLLMService(
        api_key=voice_config.azure_openai_voice_api_key(),
        endpoint=voice_config.azure_openai_voice_endpoint(),
        api_version=voice_config.azure_openai_voice_api_version(),
        settings=KeepAliveAzureLLMService.Settings(
            model=voice_config.azure_openai_voice_deployment(),
            system_instruction="warm",
        ),
    )


def _warm_silero() -> None:
    from pipecat.audio.vad.silero import SileroVADAnalyzer

    SileroVADAnalyzer()


def _warm_smart_turn() -> None:
    from voice.tuning_apply import build_smart_turn_analyzer

    build_smart_turn_analyzer({})


if __name__ == "__main__":
    _ensure_utf8_stdio()
    # Before anything imports and starts logging: without this the product's
    # standard-library loggers never reach loguru's sink. See voice/log_bridge.py.
    log_bridge.install()
    # The voice process is a bot. Which bot is a per-call fact the session
    # knows; the kind is a per-process fact, and it is what stops a call's
    # audit rows being signed by the default operator.
    import actor_context

    actor_context.bind_service_actor("bot")
    # The admission gauges are this process's; the collector reads the flag.
    os.environ.setdefault("VOICE_PROCESS", "1")
    import observability

    observability.serve_metrics()
    _warm_before_serving()
    from pipecat.runner.run import main

    main()
