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
from dataclasses import dataclass
import dataclasses
import logging
from functools import wraps
from typing import Any, Awaitable, Callable

from flow_graph import GLOBAL_TOOLS_STRIPPED_AT_RUNTIME, FlowGraph, FlowNode, parse_graph
import flow_walk
from flow_vars import FlowVariables
from flow_graph import split_key
from flow_walk import EXTRACT_TOOL, TRANSITION_PREFIX, FlowWalker
from voice.node_contracts import NODE_DIRECTIVES
from voice.rtvi_events import RtviEmitter
from voice.session import VoiceSession
from voice.tools import (
    DeveloperInjector,
    DeveloperReplacer,
    build_tools,
)

logger = logging.getLogger(__name__)

AsyncStartRecording = Callable[[], Awaitable[None]]

#: The graph rules — which edge fires, what a step offers, how a name maps to a
#: node — live in ``flow_walk`` so the text mouths can ask the same questions.
#: Imported rather than re-typed: these names are the wire format between the
#: generated tools and the walker that reads them back.
_TYPE_JSON = flow_walk._TYPE_JSON


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
        # Left explicit rather than passing the bool through: this dict is a
        # context projection read at render time, not a value set through
        # FlowVariables.set, so it does not pass the boolean normalisation
        # there. Both doors spell it the same way, which is the point.
        "identity_verified": "true" if verified else "false",
        "outstanding": str(getattr(session, "outstanding", "") or ""),
        "turn_index": str(getattr(session, "turn_index", 0) or 0),
        "intent": _u("intent") or "",
        "sentiment": "" if sentiment is None else str(sentiment),
        "language": _u("language") or "",
    }


@dataclass
class FlowBuild:
    """One authored graph being compiled into pipecat-flows nodes: the graph, the
    entry, the walker and the variable bag, the built-in tools, and the
    transition helpers ``_flow_transition_helpers`` defines for
    ``_flow_node_factory`` to close over. The bodies are what
    ``build_authored_flow`` was; ``tests/test_flow_export.py`` and the flow
    suites pin what it compiles.
    """

    entry: FlowNode
    graph: FlowGraph
    nodes: dict[str, Callable[[], dict[str, Any]]]
    role_message: Any
    session: Any
    state: Any
    tools: dict[str, Any]
    variables: FlowVariables
    walker: FlowWalker
    _advance_action: Any = None
    _extract_tool: Any = None
    _make_factory: Any = None
    _transition_tool: Any = None
    _with_deterministic_followup: Any = None


def _flow_transition_helpers(st: FlowBuild) -> None:
    """The deterministic advance, the transition and extract tools, and the follow-up wrappers."""
    entry = st.entry
    nodes = st.nodes
    variables = st.variables
    walker = st.walker

    def _deterministic_target(node: FlowNode) -> FlowNode | None:
        return walker.deterministic_target(node)

    def _advance(node: FlowNode) -> dict[str, Any] | None:
        target = walker.deterministic_target(node)
        if target is None:
            return None
        factory = nodes.get(target.key)
        return factory() if factory else None

    # --- generated tools ---------------------------------------------------

    def _transition_tool(name: str, description: str) -> Any:
        """Wrap one of the walker's transitions as a Pipecat function.

        The name and the description come from ``walker.transitions`` so the
        text mouths offer the model the identical choice, worded identically.
        Everything Pipecat-shaped — the handler, the node factory it returns —
        stays here.
        """
        from pipecat.flows import FlowsFunctionSchema

        # Never re-split the name here: a namespaced key spells ``/`` as ``__``
        # in a function name, and a local key may itself contain ``__``. The
        # walker holds the forward map, so it is the only thing that can invert.
        target_key = walker.key_for_tool(name) or name[len(TRANSITION_PREFIX) :]

        async def _handler(flow_manager) -> tuple[Any, dict[str, Any] | None]:
            factory = nodes.get(target_key)
            if factory is None:
                logger.warning("authored flow: unknown target node %s", target_key)
                return {"ok": False, "error": "unknown_node"}, None
            return {"ok": True, "node": target_key}, factory()

        return FlowsFunctionSchema(
            name=name,
            description=description,
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

    st.entry = entry
    st._advance_action = _advance_action
    st._extract_tool = _extract_tool
    st._transition_tool = _transition_tool
    st._with_deterministic_followup = _with_deterministic_followup


def _flow_node_factory(st: FlowBuild) -> None:
    """One pipecat-flows node config per authored node, built lazily."""
    entry = st.entry
    role_message = st.role_message
    session = st.session
    state = st.state
    tools = st.tools
    variables = st.variables
    walker = st.walker
    _advance_action = st._advance_action
    _extract_tool = st._extract_tool
    _transition_tool = st._transition_tool
    _with_deterministic_followup = st._with_deterministic_followup

    # --- node compilation --------------------------------------------------

    def _make_factory(node: FlowNode) -> Callable[[], dict[str, Any]]:
        def _factory() -> dict[str, Any]:
            config: dict[str, Any] = {"name": node.key}

            # role_message persists across nodes until re-set; restate it on
            # whichever node the call *begins* at so the persona survives a
            # context reset. That is the inbound start node on an inbound call
            # and the mission's entry node on an outbound one — keying it to
            # isStart alone would open every outbound mission with no persona.
            if node.key == entry.key:
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
            # The grant of the member that owns this node, not the union. On a
            # flat graph `namespace` is None and this is a no-op; in a fleet it
            # is what stops a hop leaving the receiving specialist holding the
            # sending one's tools.
            namespace = split_key(node.key)[0]
            for key in node.data.tools:
                if not state.may_offer(key, namespace=namespace):
                    logger.debug(
                        "authored flow: %s is not on %s's grant at node %s",
                        key,
                        namespace,
                        node.key,
                    )
                    continue
                schema = tools.get(key)
                if schema is None:
                    logger.warning(
                        "authored flow: node %s references unknown tool %s",
                        node.key,
                        key,
                    )
                    continue
                functions.append(_with_deterministic_followup(node, schema))

            for name, description in walker.transitions(node):
                functions.append(_transition_tool(name, description))

            if node.data.extractVariables:
                functions.append(_extract_tool(node))

            config["functions"] = functions

            # A directive the runtime attaches by node key, declared in one
            # place so the editor can show it (`voice/node_contracts.py`).
            directive = NODE_DIRECTIVES.get(split_key(node.key)[1] or node.key)
            if directive:
                config.setdefault("task_messages", []).append(
                    {"role": "developer", "content": directive}
                )

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
            if any(
                e.data.condition.type != "prompt" for e in walker.edges_from(node)
            ):
                post_actions.append(_advance_action(node))
            if node.data.endConversation:
                post_actions.append({"type": "end_conversation"})
            if post_actions:
                config["post_actions"] = post_actions
            return config

        return _factory

    st._make_factory = _make_factory


def _flow_assemble(st: FlowBuild) -> tuple[Any, dict[str, Any], Callable[[], dict[str, Any]], list[Any]]:
    """Every node compiled, the surviving globals, and the entry."""
    entry = st.entry
    graph = st.graph
    nodes = st.nodes
    state = st.state
    tools = st.tools
    _make_factory = st._make_factory

    for node in graph.nodes:
        nodes[node.key] = _make_factory(node)

    # CRM reads belong on the node that is allowed to use them, not on
    # confirm_identity's first turn. The list lives on flow_graph so G16 can
    # warn the author that these globals will not be offered.
    global_functions = [
        tools[key]
        for key in graph.globalTools
        if key in tools and key not in GLOBAL_TOOLS_STRIPPED_AT_RUNTIME
    ]

    logger.info(
        "authored flow compiled · nodes=%s · edges=%s · entry=%s · globals=%s",
        len(graph.nodes),
        len(graph.edges),
        entry.key,
        len(global_functions),
    )
    if not graph.edges:
        logger.warning(
            "authored flow has zero compiled edges · nodes=%s · entry=%s — "
            "transitions will only happen when a tool returns a node",
            len(graph.nodes),
            entry.key,
        )
    return state, tools, nodes[entry.key], global_functions


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
    sink: Any | None = None,
    initial_variables: dict[str, Any] | None = None,
    allowed_tool_names: set[str] | None = None,
    attached_skills: list[Any] | None = None,
    agent_card: dict[str, Any] | None = None,
    objective: str | None = None,
    entry_node: str | None = None,
    specialist_grants: dict[str, set[str]] | None = None,
    specialist_entries: dict[str, str] | None = None,
) -> tuple[Any, dict[str, Any], Callable[[], dict[str, Any]], list[Any]]:
    """Compile an authored graph. Mirrors ``build_collections_flow``'s contract.

    ``objective`` selects which door the call comes in through. A graph declares
    its entries with ``FlowNodeData.entryFor``, so one graph serves the inbound
    caller and every outbound mission without the spine — negotiation, dispute,
    escalation, wrap-up — being duplicated per direction and then drifting.

    An unknown or unclaimed objective falls back to the inbound start node
    rather than raising: an authored graph that predates missions must keep
    behaving exactly as it did, and a mission with no door is a configuration
    error the *compiler* reports (G-OB2) rather than something to discover
    halfway through a dial.
    """
    graph: FlowGraph = parse_graph(graph_data)
    start = graph.start_node
    if start is None:
        raise ValueError("authored flow has no start node")
    # The card's chosen node wins when it names one: it is what the compiler
    # validated (G-OB2) and what the author saw on the canvas. The objective
    # lookup is the fallback for a mission placed without a card. Shared with
    # the text mouths so an outbound mission that starts three steps in does not
    # restart at "the phone rang" just because the sandbox chose for itself.
    entry = flow_walk.entry_node(graph, objective=objective, entry_key=entry_node) or start

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
        sink=sink,
        allowed_tool_names=allowed_tool_names,
        attached_skills=attached_skills,
        agent_card=agent_card,
        specialist_grants=specialist_grants,
        specialist_entries=specialist_entries,
    )

    # Who is speaking at the start. Mandatory on a merged graph, not cosmetic:
    # with this left None, `_node("wrap_up")` finds one `wrap_up` per member,
    # `resolve_key` calls that ambiguous and returns None, and every built-in
    # transition in the call stops working — the first fleet call would greet
    # and then sit there. On a flat graph `split_key` yields None and nothing
    # changes.
    from flow_graph import split_key as _split_key

    state.active_specialist = _split_key(entry.key)[0]

    # One walker, shared with the text mouths. It owns the edge rules, the node
    # index and the variable bag; this module owns everything about speaking.
    walker = FlowWalker(graph, variables, start=entry)

    session.extra.setdefault("flow_variables", variables)

    st = FlowBuild(
        entry=entry,
        graph=graph,
        nodes=nodes,
        role_message=role_message,
        session=session,
        state=state,
        tools=tools,
        variables=variables,
        walker=walker,
    )
    _flow_transition_helpers(st)
    _flow_node_factory(st)
    return _flow_assemble(st)
