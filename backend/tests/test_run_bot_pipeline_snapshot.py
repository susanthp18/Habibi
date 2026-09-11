"""The call ``run_bot`` assembles, pinned before ``voice/bot.py`` is taken apart.

``run_bot`` is one 2,100-line closure. Splitting it into pipeline, flow and
handler modules must not reorder a stage, drop a handler, change which node the
call opens on or what the model is handed first. This drives the *real*
``run_bot`` with a fake transport and stand-in services -- no network, no audio
-- far enough to see the pipeline it built, and compares the result against
``tests/snapshots/run_bot_pipeline.json``.

Regenerate deliberately, never to make a red run green:

    UPDATE_SNAPSHOTS=1 pytest tests/test_run_bot_pipeline_snapshot.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("pipecat.flows")

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "run_bot_pipeline.json"
BOT_ID = "kaia-v2-4"


def _stand_in(name: str, events: tuple[str, ...] = ()) -> type:
    """A real ``FrameProcessor`` subclass under the service's own class name.

    ``Pipeline`` links its processors at construction, so a bare object fails
    with ``no attribute 'link'``; and the snapshot records class names, so the
    stand-in must carry the name of the service it replaces.
    """
    from pipecat.processors.frame_processor import FrameProcessor

    class Settings:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        FrameProcessor.__init__(self, name=name)
        for event in events:
            self._register_event_handler(event)

    return type(name, (FrameProcessor,), {"__init__": __init__, "Settings": Settings})


class _Transport:
    """Both ends are real processors; every ``event_handler`` registration is kept."""

    def __init__(self) -> None:
        self._in = _stand_in("TransportInput")()
        self._out = _stand_in("TransportOutput")()
        self.handlers: dict[str, str] = {}

    def input(self):
        return self._in

    def output(self):
        return self._out

    def event_handler(self, name: str):
        def deco(fn):
            self.handlers[name] = fn.__name__
            return fn

        return deco


class _SharedRunner:
    """The embedded-host branch: ``run_bot`` hands over the worker and returns."""

    def __init__(self) -> None:
        self.workers: list[Any] = []

    async def add_workers(self, *workers: Any) -> None:
        self.workers.extend(workers)


def _patch_everywhere(monkeypatch: pytest.MonkeyPatch, attr: str, value: Any) -> None:
    """Rebind a name in every ``voice.bot*`` module that holds it.

    ``voice/bot.py`` binds its collaborators at module level, so a bare patch on
    the source module misses them; and the split moves those bindings into
    sibling modules, so the patch must not care which file owns the name today.
    """
    import voice.bot  # noqa: F401  -- make sure the family is loaded
    import voice.llm_pool  # noqa: F401

    for mod in list(sys.modules.values()):
        modname = getattr(mod, "__name__", "") or ""
        if (modname.startswith("voice.bot") or modname == "voice.llm_pool") and hasattr(mod, attr):
            monkeypatch.setattr(mod, attr, value)


def _handlers_on(obj: Any) -> list[str]:
    registered = getattr(obj, "_event_handlers", {}) or {}
    return sorted(name for name, entry in registered.items() if entry.handlers)


def _name_of(fn: Any) -> str:
    return getattr(fn, "name", None) or fn.__name__


def render(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from agent_core.cards import routing
    from agent_core.providers import factory
    from pipecat.pipeline import pipeline as pipeline_mod
    from voice import flows_dynamic
    from voice import tts_pool
    from pipecat.services.azure import stt as azure_stt

    recorded: dict[str, Any] = {}

    # The card under test, whatever the entry table says today.
    monkeypatch.setattr(routing, "resolve_entry", lambda *a, **k: BOT_ID)

    # No provider binding: every slot takes the Azure default, which is the
    # stand-in below. A binding would construct a real vendor client.
    def _no_binding(**_kwargs: Any) -> Any:
        raise factory.NoBindingError("pinned: no binding")

    monkeypatch.setattr(factory, "build_first_available", _no_binding)

    monkeypatch.setattr(azure_stt, "AzureSTTService", _stand_in("AzureSTTService"))
    monkeypatch.setattr(tts_pool, "KeepAliveAzureTTSService", _stand_in("KeepAliveAzureTTSService"))
    _patch_everywhere(
        monkeypatch,
        "KeepAliveAzureLLMService",
        _stand_in("KeepAliveAzureLLMService", events=("on_function_calls_started",)),
    )

    async def _no_prewarm(*_a: Any, **_k: Any) -> float:
        return 0.0

    _patch_everywhere(monkeypatch, "prewarm_shared_client", _no_prewarm)

    real_pipeline = pipeline_mod.Pipeline

    class _RecordingPipeline(real_pipeline):
        def __init__(self, processors, *args: Any, **kwargs: Any) -> None:
            recorded["processors"] = list(processors)
            super().__init__(processors, *args, **kwargs)

    monkeypatch.setattr(pipeline_mod, "Pipeline", _RecordingPipeline)

    real_build = flows_dynamic.build_authored_flow

    def _recording_build(session, graph_data, **kwargs: Any):
        result = real_build(session, graph_data, **kwargs)
        recorded["flow"] = result
        recorded["flow_kwargs"] = kwargs
        return result

    monkeypatch.setattr(flows_dynamic, "build_authored_flow", _recording_build)

    from voice import bot

    transport = _Transport()
    runner = _SharedRunner()
    runner_args = SimpleNamespace(
        body=None,
        session_id=None,
        call_data=None,
        transport_type="webrtc",
        handle_sigint=False,
        shared_runner=runner,
        setup_started_at=None,
    )
    asyncio.run(bot.run_bot(transport, runner_args))

    assert len(runner.workers) == 1, "run_bot must hand exactly one worker to the shared runner"
    worker = runner.workers[0]
    processors = recorded["processors"]
    state, _tools, initial_node, global_fns = recorded["flow"]
    kwargs = recorded["flow_kwargs"]
    node = initial_node()

    def _first(prefix: str) -> Any:
        return next(p for p in processors if type(p).__name__.startswith(prefix))

    user_aggregator = _first("LLMUserAggregator")
    llm = _first("KeepAliveAzureLLMService")
    context = user_aggregator.context

    return {
        "stages": [type(p).__name__ for p in processors],
        "handlers": {
            "transport": dict(sorted(transport.handlers.items())),
            "worker": _handlers_on(worker),
            "user_aggregator": _handlers_on(user_aggregator),
            "llm": _handlers_on(llm),
        },
        "flow": {
            "bot_id": kwargs.get("bot_id"),
            "channel": kwargs.get("channel"),
            "objective": kwargs.get("objective"),
            "entry_node": kwargs.get("entry_node"),
            "current_node": getattr(state, "current_node", None),
            "node_name": node.get("name"),
            "node_functions": sorted(_name_of(f) for f in node.get("functions", [])),
            "role_message_roles": [m.get("role") for m in node.get("role_messages", [])],
            "task_message_roles": [m.get("role") for m in node.get("task_messages", [])],
            "global_functions": sorted(_name_of(f) for f in global_fns),
            "allowed_tools": sorted(kwargs.get("allowed_tool_names") or []),
            "attached_skills": len(kwargs.get("attached_skills") or []),
            "specialists": sorted((kwargs.get("specialist_entries") or {}).keys()),
        },
        "context_message_roles": [m.get("role") for m in context.get_messages()],
    }


def test_run_bot_assembly_matches_the_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    current = json.dumps(render(monkeypatch), indent=2, sort_keys=True, default=str) + "\n"
    if os.getenv("UPDATE_SNAPSHOTS"):
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(current, encoding="utf-8")
    assert SNAPSHOT.exists(), "no snapshot yet: run once with UPDATE_SNAPSHOTS=1"
    pinned = SNAPSHOT.read_text(encoding="utf-8")
    assert current == pinned, (
        "run_bot assembles a different call; if that is intended, regenerate with "
        "UPDATE_SNAPSHOTS=1 and review the diff"
    )
