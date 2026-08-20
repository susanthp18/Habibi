"""Execute an authored flow graph as a Pipecat Flows conversation.

The counterpart to ``voice/flows.py``: same output contract
(``state, tools, initial_node_factory, global_functions``), but the graph comes
from ``prompt_versions.flow`` instead of Python. Selected by
``VOICE_FLOW_GRAPH=db`` or the default ``auto`` (when the published version
has nodes); ``legacy`` / ``hub`` keep the hardcoded flow, so this cannot
change a call until it is deliberately allowed.

How a graph becomes a conversation
----------------------------------
Every authored node compiles to a ``NodeConfig`` factory registered under the
node's ``key``. Its ``functions`` are the union of:

  * the business tools the author picked, straight from ``voice/tools.py`` —
    this is the whole point of authoring against Habibi's registry rather than
    prompt-only nodes: ``create_promise_to_pay`` still writes a real PTP;
  * one generated transition tool per ``prompt``-conditioned outgoing edge,
    named ``go_to_<target key>``, whose description is the author's condition
    text. The model transitions by choosing to call it;
  * an ``extract_details`` tool when the node declares variables.

``expression`` and ``always`` edges are never shown to the model — they are
evaluated deterministically, at two points:

  * **A ``function`` post-action.** Pipecat defers post-actions until
    ``BotStoppedSpeakingFrame`` and invokes them as ``handler(action,
    flow_manager)``, so the handler can ``await
    flow_manager.set_node_from_config(...)`` once the node has finished
    speaking. This is what makes "say this step, then move on" work with no tool
    call and no model involvement — an ``always`` node needs nothing else.
  * **After a tool handler on the node**, via a wrapper that fills in a next
    node only when the tool did not already pick one (so a built-in transition
    like ``begin_dispute`` still wins). This catches the case where a tool
    changed the variables an ``expression`` edge tests — chiefly
    ``extract_details`` — without waiting for the turn to end.

The post-action is a backstop, not a duplicate: by the time it runs, a tool that
already transitioned has moved the flow off this node, and ``_advance`` is
re-evaluated against the live variable bag either way.

Interoperating with the built-in tools
--------------------------------------
``voice/tools.py`` transitions by name — ``_node("verify_identity")`` — against
whatever registry it is handed. Authored nodes are registered under their key,
so a graph that uses a reserved key inherits that built-in transition. A graph
that does not simply never triggers it: ``_node`` logs and returns None, which
Pipecat reads as "stay here". See ``flow_graph.RESERVED_NODE_KEYS``.
"""

from __future__ import annotations

import copy
import dataclasses
import logging
from functools import wraps
from typing import Any, Awaitable, Callable

from flow_graph import FlowGraph, FlowNode, parse_graph
from voice.flow_vars import FlowVariables, evaluate_condition
from voice.rtvi_events import RtviEmitter
from voice.session import VoiceSession
from voice.tools import (
    DeveloperInjector,
    DeveloperReplacer,
    build_tools,
)

logger = logging.getLogger(__name__)

AsyncStartRecording = Callable[[], Awaitable[None]]

#: Prefix for generated edge-transition tools. Namespaced so an authored node
#: key can never collide with a business tool from the registry.
TRANSITION_PREFIX = "go_to_"
EXTRACT_TOOL = "extract_details"

_TYPE_JSON = {"string": "string", "number": "number", "boolean": "boolean"}


#: Live call state an authored graph may interpolate or branch on. Keys are the
#: contract the Flow editor advertises, so renaming one breaks published graphs.
SESSION_VARIABLES: tuple[str, ...] = (
    "call_goal",
    "call_goal_intent",
    "identity_verified",
    "outstanding",
    "turn_index",
    "intent",
    "sentiment",
    "language",
)


def session_variables(session: Any) -> dict[str, str]:
    """Project live call state into the flow variable bag.

    Read on every render and every edge evaluation rather than snapshotted at
    build time: ``call_goal`` is captured at the discover_intent node, long
    after the graph compiles, and it is the whole point of the
    goal-conditioned hub. A build-time snapshot would always be empty.

    Session-only and allocation-cheap — no database read, because this runs
    inside condition evaluation on the audio path.
    """
    understanding = getattr(session, "understanding", None)

    def _u(field: str) -> Any:
        return getattr(understanding, field, None) if understanding is not None else None

    verified = bool(getattr(session, "identity_verified", False))
    sentiment = _u("sentiment")
    return {
        "call_goal": getattr(session, "call_goal", None) or "",
        "call_goal_intent": getattr(session, "call_goal_intent", None) or "",
        # Lower-cased so an authored `equals true` clause matches — Python's
        # str(True) is "True" and the comparison is exact.
        "identity_verified": "true" if verified else "false",
        "outstanding": str(getattr(session, "outstanding", "") or ""),
        "turn_index": str(getattr(session, "turn_index", 0) or 0),
        "intent": _u("intent") or "",
        "sentiment": "" if sentiment is None else str(sentiment),
        "language": _u("language") or "",
    }


def build_authored_flow(
    session: VoiceSession,
    graph_data: Any,
    *,
    role_message: str,
    bot_id: str | None = None,
    start_recording: AsyncStartRecording | None = None,
    emitter: RtviEmitter | None = None,
    kb_snapshot_id: str | None = None,
    inject_developer: DeveloperInjector | None = None,
    replace_developer: DeveloperReplacer | None = None,
    persona: dict[str, Any] | None = None,
    channel: str = "voice",
    on_kb_tool_used: Callable[[], None] | None = None,
    spoke_this_response: Callable[[], bool] | None = None,
    on_upsell_engaged: Callable[[], None] | None = None,
    sink: Any | None = None,
    initial_variables: dict[str, Any] | None = None,
    allowed_tool_names: set[str] | None = None,
    attached_skills: list[Any] | None = None,
) -> tuple[Any, dict[str, Any], Callable[[], dict[str, Any]], list[Any]]:
    """Compile an authored graph. Mirrors ``build_collections_flow``'s contract."""
    graph: FlowGraph = parse_graph(graph_data)
    start = graph.start_node
    if start is None:
        raise ValueError("authored flow has no start node")

    variables = FlowVariables(initial_variables, context=lambda: session_variables(session))
    # Populated below; handed to build_tools by reference so the built-in tools'
    # _node(name) lookups see the authored nodes.
    nodes: dict[str, Callable[[], dict[str, Any]]] = {}

    state, tools = build_tools(
        session,
        bot_id=bot_id,
        start_recording=start_recording,
        nodes=nodes,
        emitter=emitter,
        kb_snapshot_id=kb_snapshot_id,
        inject_developer=inject_developer,
        replace_developer=replace_developer,
        persona=persona,
        channel=channel,
        on_kb_tool_used=on_kb_tool_used,
        spoke_this_response=spoke_this_response,
        on_upsell_engaged=on_upsell_engaged,
        sink=sink,
        allowed_tool_names=allowed_tool_names,
        attached_skills=attached_skills,
    )

    by_id = {node.id: node for node in graph.nodes}
    outgoing: dict[str, list[Any]] = {}
    for edge in graph.edges:
        if edge.source in by_id and edge.target in by_id:
            outgoing.setdefault(edge.source, []).append(edge)

    session.extra.setdefault("flow_variables", variables)

    def _deterministic_target(node: FlowNode) -> FlowNode | None:
        """First non-prompt edge whose condition holds."""
        for edge in outgoing.get(node.id, ()):
            if edge.data.condition.type == "prompt":
                continue
            if evaluate_condition(edge.data.condition, variables):
                return by_id.get(edge.target)
        return None

    def _advance(node: FlowNode) -> dict[str, Any] | None:
        target = _deterministic_target(node)
        if target is None:
            return None
        factory = nodes.get(target.key)
        return factory() if factory else None

    # --- generated tools ---------------------------------------------------

    def _transition_tool(node: FlowNode, edge: Any) -> Any:
        from pipecat.flows import FlowsFunctionSchema

        target = by_id[edge.target]

        async def _handler(flow_manager) -> tuple[Any, dict[str, Any] | None]:
            factory = nodes.get(target.key)
            if factory is None:
                logger.warning("authored flow: unknown target node %s", target.key)
                return {"ok": False, "error": "unknown_node"}, None
            return {"ok": True, "node": target.key}, factory()

        return FlowsFunctionSchema(
            name=f"{TRANSITION_PREFIX}{target.key}",
            # The author's condition text *is* the tool description — it is what
            # the model reads to decide. Rendered so {{variables}} resolve.
            description=variables.render(edge.data.condition.prompt)
            or f"Move to {target.data.name}",
            properties={},
            required=[],
            handler=_handler,
        )

    def _extract_tool(node: FlowNode) -> Any:
        from pipecat.flows import FlowsFunctionSchema

        properties: dict[str, Any] = {}
        for var in node.data.extractVariables:
            entry: dict[str, Any] = {"type": _TYPE_JSON.get(var.type, "string")}
            if var.description:
                entry["description"] = var.description
            properties[var.key] = entry

        async def _handler(args: dict[str, Any], flow_manager) -> tuple[Any, Any]:
            captured = {
                k: v for k, v in (args or {}).items() if k in properties and v is not None
            }
            variables.update(captured)
            # The variables these edges test just changed, so this is exactly
            # when a deterministic transition can newly become true.
            return {"ok": True, "captured": sorted(captured)}, _advance(node)

        return FlowsFunctionSchema(
            name=EXTRACT_TOOL,
            description=(
                "Record the details the caller has provided. Include only fields "
                "you are confident about; omit the rest."
            ),
            properties=properties,
            # Nothing is required: a partial answer must still be recordable.
            required=[],
            handler=_handler,
        )

    def _advance_action(node: FlowNode) -> dict[str, Any]:
        """A post-action that takes a deterministic edge once the node has spoken.

        Pipecat's built-in ``function`` action queues a ``FunctionActionFrame``
        and invokes it as ``handler(action, flow_manager)``; post-actions are
        deferred until ``BotStoppedSpeakingFrame``, i.e. the bot's turn is over.
        That is precisely "say this step, then move on", so an ``always`` or a
        satisfied ``expression`` edge fires without the model being involved.
        """

        async def _handler(action: dict[str, Any], flow_manager) -> None:
            target = _advance(node)
            if target is None:
                return
            try:
                await flow_manager.set_node_from_config(target)
            except Exception:
                # A failed transition must not kill the call — the caller stays
                # on this node, which is the same outcome as the edge not
                # matching, rather than dead air.
                logger.exception(
                    "authored flow: deterministic transition from %s failed", node.key
                )

        return {"type": "function", "handler": _handler}

    def _wrap_followup(node: FlowNode, inner: Callable[..., Any]) -> Callable[..., Any]:
        """Fill in a deterministic next node when the tool did not pick one."""

        @wraps(inner)
        async def _handler(*args: Any, **kwargs: Any):
            result = await inner(*args, **kwargs)
            if isinstance(result, tuple) and len(result) == 2:
                payload, next_node = result
                # A tool that chose its own node (begin_dispute and friends)
                # keeps that choice: the built-in transition is more specific
                # than the authored fallback.
                return payload, (next_node if next_node is not None else _advance(node))
            return result

        return _handler

    def _with_deterministic_followup(node: FlowNode, tool: Any) -> Any:
        """Let a business tool trigger a deterministic edge it did not choose.

        ``build_tools`` returns two shapes — a ``FlowsFunctionSchema`` for tools
        declared in the catalog, and a bare async function for the rest (9 of 25
        at the time of writing, including every ``begin_*`` hop). Both have to be
        wrapped, and the bare ones must keep ``__name__``, which is how Pipecat
        derives the tool name for them.
        """
        handler = getattr(tool, "handler", None)
        if handler is not None:
            wrapped = _wrap_followup(node, handler)
            # FlowsFunctionSchema is a dataclass in Pipecat 1.6 (not a pydantic
            # model), so replace() is the copy. Copy rather than mutate: the
            # schema objects come from build_tools' single registry dict and are
            # shared by every node that lists the tool — mutating one would give
            # every other node this node's deterministic follow-up.
            if dataclasses.is_dataclass(tool):
                return dataclasses.replace(tool, handler=wrapped)
            clone = copy.copy(tool)
            clone.handler = wrapped
            return clone
        if callable(tool):
            return _wrap_followup(node, tool)
        return tool

    # --- node compilation --------------------------------------------------

    def _make_factory(node: FlowNode) -> Callable[[], dict[str, Any]]:
        def _factory() -> dict[str, Any]:
            config: dict[str, Any] = {"name": node.key}

            # role_message persists across nodes until re-set; restate it on the
            # start node so the persona survives a context reset.
            if node.data.isStart:
                config["role_message"] = role_message

            if node.type == "end":
                config["task_messages"] = [
                    {
                        "role": "developer",
                        "content": variables.render(node.data.instructions)
                        or "Close the call politely in one short sentence.",
                    }
                ]
                config["functions"] = []
                config["respond_immediately"] = True
                config["post_actions"] = [{"type": "end_conversation"}]
                return config

            instructions = variables.render(node.data.instructions)
            entry_line = variables.render(node.data.entryLine).strip()
            if node.data.instructionType == "say" and instructions:
                # Verbatim delivery: say exactly this, do not improvise.
                config["pre_actions"] = [{"type": "tts_say", "text": instructions}]
                config["task_messages"] = [
                    {
                        "role": "developer",
                        "content": (
                            "You have just said the scripted line for this step. "
                            "Do not repeat it. Continue from the caller's reply."
                        ),
                    }
                ]
            else:
                if entry_line:
                    # Spoken the instant the step is entered, ahead of any
                    # generation. append_text_to_context=False keeps it out of
                    # the transcript the model reasons over, matching how the
                    # built-in script uses its bridge lines.
                    config["pre_actions"] = [
                        {
                            "type": "tts_say",
                            "text": entry_line,
                            "append_text_to_context": False,
                        }
                    ]
                config["task_messages"] = [
                    {"role": "developer", "content": instructions}
                ]

            functions: list[Any] = []
            for key in node.data.tools:
                schema = tools.get(key)
                if schema is None:
                    logger.warning(
                        "authored flow: node %s references unknown tool %s",
                        node.key,
                        key,
                    )
                    continue
                functions.append(_with_deterministic_followup(node, schema))

            edges = outgoing.get(node.id, [])
            prompt_edges = [e for e in edges if e.data.condition.type == "prompt"]
            for edge in prompt_edges:
                functions.append(_transition_tool(node, edge))

            if node.data.extractVariables:
                functions.append(_extract_tool(node))

            config["functions"] = functions

            # "Listen first" is a claim about whose turn it is, and the graph
            # cannot know that — only the call can. A step entered because the
            # CALLER just spoke owes them a reply: waiting produces silence
            # neither side will break. On VS-92CDE3F088 the caller answered
            # "payment plan discussion", begin_negotiate moved the flow to a
            # listen-first step, and the line stayed dead for 24 seconds until
            # the caller gave up and spoke again. Pipecat's idle ladder cannot
            # rescue this: UserIdleController only arms its timer on
            # BotStoppedSpeakingFrame, and no bot turn ever happened.
            #
            # An entry line settles the debt on its own, so a step that speaks
            # on entry may still listen.
            respond = bool(node.data.respondImmediately)
            if not respond and not entry_line:
                if (getattr(session, "last_speaker", None) or "") == "customer":
                    logger.info(
                        "authored flow: node %s responds immediately — the caller "
                        "spoke last and listening again would be dead air",
                        node.key,
                    )
                    respond = True
            config["respond_immediately"] = respond

            post_actions: list[dict[str, Any]] = []
            # Deterministic edges are resolved by a post-action rather than by a
            # tool the model has to choose to call. Tool handlers on this node
            # can still take one earlier (see _wrap_followup); this is the
            # backstop for the turn ending without any tool having run, which is
            # the whole of an `always` node's life.
            if any(e.data.condition.type != "prompt" for e in edges):
                post_actions.append(_advance_action(node))
            if node.data.endConversation:
                post_actions.append({"type": "end_conversation"})
            if post_actions:
                config["post_actions"] = post_actions
            return config

        return _factory

    for node in graph.nodes:
        nodes[node.key] = _make_factory(node)

    global_functions = [
        tools[key] for key in graph.globalTools if key in tools
    ]

    logger.info(
        "authored flow compiled · nodes=%s · edges=%s · start=%s · globals=%s",
        len(graph.nodes),
        len(graph.edges),
        start.key,
        len(global_functions),
    )
    return state, tools, nodes[start.key], global_functions
