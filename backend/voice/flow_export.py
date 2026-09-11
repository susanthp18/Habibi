"""The built-in collections conversation, as an authored FlowGraph.

The Studio's Flow tab governed nothing for the live agent for a long time:
every card stored an empty graph, so every call ran ``voice/flows.py`` --
Python that no prompt version, publish or rollback could touch. That script
was materialised as a graph an author can open, edit and ship, and then
deleted; what it said now lives in ``agent_core/cards/graphs/collections.json``
as seed data. There is one conversation definition, it is data, and the
runtime (``voice/flows_dynamic.py``, ``flow_walk.py``) executes it the same
way it executes anything an author draws.

**Edges are implicit, on purpose.** The built-in tools transition by node key
(``disclose_recording`` moves to ``discover_intent``), which
``flow_graph.TRANSITIONS`` declares and the canvas draws. An ``always`` edge
would not mean the same thing -- it fires after the node has *spoken*, with no
tool involved -- so writing the tool hops down as edges would change the call.
The map is the declaration; ``tests/test_transitions_are_declared.py`` keeps
the handlers honest against it.

``part`` splits the one graph along ``_DOOR_KEYS``: ``"door"`` is greet and
disclose, discover, verify and the shared terminals; ``"servicing"`` is
everything else. A filter over one source, not a second copy.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import flow_graph as fg

#: Which half of the graph to emit. See ``built_in_collections_graph``.
Part = Literal["all", "door", "servicing"]

GRAPH_PATH = Path(__file__).resolve().parents[1] / "agent_core" / "cards" / "graphs" / "collections.json"

#: The door/servicing split is ``flow_graph.DOOR_KEYS`` -- owned there so the
#: compiler (which runs where pipecat is not installed) reads the same list.
_DOOR_KEYS = fg.DOOR_KEYS


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


def built_in_collections_graph(*, part: Part = "all") -> dict[str, Any]:
    """The built-in conversation as an authored graph (a deep copy per call)."""
    graph = copy.deepcopy(_load())
    if part == "door":
        graph["nodes"] = [n for n in graph["nodes"] if n["key"] in _DOOR_KEYS]
    elif part == "servicing":
        graph["nodes"] = [n for n in graph["nodes"] if n["key"] not in _DOOR_KEYS]
    keep = {n["key"] for n in graph["nodes"]}
    graph["edges"] = [
        e for e in graph.get("edges") or []
        if _node_key(graph, e["source"]) in keep and _node_key(graph, e["target"]) in keep
    ]
    return graph


def _node_key(graph: dict[str, Any], node_id: str) -> str | None:
    for n in _load()["nodes"]:
        if n["id"] == node_id:
            return n["key"]
    return None
