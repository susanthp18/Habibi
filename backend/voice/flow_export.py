"""Materialise the built-in collections script as an authored FlowGraph.

The Studio's Flow tab governed nothing for the live agent: every card stored an
empty graph, so every call ran ``voice/flows.py`` — Python that no prompt
version, publish or rollback could touch. This turns that script into a graph
an author can open, edit and ship.

**Derived, not transcribed.** ``build_collections_flow`` is called with a stub
session and its node factories are invoked, so the instructions, per-node tool
sets and ``respond_immediately`` flags come from the same source the runtime
uses. Hand-copying 700 lines of tuned prompt text would drift on the first edit
to either side; ``test_flow_export.py`` asserts the two stay in step.

**Edges are mostly implicit.** The built-in tools transition by node key —
``disclose_recording`` calls ``_node("discover_intent")`` — and
``flow_graph.RESERVED_NODE_KEYS`` exists precisely so an authored graph that
uses those keys inherits the same hops. Naming the nodes correctly is what wires
the graph up; only the entry marker has to be authored.

**The goal-conditioned hub survives, as one node.** ``_goal_directive()`` looks
like a branch but is not a graph branch: both arms reach the same node with the
same tools and differ only in the developer text. So the export renders the hub
twice — once with no goal, once with a non-money goal — and emits a single node
carrying both arms under an explicit condition, with ``{{call_goal}}`` and
``{{call_goal_intent}}`` left live. Those resolve through
``flows_dynamic.session_variables``, which is what makes this expressible at all.
"""

from __future__ import annotations

from typing import Any, Callable

from voice.flows import MONEY_GOAL_INTENTS
from voice.session import VoiceSession

#: Top-to-bottom in call order, branches fanned sideways.
#:
#: Nodes are 256px wide and the Flow tab's canvas is a narrow column (the
#: inspector takes the other half), so the first left-to-right layout spanned
#: 2240px and fitted at ~0.2 zoom — every node an unreadable smudge. A tall
#: layout matches the pane's shape and fits near 0.5.
_LAYOUT: dict[str, tuple[int, int]] = {
    "greet_disclose": (0, 0),
    "discover_intent": (0, 150),
    "verify_identity": (0, 300),
    "terminate_politely": (-320, 300),
    "state_position": (0, 460),
    "collections_hub": (0, 460),
    "negotiate_ptp": (-320, 620),
    "handle_dispute": (0, 620),
    "gated_upsell": (320, 620),
    "wrap_up": (0, 780),
    "escalate_close": (320, 780),
    "pre_close": (0, 930),
    "call_ended": (0, 1080),
}

#: Order the nodes are emitted in. Anything the builder registers that is not
#: listed still ships — appended in registry order — so a new built-in node
#: cannot be silently dropped from the export.
_ORDER: tuple[str, ...] = (
    "greet_disclose",
    "discover_intent",
    "verify_identity",
    "state_position",
    "collections_hub",
    "negotiate_ptp",
    "handle_dispute",
    "gated_upsell",
    "wrap_up",
    "pre_close",
    "terminate_politely",
    "escalate_close",
    "call_ended",
)


#: Rendered into the goal-aware nodes so the placeholders survive into the
#: authored graph and resolve per call.
_GOAL_TEMPLATE = "{{call_goal}}"
_INTENT_TEMPLATE = "{{call_goal_intent}}"


def _stub_session(*, goal: str | None = None, intent: str | None = None) -> VoiceSession:
    """A session used only to render node factories.

    Two stubs are needed: the factories that read ``session.call_goal`` produce
    different text with and without one, and the export has to see both arms to
    write them down.
    """
    session = VoiceSession(session_id="FLOW-EXPORT", customer_id=None, interaction_id=None)
    session.call_goal = goal
    session.call_goal_intent = intent
    return session


def _tool_names(functions: list[Any], registry: dict[str, Any]) -> list[str]:
    """Registry keys for a node's ``functions`` list.

    A node's entries are a mix: some are Pipecat ``FlowsFunctionSchema`` objects
    carrying a ``name``, others are bare handler functions whose ``__name__`` is
    the private closure name, not the tool key. Reverse-mapping through the tool
    registry by identity is exact for both — reading ``.name`` alone silently
    dropped half of every node's tool list.
    """
    by_id = {id(spec): key for key, spec in (registry or {}).items()}
    out: list[str] = []
    for fn in functions or []:
        key = by_id.get(id(fn)) or getattr(fn, "name", None)
        if not key and isinstance(fn, dict):
            key = fn.get("name") or (fn.get("function") or {}).get("name")
        if key:
            out.append(str(key))
    return out


def _instructions(node: dict[str, Any]) -> str:
    parts = [
        str(m.get("content") or "")
        for m in node.get("task_messages") or []
        if isinstance(m, dict)
    ]
    return "\n".join(p for p in parts if p).strip()


def _entry_line(node: dict[str, Any]) -> str:
    """The node's spoken-on-entry bridge line, if it has one.

    ``voice/flows.py`` pairs every ``respond_immediately=False`` step with a
    ``tts_say`` pre-action — "Happy to set that up." — and that line is the only
    reason the step is not dead air. The export used to drop pre-actions
    entirely, so reloading the built-in script into the canvas produced a graph
    that *looked* identical and silently removed the bridge; a live call then
    sat mute for 24 seconds on ``negotiate_ptp``. Carry it across.
    """
    for action in node.get("pre_actions") or []:
        if not isinstance(action, dict) or action.get("type") != "tts_say":
            continue
        text = str(action.get("text") or "").strip()
        if text:
            return text
    return ""


def _node_json(
    key: str, node: dict[str, Any], *, index: int, tools: dict[str, Any]
) -> dict[str, Any]:
    x, y = _LAYOUT.get(key, (320 * index, 480))
    return {
        "id": f"n_{key}",
        "key": key,
        "type": "end" if key == "call_ended" else "conversation",
        "position": {"x": x, "y": y},
        "data": {
            "name": key.replace("_", " ").title(),
            "instructionType": "prompt",
            "instructions": _instructions(node),
            "isStart": key == "greet_disclose",
            "respondImmediately": bool(node.get("respond_immediately", True)),
            "entryLine": _entry_line(node),
            "tools": _tool_names(node.get("functions") or [], tools),
            "extractVariables": [],
            "endConversation": key == "call_ended",
        },
    }


def _registry(
    graph: str | None, session: VoiceSession
) -> tuple[dict[str, Callable[[], dict[str, Any]]], dict[str, Any], list[Any]]:
    from voice.flows import build_collections_flow

    state, tools, _initial, globals_ = build_collections_flow(
        session,
        role_message="",
        graph=graph or "legacy",
    )
    # ToolState.nodes is the live node registry the builder populates, and the
    # one the built-in transitions resolve node names against.
    return state.nodes, tools, globals_


def _merge_goal_arms(no_goal: str, with_goal: str) -> str:
    """One instruction carrying both arms of a goal-dependent node.

    Neither arm is a graph branch: both reach the same node with the same tools
    and differ only in developer text, so splitting them into two nodes would
    change the call's turn structure. Writing the condition into the instruction
    preserves the behaviour and makes it visible on the canvas.

    Two shapes exist and they need different wording — using one for both put
    "a money question the outstanding balance answers" on the *verification*
    node, which is nonsense and would steer the model wrongly:

    * **prepend** (``verify_identity``) — the goal-aware render is the plain one
      with a preamble in front, so only the preamble is conditional, and the
      condition is simply whether a goal has been stated;
    * **divergent** (the hub) — the two arms genuinely differ mid-text, and the
      condition really is money-shaped vs not.
    """
    if no_goal == with_goal:
        return no_goal
    if with_goal.endswith(no_goal):
        preamble = with_goal[: -len(no_goal)].strip()
        if preamble:
            return (
                f"IF the caller has already said why they called: {preamble}\n"
                "IF they have not said yet, skip that line entirely and do "
                "not invent a reason.\n\n"
                "Either way, then:\n"
                f"{no_goal}"
            )
    intents = ", ".join(sorted(MONEY_GOAL_INTENTS))
    return (
        f"IF the caller has stated no goal, or {_INTENT_TEMPLATE} is one of "
        f"[{intents}] — a money question the outstanding balance actually "
        "answers — follow this:\n"
        f"{no_goal}\n\n"
        "OTHERWISE the balance interrupts their goal rather than serving it, so "
        "follow this instead:\n"
        f"{with_goal}"
    )


def built_in_collections_graph(*, graph: str | None = None) -> dict[str, Any]:
    """The running built-in script, as an authored graph.

    ``graph`` picks the shape the same way the runtime does: the default
    multi-node script, or ``"hub"`` for the merged single-hub variant.
    """
    plain, tools, globals_ = _registry(graph, _stub_session())
    # A non-money intent so the goal-first arm renders. The goal *text* stays a
    # live template, so it survives into the graph and resolves per call.
    goal_reg, _t, _g = _registry(graph, _stub_session(goal=_GOAL_TEMPLATE, intent="dispute"))

    keys = [k for k in _ORDER if k in plain]
    keys += [k for k in plain if k not in keys]

    nodes: list[dict[str, Any]] = []
    for index, key in enumerate(keys):
        node = _node_json(key, plain[key](), index=index, tools=tools)
        alt = goal_reg.get(key)
        if alt is not None:
            node["data"]["instructions"] = _merge_goal_arms(
                node["data"]["instructions"], _instructions(alt())
            )
        nodes.append(node)

    return {
        "nodes": nodes,
        # Every scripted hop already comes from the built-in tools via
        # RESERVED_NODE_KEYS, so the export authors none. Adding your own edges
        # here is exactly the point of materialising it.
        "edges": [],
        "globalTools": _tool_names(globals_, tools),
    }
