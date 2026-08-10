"""Authored conversation flow — schema, validation and tool catalog.

The collections call script has always been a Pipecat Flows node graph, but it
lived in ``voice/flows.py`` as Python: changing the conversation meant editing
code and redeploying. This module is the data model for the same shape, so a
graph can be authored in the UI, versioned with the prompt it belongs to, and
executed by ``voice/flows_dynamic.py``.

Design notes, and where this deliberately differs from the obvious approach:

* **Nodes carry a ``key`` as well as an ``id``.** The id is the canvas's handle
  and is meaningless to the runtime. The key is the stable machine name the
  runtime transitions by. Deriving tool names from a node's *display name*
  (which is what the reference implementation this was modelled on does) means
  renaming a node silently renames its transition tool, and two nodes called
  "Wrap up" collide into one tool. A separate key makes both impossible.

* **Reserved keys interoperate with the built-in tools.** ``voice/tools.py``
  transitions by calling ``_node("verify_identity")`` and similar. Those resolve
  against whatever node dict the runtime hands it, so an authored graph that
  uses a reserved key inherits that built-in transition for free; one that does
  not simply never triggers it (``_node`` logs and stays put — it does not
  raise). :data:`RESERVED_NODE_KEYS` is surfaced in the editor so this is a
  visible choice rather than a trap.

* **Validation separates errors from warnings.** An all-or-nothing validator
  makes a half-built graph unsavable, so authors work around it by not saving.
  Errors block publish; warnings (an unreachable node, an end node with no way
  in) are advisory and are shown on the canvas while editing.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

# Node keys and variable names become identifiers in tool schemas.
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")

#: Node keys that ``voice/tools.py`` transitions to by name. An authored graph
#: is not required to define them; defining one wires up the corresponding
#: built-in transition. Keep in sync with the ``_node("…")`` calls there.
RESERVED_NODE_KEYS: dict[str, str] = {
    "discover_intent": "disclose_recording moves here once the greeting is spoken",
    "verify_identity": "capture_call_goal moves here once the caller states why they called",
    "terminate_politely": "refuse_verification / not_account_holder / failed verification",
    "negotiate_ptp": "begin_negotiate moves here",
    "handle_dispute": "begin_dispute moves here",
    "wrap_up": "begin_wrap_up and a completed promise-to-pay move here",
    "escalate_close": "escalate_to_human moves here",
    "state_position": "the hub that return_to_position comes back to",
    "collections_hub": "hub variant used when VOICE_FLOW_GRAPH=hub",
    "gated_upsell": "recommend_next_offer moves here when upselling is enabled",
    "call_ended": "terminal node after the farewell",
}

FlowInstructionType = Literal["prompt", "say"]
FlowVariableType = Literal["string", "number", "boolean"]
FlowConditionType = Literal["prompt", "expression", "always"]
FlowMatch = Literal["all", "any"]
FlowOperator = Literal[
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "greater_than",
    "greater_or_equal",
    "less_than",
    "less_or_equal",
    "exists",
    "not_exists",
]
#: Operators that ignore the right-hand side.
UNARY_OPERATORS = frozenset({"exists", "not_exists"})


class FlowPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = 0.0
    y: float = 0.0


class FlowVariable(BaseModel):
    """A value the node asks the model to extract from the caller."""

    model_config = ConfigDict(extra="forbid")

    key: str
    description: str = ""
    type: FlowVariableType = "string"


class FlowNodeData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "Untitled"
    #: "prompt" lets the model compose the turn; "say" speaks the text verbatim.
    instructionType: FlowInstructionType = "prompt"
    instructions: str = ""
    isStart: bool = False
    #: False makes the bot listen first — the node the caller is expected to
    #: open. Mirrors Pipecat's NodeConfig field of the same name.
    respondImmediately: bool = True
    #: Tool keys from the registry, exposed to the model while on this node.
    tools: list[str] = Field(default_factory=list)
    extractVariables: list[FlowVariable] = Field(default_factory=list)
    #: Ends the call after this node's speech finishes (post_actions).
    endConversation: bool = False


class FlowNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    type: Literal["conversation", "end"] = "conversation"
    position: FlowPosition = Field(default_factory=FlowPosition)
    data: FlowNodeData = Field(default_factory=FlowNodeData)


class FlowExpressionClause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variable: str
    operator: FlowOperator = "equals"
    value: str | None = None


class FlowCondition(BaseModel):
    """Why an edge fires.

    ``prompt``     — becomes a transition tool; the model decides.
    ``expression`` — evaluated against extracted variables, never shown to the model.
    ``always``     — unconditional; must be the node's only outgoing edge.
    """

    model_config = ConfigDict(extra="forbid")

    type: FlowConditionType = "prompt"
    prompt: str = ""
    match: FlowMatch = "all"
    clauses: list[FlowExpressionClause] = Field(default_factory=list)


class FlowEdgeData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition: FlowCondition = Field(default_factory=FlowCondition)


class FlowEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    target: str
    data: FlowEdgeData = Field(default_factory=FlowEdgeData)


class FlowGraph(BaseModel):
    """A complete authored conversation flow."""

    model_config = ConfigDict(extra="forbid")

    #: Schema version, so a future shape change can migrate stored graphs.
    version: int = 1
    #: Tools callable from any node (KB search, escalation, notes, end call).
    globalTools: list[str] = Field(default_factory=list)
    nodes: list[FlowNode] = Field(default_factory=list)
    edges: list[FlowEdge] = Field(default_factory=list)

    @property
    def start_node(self) -> FlowNode | None:
        return next(
            (n for n in self.nodes if n.type == "conversation" and n.data.isStart), None
        )


class FlowIssue(BaseModel):
    """One validation finding, addressed at a specific part of the graph."""

    model_config = ConfigDict(extra="forbid")

    severity: Literal["error", "warning"]
    code: str
    message: str
    nodeId: str | None = None
    edgeId: str | None = None


class FlowValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    issues: list[FlowIssue] = Field(default_factory=list)


def empty_graph() -> FlowGraph:
    """The two-node graph a new draft starts from."""
    return FlowGraph(
        version=1,
        globalTools=["search_knowledge_base", "escalate_to_human", "end_call"],
        nodes=[
            FlowNode(
                id="n-start",
                key="greet",
                type="conversation",
                position=FlowPosition(x=0, y=0),
                data=FlowNodeData(
                    name="Greeting",
                    isStart=True,
                    instructionType="prompt",
                    instructions=(
                        "Speak first — one short greeting that also says the call "
                        "is recorded for quality and compliance."
                    ),
                    tools=["disclose_recording"],
                ),
            ),
            FlowNode(
                id="n-end",
                key="call_ended",
                type="end",
                position=FlowPosition(x=0, y=240),
                data=FlowNodeData(name="End call", endConversation=True),
            ),
        ],
        edges=[
            FlowEdge(
                id="e-start-end",
                source="n-start",
                target="n-end",
                data=FlowEdgeData(
                    condition=FlowCondition(
                        type="prompt", prompt="The conversation is complete"
                    )
                ),
            )
        ],
    )


def parse_graph(raw: Any) -> FlowGraph:
    """Coerce stored JSON into a graph, tolerating an empty/absent value."""
    if not raw:
        return FlowGraph()
    if isinstance(raw, FlowGraph):
        return raw
    return FlowGraph.model_validate(raw)


def validate_graph(graph: FlowGraph, *, known_tools: Iterable[str] = ()) -> FlowValidation:
    """Structural check. Errors block publish; warnings are advisory.

    Deliberately does not require a non-empty graph: a draft mid-edit must stay
    savable, or authors stop saving.
    """
    issues: list[FlowIssue] = []
    tools = set(known_tools)

    def err(code: str, message: str, **loc: Any) -> None:
        issues.append(FlowIssue(severity="error", code=code, message=message, **loc))

    def warn(code: str, message: str, **loc: Any) -> None:
        issues.append(FlowIssue(severity="warning", code=code, message=message, **loc))

    # --- nodes ---
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    for node in graph.nodes:
        if node.id in seen_ids:
            err("duplicate_node_id", f"Duplicate node id {node.id!r}.", nodeId=node.id)
        seen_ids.add(node.id)

        if not _KEY_RE.match(node.key):
            err(
                "invalid_node_key",
                f"Node key {node.key!r} must be lowercase letters, digits and "
                "underscores, starting with a letter.",
                nodeId=node.id,
            )
        elif node.key in seen_keys:
            # Keys become transition tool names; a collision silently merges two
            # transitions into one.
            err(
                "duplicate_node_key",
                f"Node key {node.key!r} is used more than once.",
                nodeId=node.id,
            )
        seen_keys.add(node.key)

        if node.type == "conversation" and not node.data.instructions.strip():
            warn(
                "empty_instructions",
                f"Node {node.data.name!r} has no instructions.",
                nodeId=node.id,
            )

        for tool in node.data.tools:
            if tools and tool not in tools:
                err(
                    "unknown_tool",
                    f"Node {node.data.name!r} uses unknown tool {tool!r}.",
                    nodeId=node.id,
                )

        var_keys: set[str] = set()
        for var in node.data.extractVariables:
            if not _KEY_RE.match(var.key):
                err(
                    "invalid_variable_key",
                    f"Variable {var.key!r} must be lowercase letters, digits "
                    "and underscores.",
                    nodeId=node.id,
                )
            if var.key in var_keys:
                err(
                    "duplicate_variable",
                    f"Variable {var.key!r} is declared twice on {node.data.name!r}.",
                    nodeId=node.id,
                )
            var_keys.add(var.key)

    for tool in graph.globalTools:
        if tools and tool not in tools:
            err("unknown_tool", f"Unknown global tool {tool!r}.")

    starts = [n for n in graph.nodes if n.type == "conversation" and n.data.isStart]
    if graph.nodes and not starts:
        err("no_start", "Exactly one node must be marked as the start node.")
    elif len(starts) > 1:
        for node in starts:
            err(
                "multiple_starts",
                "More than one node is marked as the start node.",
                nodeId=node.id,
            )

    # --- edges ---
    by_id = {n.id: n for n in graph.nodes}
    seen_edge_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    outgoing: dict[str, list[FlowEdge]] = {}
    incoming: set[str] = set()

    for edge in graph.edges:
        if edge.id in seen_edge_ids:
            err("duplicate_edge_id", f"Duplicate edge id {edge.id!r}.", edgeId=edge.id)
        seen_edge_ids.add(edge.id)

        if edge.source not in by_id:
            err(
                "dangling_source",
                "Edge starts from a node that no longer exists.",
                edgeId=edge.id,
            )
            continue
        if edge.target not in by_id:
            err(
                "dangling_target",
                "Edge points at a node that no longer exists.",
                edgeId=edge.id,
            )
            continue

        pair = (edge.source, edge.target)
        if pair in seen_pairs:
            err(
                "duplicate_edge",
                "Two edges connect the same pair of nodes.",
                edgeId=edge.id,
            )
        seen_pairs.add(pair)

        if by_id[edge.source].type == "end":
            err(
                "edge_from_end",
                "An end node cannot transition anywhere.",
                edgeId=edge.id,
            )

        outgoing.setdefault(edge.source, []).append(edge)
        incoming.add(edge.target)

        cond = edge.data.condition
        if cond.type == "prompt" and not cond.prompt.strip():
            err(
                "empty_condition",
                "A prompt transition needs a condition describing when it fires.",
                edgeId=edge.id,
            )
        if cond.type == "expression":
            if not cond.clauses:
                err(
                    "empty_expression",
                    "An expression transition needs at least one clause.",
                    edgeId=edge.id,
                )
            for clause in cond.clauses:
                if not clause.variable.strip():
                    err(
                        "empty_clause_variable",
                        "An expression clause needs a variable.",
                        edgeId=edge.id,
                    )
                if (
                    clause.operator not in UNARY_OPERATORS
                    and not (clause.value or "").strip()
                ):
                    err(
                        "empty_clause_value",
                        f"Operator {clause.operator!r} needs a value.",
                        edgeId=edge.id,
                    )

    # An `always` edge fires unconditionally, so a sibling can never be taken.
    for source_id, edges in outgoing.items():
        if len(edges) > 1 and any(e.data.condition.type == "always" for e in edges):
            for edge in edges:
                if edge.data.condition.type == "always":
                    err(
                        "always_not_exclusive",
                        "An 'always' transition must be the node's only outgoing "
                        "transition — the others could never fire.",
                        edgeId=edge.id,
                    )

    # --- reachability (advisory) ---
    start = graph.start_node
    if start:
        reachable = _reachable_from(start.id, graph.edges)
        for node in graph.nodes:
            if node.id not in reachable and node.id != start.id:
                warn(
                    "unreachable",
                    f"Node {node.data.name!r} cannot be reached from the start node.",
                    nodeId=node.id,
                )
    for node in graph.nodes:
        if (
            node.type == "conversation"
            and node.id not in incoming
            and not node.data.isStart
            and node.id in by_id
        ):
            # Covered by "unreachable" when a start exists; this catches the
            # start-less draft case.
            if not start:
                warn(
                    "no_inbound",
                    f"Nothing transitions into {node.data.name!r}.",
                    nodeId=node.id,
                )

    return FlowValidation(
        ok=not any(i.severity == "error" for i in issues), issues=issues
    )


def _reachable_from(start_id: str, edges: list[FlowEdge]) -> set[str]:
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source, []).append(edge.target)
    seen = {start_id}
    stack = [start_id]
    while stack:
        for nxt in adjacency.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


#: Flow-control tools that exist only inside ``voice.tools.build_tools`` and so
#: are absent from the channel-agnostic ``agent_core.tools.CATALOG``.
#:
#: Declared rather than introspected because this module is imported by the API
#: process, which deliberately does not have pipecat installed — importing
#: ``voice.tools`` there would fail. ``tests/test_flow_tool_catalog.py`` runs in
#: the voice container and asserts this list plus the catalog equals exactly
#: what ``build_tools`` returns, so the two cannot drift apart silently.
_FLOW_CONTROL_TOOLS: dict[str, str] = {
    "disclose_recording": "Confirm the recording disclosure was spoken to the caller.",
    "verify_identity": "Verify caller identity before sharing any account details.",
    "refuse_verification": "Caller refuses to verify identity.",
    "not_account_holder": "Caller says they are not the account holder / third party.",
    "begin_negotiate": "Move to promise-to-pay negotiation when the caller wants a plan.",
    "begin_dispute": "Move to dispute handling when the caller disputes the balance.",
    "begin_wrap_up": "Move to call wrap-up when the caller is done.",
    "return_to_position": "Return to the account-position hub after a side path.",
    "pause_for_caller": "Caller asked to hold / wait a moment.",
    "end_call": "End the call when the caller says goodbye mid-conversation.",
}

#: Tools whose handlers return a next node of their own (see voice/tools.py).
#: Pairing one with graph edges on the same node gives the model two ways out.
_TRANSITIONING_TOOLS = frozenset(
    {
        "disclose_recording",
        "verify_identity",
        "refuse_verification",
        "not_account_holder",
        "begin_negotiate",
        "begin_dispute",
        "begin_wrap_up",
        "return_to_position",
        "create_promise_to_pay",
        "escalate_to_human",
        "recommend_next_offer",
        "end_call",
    }
)


def tool_catalog() -> list[dict[str, Any]]:
    """Tools an authored node may call, as the editor should offer them.

    Assembled from the pipecat-free ``agent_core.tools.CATALOG`` (filtered to
    the voice channel — ``identify_customer`` is text-only and would be dead
    weight on a call) plus :data:`_FLOW_CONTROL_TOOLS`.
    """
    from agent_core.tools import CATALOG

    entries: dict[str, str] = {}
    for key, spec in CATALOG.specs.items():
        channels = getattr(spec, "channels", None) or ()
        if "voice" not in channels:
            continue
        entries[key] = (getattr(spec, "description", "") or "").strip()
    entries.update(_FLOW_CONTROL_TOOLS)

    return [
        {
            "key": key,
            "description": entries[key],
            "transitions": key in _TRANSITIONING_TOOLS,
        }
        for key in sorted(entries)
    ]
