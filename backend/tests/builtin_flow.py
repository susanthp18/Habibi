"""The built-in conversation, compiled the way the runtime compiles every graph.

``voice/flows.py`` -- the Python script -- is gone; its conversation is
``agent_core/cards/graphs/collections.json`` and ``voice/flows_dynamic.py``
executes it like any authored graph. Tests that used to build the script call
this instead, so they exercise the path a call actually takes.
"""

from __future__ import annotations

from typing import Any


def build_collections_flow(session: Any, *, role_message: str, **kwargs: Any):
    from voice.flow_export import built_in_collections_graph
    from voice.flows_dynamic import build_authored_flow

    kwargs.pop("graph", None)  # the hub variant is retired; one graph now
    return build_authored_flow(
        session, built_in_collections_graph(), role_message=role_message, **kwargs
    )
