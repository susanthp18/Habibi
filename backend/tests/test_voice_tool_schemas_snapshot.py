"""The voice tool surface, pinned byte for byte.

``voice/tools.py build_tools`` and ``voice/flows_dynamic.py`` are being taken
apart into a package. A pure move must not change one property, one required
field, one transition target or one node's function list. This renders all of
it -- the full-grant tool registry, every node of the collections graph as the
runtime compiles it, and the built-in transition map -- and compares against
``tests/snapshots/voice_tools.json``.

Regenerate deliberately, never to make a red run green:

    UPDATE_SNAPSHOTS=1 pytest tests/test_voice_tool_schemas_snapshot.py
"""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from typing import Any

import pytest

import flow_graph as fg
from voice.session import VoiceSession

pytest.importorskip("pipecat.flows")

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "voice_tools.json"


def _render_tool(fn: Any) -> dict[str, Any]:
    """One tool as the model would see it: a spec-rendered schema or a bare function."""
    from pipecat.flows import FlowsFunctionSchema

    if isinstance(fn, FlowsFunctionSchema):
        return {
            "kind": "schema",
            "description": fn.description,
            "properties": fn.properties,
            "required": sorted(fn.required or []),
            "cancel_on_interruption": fn.cancel_on_interruption,
            "timeout_secs": fn.timeout_secs,
            "handler": getattr(fn.handler, "__name__", None),
        }
    params = [p for p in inspect.signature(fn).parameters if p not in {"self", "flow_manager"}]
    return {"kind": "direct", "name": fn.__name__, "params": params}


def _name_of(fn: Any) -> str:
    return getattr(fn, "name", None) or fn.__name__


def _full_grant() -> set[str]:
    from agent_core.tools.catalog import CATALOG
    from voice.tools import ALWAYS_ON

    return set(CATALOG.specs) | set(ALWAYS_ON)


def render() -> dict[str, Any]:
    from tests.builtin_flow import build_collections_flow
    from voice.tools import build_tools

    _state, tools = build_tools(
        VoiceSession(session_id="VS-SNAPSHOT01"),
        bot_id=None,
        start_recording=None,
        nodes={},
        allowed_tool_names=_full_grant(),
    )
    registry = {name: _render_tool(fn) for name, fn in sorted(tools.items())}

    state, _tools, _entry, globals_ = build_collections_flow(
        VoiceSession(session_id="VS-SNAPSHOT02"),
        role_message="You are Priya.",
        allowed_tool_names=_full_grant(),
    )
    nodes: dict[str, Any] = {}
    for key, factory in sorted(state.nodes.items()):
        config = factory()
        nodes[key] = {
            k: v
            for k, v in config.items()
            if k in {"respond_immediately", "pre_actions", "post_actions"}
        }
        if "pre_actions" in nodes[key]:
            nodes[key]["pre_actions"] = [
                {sk: sv for sk, sv in action.items() if sk != "handler"}
                for action in nodes[key]["pre_actions"]
            ]
        nodes[key]["functions"] = sorted(_name_of(f) for f in config.get("functions", []))
        nodes[key]["task_message_roles"] = [m.get("role") for m in config.get("task_messages", [])]
    return {
        "registry": registry,
        "collections_nodes": nodes,
        "global_functions": sorted(_name_of(f) for f in globals_),
        "transitions": {k: list(v) for k, v in sorted(fg.TRANSITIONS.items())},
    }


def test_voice_tool_surface_matches_the_snapshot() -> None:
    current = json.dumps(render(), indent=2, sort_keys=True, default=str) + "\n"
    if os.getenv("UPDATE_SNAPSHOTS"):
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(current, encoding="utf-8")
    assert SNAPSHOT.exists(), "no snapshot yet: run once with UPDATE_SNAPSHOTS=1"
    pinned = SNAPSHOT.read_text(encoding="utf-8")
    assert current == pinned, (
        "the voice tool surface changed; if that is intended, regenerate with "
        "UPDATE_SNAPSHOTS=1 and review the diff"
    )
