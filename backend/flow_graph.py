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

import logging
import re
from functools import lru_cache
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# Node keys and variable names become identifiers in tool schemas.
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")

#: Node keys that ``voice/tools.py`` transitions to by name. An authored graph
#: is not required to define them; defining one wires up the corresponding
#: built-in transition. Keep in sync with the ``_node("…")`` calls there.
RESERVED_NODE_KEYS: dict[str, str] = {
    # `confirm_identity` is deliberately NOT here. Reserved keys are the nodes
    # `voice/tools.py` transitions to *by name*; the outbound door is reached by
    # being dialled, which is what `FlowNodeData.entryFor` expresses. Reserving
    # it would claim a built-in transition that does not exist.
    "third_party": "not_account_holder moves here on an outbound leg",
    "discover_intent": "disclose_recording moves here once the greeting is spoken",
    "verify_identity": "capture_call_goal moves here once the caller states why they called",
    "terminate_politely": "refuse_verification / not_account_holder / failed verification",
    "negotiate_ptp": "begin_negotiate moves here",
    "handle_dispute": "begin_dispute moves here",
    "wrap_up": "begin_wrap_up and a completed promise-to-pay move here",
    "escalate_close": "escalate_to_human moves here",
    "state_position": "the hub that return_to_position comes back to",
    "pre_close": "the close probe moves here before the farewell",
    "collections_hub": "hub variant used when VOICE_FLOW_GRAPH=hub",
    "gated_upsell": "recommend_next_offer moves here when upselling is enabled",
    "call_ended": "terminal node after the farewell",
}

#: The missions an outbound agent can be sent on. A node claims one or more of
#: these in ``entryFor`` and becomes the place that conversation *starts*.
#:
#: Declared here rather than on the Agent Card because the validator has to
#: check a claim without importing the card package — and because the graph is
#: the thing that has to contain a matching node. ``agent_core.cards.schema``
#: re-exports it so an author sees one list, not two.
OBJECTIVES: tuple[str, ...] = (
    "inbound",
    "pre_due_reminder",
    "bounce_cure",
    "dpd_reminder",
    "broken_ptp_chase",
    "hardship_intake",
    "mandate_reregistration",
    "document_chase",
    "callback_honour",
    "welcome_onboarding",
    "retention_save",
    "cross_sell",
    "manual_outbound",
)

#: Objectives whose contact is made *in order to sell something*, which under
#: DPDP purpose limitation needs a consent basis of its own rather than the one
#: captured to service the loan.
#:
#: Only ``cross_sell`` is on this list, and the omissions are the interesting
#: part. ``retention_save`` is a call about a product the borrower already
#: holds — keeping an existing relationship is servicing it, not marketing to
#: them. ``welcome_onboarding`` explains the first EMI. A collections call that
#: happens to reach a gated offer is not here either: whether an offer folded
#: into a servicing conversation makes that conversation promotional is the open
#: question in section 18.1 of the outbound design doc, and it belongs to the
#: client's compliance officer rather than to this frozenset.
PROMOTIONAL_OBJECTIVES: frozenset[str] = frozenset({"cross_sell"})


def data_purpose_for(objective: str | None) -> str:
    """``servicing`` or ``promotional`` for a mission objective."""
    return "promotional" if str(objective or "") in PROMOTIONAL_OBJECTIVES else "servicing"

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
    #: Missions that *begin* at this node. An outbound call is not the inbound
    #: script with a different greeting: we chose the borrower, the moment and
    #: the reason, so asking them why we called is absurd. A graph therefore
    #: needs more than one way in.
    #:
    #: Deliberately additive to ``isStart`` rather than replacing it. ``isStart``
    #: is where an inbound caller lands and stays exactly one node — a graph with
    #: two "the phone rang" entries is ambiguous. ``entryFor`` is where a mission
    #: lands, and each mission has exactly one. The spine after the first two or
    #: three nodes is shared, which is the whole reason this is one graph with
    #: several doors rather than several graphs that drift.
    entryFor: list[str] = Field(default_factory=list)
    #: False makes the bot listen first — the node the caller is expected to
    #: open. Mirrors Pipecat's NodeConfig field of the same name.
    respondImmediately: bool = True
    #: Fixed line spoken the moment this step is entered, before anything else.
    #: This is what makes ``respondImmediately: False`` survivable on a step the
    #: caller is transitioned into: the built-in script pairs every such step
    #: with one ("Happy to set that up."), and a graph that could not express it
    #: silently turned those steps into dead air on the live call.
    entryLine: str = ""
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

    def entry_for(self, objective: str | None) -> FlowNode | None:
        """The node a mission starts at, or None to fall back to ``start_node``.

        ``inbound`` resolves to the start node when no node claims it, so a graph
        authored before missions existed keeps behaving exactly as it did.
        """
        key = (objective or "").strip()
        if not key:
            return None
        node = next(
            (n for n in self.nodes if n.type == "conversation" and key in n.data.entryFor),
            None,
        )
        if node is None and key == "inbound":
            return self.start_node
        return node

    def entry_objectives(self) -> dict[str, str]:
        """objective -> node key, for the compiler and the Studio canvas."""
        out: dict[str, str] = {}
        for node in self.nodes:
            if node.type != "conversation":
                continue
            for objective in node.data.entryFor:
                out.setdefault(objective, node.key)
        return out


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


class FlowInvalidError(Exception):
    """Raised when a graph must not be published. Maps to HTTP 422, not 409."""

    def __init__(self, validation: FlowValidation):
        self.validation = validation
        super().__init__("flow_invalid")

    def http_detail(self) -> dict[str, Any]:
        return {
            "code": "flow_invalid",
            "issues": [
                i.model_dump()
                for i in self.validation.issues
                if i.severity == "error"
            ],
        }


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


def is_unauthored(raw: Any) -> bool:
    """True only for the built-in-script sentinel: no nodes AND no edges.

    "No nodes" on its own is a weaker claim and was the one being made. A row
    holding zero nodes and one or more edges is not a card that declined to
    author a flow — it is a corrupted graph, and every check that abbreviated
    the sentinel test to ``not nodes`` waved it through: ``assert_publishable``
    returned before reaching the dangling-edge rules, the compile gate passed,
    the canvas skipped validation, and the studio printed "No authored flow"
    over it.

    That mattered precisely because the two rows are otherwise identical from
    the outside. kaia's published v1_4 stores the genuine ``{nodes: [], edges:
    []}``; a corrupted edge-only row looked exactly like it to anything counting
    nodes, so the corruption had nowhere left to surface.

    Unparseable JSON is not unauthored either — it is broken, and saying so is
    ``assert_publishable``'s job.
    """
    try:
        graph = parse_graph(raw)
    except Exception:
        return False
    return not graph.nodes and not graph.edges


def is_authored(raw: Any) -> bool:
    """True when the stored JSON is a real graph, not the built-in-script sentinel."""
    return not is_unauthored(raw)


def assert_publishable(
    raw: Any, *, known_tools: Iterable[str] | None = None
) -> FlowGraph:
    """Empty graph is allowed (runtime uses the built-in script). Errors are not.

    Drafts stay savable with half-built graphs; *publish* is the compiler.
    """
    try:
        graph = parse_graph(raw)
    except Exception as exc:
        raise FlowInvalidError(
            FlowValidation(
                ok=False,
                issues=[
                    FlowIssue(
                        severity="error",
                        code="invalid_schema",
                        message=f"Flow graph is not valid JSON for this schema: {exc}",
                    )
                ],
            )
        ) from exc
    # Only the true sentinel skips validation. See `is_unauthored`: a graph with
    # edges and no nodes used to return here untouched, which is how an
    # edge-only row reached production wearing "no authored flow".
    if not graph.nodes and not graph.edges:
        return graph
    tools = (
        list(known_tools)
        if known_tools is not None
        else [t["key"] for t in tool_catalog()]
    )
    result = validate_graph(graph, known_tools=tools)
    if not result.ok:
        raise FlowInvalidError(result)
    return graph


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

    # --- mission entry points ---
    #
    # One node per mission, and only conversation nodes. Two nodes claiming the
    # same mission is not a preference the runtime can resolve — it would pick
    # whichever the node list happened to order first, so a graph edit could
    # silently change what a borrower hears without changing anything visible.
    claimed: dict[str, list[FlowNode]] = {}
    for node in graph.nodes:
        for objective in node.data.entryFor:
            if objective not in OBJECTIVES:
                err(
                    "unknown_objective",
                    f"{objective!r} is not a mission this system knows. "
                    f"One of: {', '.join(OBJECTIVES)}.",
                    nodeId=node.id,
                )
                continue
            if node.type != "conversation":
                err(
                    "entry_on_end_node",
                    "A call cannot begin at an end step.",
                    nodeId=node.id,
                )
                continue
            claimed.setdefault(objective, []).append(node)
    for objective, nodes in claimed.items():
        if len(nodes) > 1:
            for node in nodes:
                err(
                    "duplicate_entry",
                    f"More than one step is the entry for {objective!r}. "
                    "Exactly one step must begin each mission.",
                    nodeId=node.id,
                )
    # An entry step that listens first with nothing to say is dead air on a call
    # *we* placed — the borrower answered and heard silence. Tolerable on the
    # inbound start node, where the caller speaks first by definition.
    for objective, nodes in claimed.items():
        if objective == "inbound":
            continue
        for node in nodes:
            if not node.data.respondImmediately and not node.data.entryLine.strip():
                err(
                    "silent_outbound_entry",
                    "This step begins an outbound call but neither speaks first "
                    "nor has an entry line — the borrower would answer to silence.",
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

        if edge.source == edge.target:
            # A node that transitions to itself. The runtime compiles it into a
            # transition tool whose only destination is the node the model is
            # already on, so the call can never leave; on the canvas it draws as
            # a stub hidden behind the card, so the author cannot see what they
            # made. Nothing legitimate needs one — staying put is what happens
            # when no transition fires.
            err(
                "self_edge",
                "A step cannot transition to itself.",
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

    # --- redundant with a built-in hop (advisory) ---
    # An authored edge to a node a tool on the same source already transitions
    # to gives the model two routes to one place: the business tool, plus the
    # transition tool this edge compiles into. Not wrong — an author may want an
    # explicit path — but invisible, because the canvas hides the ghost edge
    # once an authored one covers the same pair.
    hops = implicit_transitions()
    if hops:
        key_of = {n.id: n.key for n in graph.nodes}
        tools_of = {n.id: set(n.data.tools) for n in graph.nodes}
        for edge in graph.edges:
            target_key = key_of.get(edge.target)
            if not target_key:
                continue
            covered = sorted(
                tool
                for tool in tools_of.get(edge.source, ())
                if target_key in hops.get(tool, ())
            )
            if covered:
                warn(
                    "redundant_with_tool",
                    f"{', '.join(covered)} already moves the call to "
                    f"{target_key!r}, so this transition is a second route to "
                    "the same node.",
                    edgeId=edge.id,
                )

    # --- reachability (advisory) ---
    start = graph.start_node
    if start:
        reachable = _reachable_from(start.id, graph.edges)
        for node in graph.nodes:
            if node.id in reachable or node.id == start.id:
                continue
            # A reserved key *is* an inbound path: the built-in tool named in
            # RESERVED_NODE_KEYS transitions to it by name, without an authored
            # edge. Warning here made every graph that interoperates with the
            # built-in tools open with a screenful of false positives — worst of
            # all the materialised collections script, where all 11 non-start
            # nodes are reached exactly that way.
            if node.key in RESERVED_NODE_KEYS:
                continue
            # A mission entry is reached by being dialled, not by an edge.
            if node.data.entryFor:
                continue
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
            and not node.data.entryFor
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
    from agent_core.cards.schema import LOCKED_MOUTH_TOOLS
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
            "locked": key in LOCKED_MOUTH_TOOLS,
        }
        for key in sorted(entries)
    ]


# ---------------------------------------------------------------------------
# Implicit transitions
# ---------------------------------------------------------------------------
# The built-in tools move the conversation by node key — ``_node("wrap_up")``
# — so an authored graph that uses a reserved key inherits that hop without any
# authored edge. Correct at runtime, invisible in the editor: the materialised
# collections script has twelve nodes and zero edges, and rendered as a pile of
# disconnected rectangles with no way to see what leads where.
#
# Derived by parsing ``voice/tools.py`` rather than importing it: this is called
# from the API process, and importing the voice tools drags in Pipecat.


def _tools_source() -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parent / "voice" / "tools.py").read_text(
        encoding="utf-8"
    )


@lru_cache(maxsize=1)
def implicit_transitions() -> dict[str, list[str]]:
    """tool key → node keys that tool transitions to.

    Three passes over one AST: the ``_node("x")`` calls each function makes
    directly, the intra-module calls each function makes, and the
    ``tools = {...}`` registry literal binding a tool key to its handler.

    The call graph matters. Most tools are thin wrappers that delegate — the
    registry binds ``"escalate_to_human"`` to a function whose body calls
    ``_escalate_to_human_handler``, and that helper owns the ``_node`` call.
    Reading only the registered function found 8 of the 14 real transitions, so
    the canvas drew ``escalate_close`` as an orphan and hid the route from
    verification to a polite termination. Following delegation is the fix that
    keeps working when someone extracts another helper; matching helper names
    would not.

    A tool missing from the result simply does not move the conversation.
    """
    import ast

    try:
        tree = ast.parse(_tools_source())
    except (OSError, SyntaxError):  # pragma: no cover - source always present
        logger.warning("could not parse voice/tools.py for transitions", exc_info=True)
        return {}

    # Node keys reachable through a name rather than a literal. The hub is
    # transitioned to as ``_node(hub_node)``, where hub_node is a parameter
    # defaulting to "state_position" — so a literals-only reader drew the busiest
    # node in the graph with nothing pointing at it. Resolved from parameter
    # defaults and simple string assignments, which is where a node key can
    # come from without becoming unknowable to static reading.
    literals: dict[str, set[str]] = {}

    def _remember(name: str, value: Any) -> None:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            literals.setdefault(name, set()).add(value.value)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            positional = [*args.posonlyargs, *args.args]
            for arg, default in zip(positional[len(positional) - len(args.defaults) :], args.defaults):
                _remember(arg.arg, default)
            for arg, default in zip(args.kwonlyargs, args.kw_defaults):
                if default is not None:
                    _remember(arg.arg, default)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    _remember(target.id, node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                _remember(node.target.id, node.value)

    direct: dict[str, set[str]] = {}
    calls: dict[str, set[str]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        hits: set[str] = set()
        callees: set[str] = set()
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id == "_node":
                if not node.args:
                    continue
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    hits.add(first.value)
                elif isinstance(first, ast.Name):
                    hits |= literals.get(first.id, set())
            else:
                callees.add(node.func.id)
        direct[fn.name] = hits
        calls[fn.name] = callees

    # Tools are registered two ways. Some entries name a plain function; others
    # name a binding built by a factory —
    # ``capture_call_goal = _spec("capture_call_goal", _capture_call_goal_handler)``
    # — and the registry then refers to that binding, which is not a function
    # this walk ever saw. Any function passed to any call in such an assignment
    # is treated as the binding's delegate, so this keeps working if the factory
    # is renamed or another one appears.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not targets:
            continue
        delegates = {
            arg.id
            for arg in (*node.value.args, *(kw.value for kw in node.value.keywords))
            if isinstance(arg, ast.Name) and arg.id in direct
        }
        if not delegates:
            continue
        for target in targets:
            direct.setdefault(target, set())
            calls.setdefault(target, set()).update(delegates)

    def _closure(name: str) -> set[str]:
        """Nodes reachable from ``name``, following intra-module delegation.

        Iterative with a seen-set: the tool module has mutually recursive
        helpers, and recursion here would not terminate on them.
        """
        seen: set[str] = set()
        stack = [name]
        found: set[str] = set()
        while stack:
            current = stack.pop()
            if current in seen or current not in direct:
                continue
            seen.add(current)
            found |= direct[current]
            stack.extend(calls.get(current, ()))
        return found

    by_handler = {name: sorted(_closure(name)) for name in direct}

    out: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "tools" for t in node.targets):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and isinstance(value, ast.Name)
                and by_handler.get(value.id)
            ):
                out[key.value] = by_handler[value.id]
    return out
