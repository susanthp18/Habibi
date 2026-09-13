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

import copy
from dataclasses import dataclass, field
import logging
import re
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# Node keys and variable names become identifiers in tool schemas.
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")

#: Separates a fleet member's slug from its own node key: ``collections/wrap_up``.
#: Two specialists must be able to own a ``wrap_up`` each — without this, one
#: member per reserved key is the ceiling, which is one specialist per fleet.
#: ``/`` is illegal in an OpenAI function name, so a transition tool spells it
#: ``__`` (``flow_walk.transition_tool_name``); the graph keeps the readable form
#: because it is what the canvas and the compile report show.
NAMESPACE_SEP = "/"

#: A member slug is a bot id, which admits hyphens (``kaia-v2-4``).
_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def split_key(key: str) -> tuple[str | None, str]:
    """``('collections', 'wrap_up')`` — or ``(None, 'wrap_up')`` when flat."""
    namespace, sep, local = (key or "").partition(NAMESPACE_SEP)
    return (namespace, local) if sep else (None, key or "")


def local_key(key: str) -> str:
    """The member-local half. A flat key is its own local key."""
    return split_key(key)[1]


#: The part of a conversation that answers the phone -- greeting, disclosure,
#: identity, intent, the polite exits -- as opposed to the part that does
#: business on it. A hop between fleet members must never land here: the
#: caller has already been greeted and verified by the member handing off.
#:
#: ``state_position`` is deliberately absent. In the collections graph that key
#: is the servicing hub, so a door that owned it would inherit collections'
#: business tools; the door authors a *route* node under that name instead
#: (``scripts/seed_door_graph.py``).
DOOR_KEYS: frozenset[str] = frozenset(
    {
        "greet_disclose",
        "confirm_identity",
        "third_party",
        "discover_intent",
        "verify_identity",
        "terminate_politely",
        "escalate_close",
        "pre_close",
        "call_ended",
    }
)


def business_entry(flow: dict[str, Any]) -> str:
    """Where a hop into this graph lands when the handoff authors no entry_node.

    The first node in the graph's own order that is not a door node -- the
    point where its business starts. Derived, not a per-bot map: a map would
    drift the first time a member's graph changed. A graph that is all door
    nodes yields its first node (G-F15 then reports it). Keys may be
    namespaced; the door test is on the local half.
    """
    keys = [str(n.get("key") or "") for n in (flow.get("nodes") or []) if isinstance(n, dict)]
    keys = [k for k in keys if k]
    business = [k for k in keys if local_key(k) not in DOOR_KEYS]
    return (business or keys or [""])[0]


def valid_node_key(key: str) -> bool:
    namespace, local = split_key(key)
    if not _KEY_RE.match(local):
        return False
    return namespace is None or bool(_NAMESPACE_RE.match(namespace))


def resolve_key(keys: Iterable[str], name: str, *, namespace: str | None = None) -> str | None:
    """Resolve a possibly-local node name against a set of graph keys.

    Order is the whole point: the *speaking* member's namespace first, then the
    name exactly as given (already-namespaced, or a flat graph), then any single
    unambiguous namespace holding it. ``voice/tools.py`` transitions by literal
    local name — ``_node("wrap_up")`` — and must reach its own ``wrap_up`` rather
    than whichever member happens to be first in the merged graph.

    Returns ``None`` when the name is absent or ambiguous across members; an
    ambiguous hop is a compile-time authoring error, not something to guess at
    mid-call.
    """
    keyset = set(keys)
    # A name that carries its own namespace means exactly that node. Trying
    # the speaking namespace first turned a hop into `kaia-v2-4/state_position`
    # from the door into the door's own `state_position` -- the route node --
    # so the handoff landed where it started.
    if split_key(name)[0]:
        return name if name in keyset else None
    if namespace:
        scoped = f"{namespace}{NAMESPACE_SEP}{local_key(name)}"
        if scoped in keyset:
            return scoped
    if name in keyset:
        return name
    matches = [k for k in sorted(keyset) if split_key(k)[0] and local_key(k) == name]
    if len(matches) == 1:
        return matches[0]
    if matches:
        logger.warning("flow node %r is ambiguous across %d namespaces", name, len(matches))
    return None


def graph_namespaces(flow: Any) -> set[str]:
    """Namespaces carried by a graph's node keys. Empty for a flat graph.

    One derivation, so the compiler and the runtime cannot disagree about who is
    in a fleet. Takes the raw dict a bundle carries or a parsed ``FlowGraph``.
    """
    nodes = flow.nodes if isinstance(flow, FlowGraph) else (flow or {}).get("nodes") or []
    out: set[str] = set()
    for node in nodes:
        key = node.key if isinstance(node, FlowNode) else (node or {}).get("key") or ""
        namespace = split_key(key)[0]
        if namespace:
            out.add(namespace)
    return out


def namespaced(flow: dict[str, Any], ns: str, *, keep_start: bool) -> dict[str, Any]:
    """One member's graph, rewritten to live inside a merged fleet graph.

    Keys *and* ids are prefixed: two members both ship an ``n-start`` id, and
    edges address nodes by id, so prefixing keys alone would silently cross-wire
    the two graphs at merge time.

    ``globalTools`` move onto each node's own ``tools``. That is the load-bearing
    line. ``flows_dynamic`` builds ``global_functions`` once per graph with no
    per-member filter, so a merged graph that kept a union of every member's
    globals would hand the receiving specialist the sending one's tools — the
    exact leak the hop exists to close, reappearing one level up. Routed through
    ``data.tools`` they pass the per-node narrowing that is already there.

    ``isStart`` is cleared on everything but the primary: a fleet has one door.
    ``entryFor`` is kept, because a mission belongs to the member that owns it
    and G-OB2 checks that pairing per card.
    """
    graph = copy.deepcopy(flow or {})
    globals_ = list(graph.get("globalTools") or [])

    def scoped(value: str) -> str:
        return f"{ns}{NAMESPACE_SEP}{value}" if value else value

    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node["key"] = scoped(local_key(str(node.get("key") or "")))
        node["id"] = scoped(str(node.get("id") or ""))
        data = node.setdefault("data", {})
        if not isinstance(data, dict):
            continue
        if not keep_start:
            data["isStart"] = False
        if globals_:
            tools = list(data.get("tools") or [])
            data["tools"] = tools + [t for t in globals_ if t not in tools]

    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        edge["id"] = scoped(str(edge.get("id") or ""))
        edge["source"] = scoped(str(edge.get("source") or ""))
        edge["target"] = scoped(str(edge.get("target") or ""))

    # Folded into the nodes above; a merged graph has no member-level globals.
    graph["globalTools"] = []
    return graph


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


#: CRM reads the runtime strips from ``globalTools`` before a call starts: they
#: belong on the node that is allowed to use them, not on confirm_identity's
#: first turn. Declared here so the compiler's G16 can warn the author with the
#: same list ``voice.flows_dynamic`` strips by — authoring one and having it
#: vanish at dial time was silent.
GLOBAL_TOOLS_STRIPPED_AT_RUNTIME: frozenset[str] = frozenset(
    {"get_customer_context", "get_payment_history", "get_emi_schedule", "request_documents"}
)


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


def _err(issues: list[FlowIssue], code: str, message: str, **loc: Any) -> None:
    issues.append(FlowIssue(severity="error", code=code, message=message, **loc))


def _warn(issues: list[FlowIssue], code: str, message: str, **loc: Any) -> None:
    issues.append(FlowIssue(severity="warning", code=code, message=message, **loc))


@dataclass
class GraphCheck:
    """One structural check of an authored graph: the graph, the known tools, the
    issues found so far, and the edge index the reachability pass reads. Filled
    in order by ``_check_nodes`` / ``_check_objectives`` / ``_check_edges`` /
    ``_check_hops_and_reach``; the bodies are what ``validate_graph`` was.
    """

    graph: FlowGraph
    issues: list[FlowIssue]
    tools: set[str]
    by_id: dict[str, FlowNode] = field(default_factory=dict)
    incoming: set[str] = field(default_factory=set)


def _check_nodes(st: GraphCheck) -> None:
    """Node ids, keys, types, tools and the start node."""
    graph = st.graph
    issues = st.issues
    tools = st.tools

    # --- nodes ---
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    for node in graph.nodes:
        if node.id in seen_ids:
            _err(issues, "duplicate_node_id", f"Duplicate node id {node.id!r}.", nodeId=node.id)
        seen_ids.add(node.id)

        if not valid_node_key(node.key):
            _err(issues, 
                "invalid_node_key",
                f"Node key {node.key!r} must be lowercase letters, digits and "
                "underscores, starting with a letter, optionally prefixed with "
                "a member slug and a slash.",
                nodeId=node.id,
            )
        elif node.key in seen_keys:
            # Keys become transition tool names; a collision silently merges two
            # transitions into one.
            _err(issues, 
                "duplicate_node_key",
                f"Node key {node.key!r} is used more than once.",
                nodeId=node.id,
            )
        seen_keys.add(node.key)

        if node.type == "conversation" and not node.data.instructions.strip():
            _warn(issues, 
                "empty_instructions",
                f"Node {node.data.name!r} has no instructions.",
                nodeId=node.id,
            )

        for tool in node.data.tools:
            if tools and tool not in tools:
                _err(issues, 
                    "unknown_tool",
                    f"Node {node.data.name!r} uses unknown tool {tool!r}.",
                    nodeId=node.id,
                )

        var_keys: set[str] = set()
        for var in node.data.extractVariables:
            if not _KEY_RE.match(var.key):
                _err(issues, 
                    "invalid_variable_key",
                    f"Variable {var.key!r} must be lowercase letters, digits "
                    "and underscores.",
                    nodeId=node.id,
                )
            if var.key in var_keys:
                _err(issues, 
                    "duplicate_variable",
                    f"Variable {var.key!r} is declared twice on {node.data.name!r}.",
                    nodeId=node.id,
                )
            var_keys.add(var.key)

    for tool in graph.globalTools:
        if tools and tool not in tools:
            _err(issues, "unknown_tool", f"Unknown global tool {tool!r}.")

    starts = [n for n in graph.nodes if n.type == "conversation" and n.data.isStart]
    if graph.nodes and not starts:
        _err(issues, "no_start", "Exactly one node must be marked as the start node.")
    elif len(starts) > 1:
        for node in starts:
            _err(issues, 
                "multiple_starts",
                "More than one node is marked as the start node.",
                nodeId=node.id,
            )


def _check_objectives(st: GraphCheck) -> None:
    """Mission entry points: one conversation node per objective."""
    graph = st.graph
    issues = st.issues

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
                _err(issues, 
                    "unknown_objective",
                    f"{objective!r} is not a mission this system knows. "
                    f"One of: {', '.join(OBJECTIVES)}.",
                    nodeId=node.id,
                )
                continue
            if node.type != "conversation":
                _err(issues, 
                    "entry_on_end_node",
                    "A call cannot begin at an end step.",
                    nodeId=node.id,
                )
                continue
            claimed.setdefault(objective, []).append(node)
    for objective, nodes in claimed.items():
        if len(nodes) > 1:
            for node in nodes:
                _err(issues, 
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
                _err(issues, 
                    "silent_outbound_entry",
                    "This step begins an outbound call but neither speaks first "
                    "nor has an entry line — the borrower would answer to silence.",
                    nodeId=node.id,
                )


def _check_edges(st: GraphCheck) -> None:
    """Edge ids, endpoints, conditions, and one route per pair."""
    graph = st.graph
    issues = st.issues

    # --- edges ---
    by_id = {n.id: n for n in graph.nodes}
    seen_edge_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    outgoing: dict[str, list[FlowEdge]] = {}
    incoming: set[str] = set()

    for edge in graph.edges:
        if edge.id in seen_edge_ids:
            _err(issues, "duplicate_edge_id", f"Duplicate edge id {edge.id!r}.", edgeId=edge.id)
        seen_edge_ids.add(edge.id)

        if edge.source not in by_id:
            _err(issues, 
                "dangling_source",
                "Edge starts from a node that no longer exists.",
                edgeId=edge.id,
            )
            continue
        if edge.target not in by_id:
            _err(issues, 
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
            _err(issues, 
                "self_edge",
                "A step cannot transition to itself.",
                edgeId=edge.id,
            )
            continue

        pair = (edge.source, edge.target)
        if pair in seen_pairs:
            _err(issues, 
                "duplicate_edge",
                "Two edges connect the same pair of nodes.",
                edgeId=edge.id,
            )
        seen_pairs.add(pair)

        if by_id[edge.source].type == "end":
            _err(issues, 
                "edge_from_end",
                "An end node cannot transition anywhere.",
                edgeId=edge.id,
            )

        outgoing.setdefault(edge.source, []).append(edge)
        incoming.add(edge.target)

        cond = edge.data.condition
        if cond.type == "prompt" and not cond.prompt.strip():
            _err(issues, 
                "empty_condition",
                "A prompt transition needs a condition describing when it fires.",
                edgeId=edge.id,
            )
        if cond.type == "expression":
            if not cond.clauses:
                _err(issues, 
                    "empty_expression",
                    "An expression transition needs at least one clause.",
                    edgeId=edge.id,
                )
            for clause in cond.clauses:
                if not clause.variable.strip():
                    _err(issues, 
                        "empty_clause_variable",
                        "An expression clause needs a variable.",
                        edgeId=edge.id,
                    )
                if (
                    clause.operator not in UNARY_OPERATORS
                    and not (clause.value or "").strip()
                ):
                    _err(issues, 
                        "empty_clause_value",
                        f"Operator {clause.operator!r} needs a value.",
                        edgeId=edge.id,
                    )

    # An `always` edge fires unconditionally, so a sibling can never be taken.
    for source_id, edges in outgoing.items():
        if len(edges) > 1 and any(e.data.condition.type == "always" for e in edges):
            for edge in edges:
                if edge.data.condition.type == "always":
                    _err(issues, 
                        "always_not_exclusive",
                        "An 'always' transition must be the node's only outgoing "
                        "transition — the others could never fire.",
                        edgeId=edge.id,
                    )

    st.by_id = by_id
    st.incoming = incoming


def _check_hops_and_reach(st: GraphCheck) -> FlowValidation:
    """Edges redundant with a built-in hop, and reachability from the start."""
    graph = st.graph
    issues = st.issues
    by_id = st.by_id
    incoming = st.incoming

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
                _warn(issues, 
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
            if local_key(node.key) in RESERVED_NODE_KEYS:
                continue
            # A mission entry is reached by being dialled, not by an edge.
            if node.data.entryFor:
                continue
            _warn(issues, 
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
                _warn(issues, 
                    "no_inbound",
                    f"Nothing transitions into {node.data.name!r}.",
                    nodeId=node.id,
                )

    return FlowValidation(
        ok=not any(i.severity == "error" for i in issues), issues=issues
    )


def validate_graph(graph: FlowGraph, *, known_tools: Iterable[str] = ()) -> FlowValidation:
    """Structural check. Errors block publish; warnings are advisory.

    Deliberately does not require a non-empty graph: a draft mid-edit must stay
    savable, or authors stop saving.
    """
    issues: list[FlowIssue] = []
    tools = set(known_tools)

    st = GraphCheck(
        graph=graph,
        issues=issues,
        tools=tools,
    )
    _check_nodes(st)
    _check_objectives(st)
    _check_edges(st)
    return _check_hops_and_reach(st)


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
    "refuse_verification": "Caller refuses to verify identity.",
    "not_account_holder": "Caller says they are not the account holder / third party.",
    "begin_negotiate": "Move to promise-to-pay negotiation when the caller wants a plan.",
    "begin_dispute": "Move to dispute handling when the caller disputes the balance.",
    "begin_wrap_up": "Move to call wrap-up when the caller is done.",
    "return_to_position": "Return to the account-position hub after a side path.",
    "pause_for_caller": "Caller asked to hold / wait a moment.",
    "end_call": "End the call when the caller says goodbye mid-conversation.",
}

#: Where each built-in tool moves the conversation. **This is the source of
#: truth for transitions**, read by the canvas (``implicit_transitions``), the
#: text walker (``flow_walk.implicit_target``), the validator and G-F11.
#:
#: It used to be recovered at runtime by parsing ``voice/tools.py`` with
#: ``ast`` -- three passes over the module, following delegation and parameter
#: defaults -- so that the handlers' ``_node("...")`` literals stayed the only
#: statement of where a call goes. Now the handlers agree with this map, and
#: ``tests/test_transitions_are_declared.py`` reads the handlers the old way
#: and fails if one moves somewhere this map does not say.
#:
#: Order is the walker's preference: **the first key present in the graph
#: wins**. Where a handler's real choice is call state the walker cannot see
#: (``end_call`` probes ``pre_close`` once before ``call_ended``;
#: ``not_account_holder`` lands on ``third_party`` only on the outbound leg),
#: the entry lists the plain terminal first so a text rehearsal reaches an end
#: rather than a loop. Named here rather than hidden in the walker.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "disclose_recording": ("discover_intent", "verify_identity"),
    "capture_call_goal": ("verify_identity",),
    "verify_identity": ("state_position", "terminate_politely"),
    "refuse_verification": ("terminate_politely",),
    "not_account_holder": ("terminate_politely", "third_party"),
    "begin_negotiate": ("negotiate_ptp",),
    "begin_dispute": ("handle_dispute",),
    "begin_wrap_up": ("pre_close", "wrap_up"),
    "return_to_position": ("state_position",),
    "create_promise_to_pay": ("gated_upsell",),
    "flag_dispute": ("escalate_close",),
    "request_callback": ("wrap_up",),
    "recommend_next_offer": ("wrap_up",),
    "capture_lead": ("wrap_up",),
    "escalate_to_human": ("escalate_close",),
    "end_call": ("call_ended", "pre_close"),
}

#: Tools whose handlers return a next node of their own. Derived from the map
#: above -- the hand-kept copy this used to be had drifted to 12 of 16.
_TRANSITIONING_TOOLS = frozenset(TRANSITIONS)


def tool_catalog() -> list[dict[str, Any]]:
    """Tools the Studio may offer an author, on every channel.

    Assembled from the pipecat-free ``agent_core.tools.CATALOG`` plus
    :data:`_FLOW_CONTROL_TOOLS`.

    **No longer filtered to voice.** This one endpoint feeds three pickers —
    the flow node's tools, the card's Tool Grant, and a skill pack's
    ``allowed-tools`` — and only the first of them is voice. Dropping every
    text-only spec here is why ``identify_customer`` and
    ``ingest_customer_document`` could not be granted from the Studio at all:
    they were absent from the palette, so no author could add them, so they
    appeared on no card and in no pack, so the runtime refused them —
    while the WhatsApp system prompt named one of them on every turn.

    Each row now states its own ``channels`` and each consumer filters to what
    it is for. The Flow tab keeps voice, because a flow node is a voice node.
    """
    from agent_core.cards.schema import LOCKED_MOUTH_TOOLS
    from agent_core.tools import CATALOG
    from agent_core.tools.grant import TEXT_ALWAYS, VOICE_ALWAYS, VOICE_FLOW_TOOLS

    entries: dict[str, str] = {}
    channels: dict[str, list[str]] = {}
    catalog_keys: set[str] = set()
    for key, spec in CATALOG.specs.items():
        entries[key] = (getattr(spec, "description", "") or "").strip()
        channels[key] = sorted(getattr(spec, "channels", None) or ())
        catalog_keys.add(key)
    entries.update(_FLOW_CONTROL_TOOLS)

    #: Names the runtime keeps regardless of what a card granted. Adding one to
    #: ``tools.include`` is at best a no-op and at worst — for the nine
    #: flow-control verbs, which are not catalog specs — a G4 failure the author
    #: only discovers at Publish.
    floor = VOICE_ALWAYS | TEXT_ALWAYS

    return [
        {
            "key": key,
            "description": entries[key],
            "transitions": key in _TRANSITIONING_TOOLS,
            "locked": key in LOCKED_MOUTH_TOOLS,
            "alwaysOn": key in floor,
            # Flow-control verbs live only inside voice.tools.build_tools.
            "channels": channels.get(key) or ["voice"],
            "kind": (
                "flow_control"
                if key in VOICE_FLOW_TOOLS and key not in catalog_keys
                else "catalog"
            ),
        }
        for key in sorted(entries)
    ]


# ---------------------------------------------------------------------------
# Implicit transitions
# ---------------------------------------------------------------------------


def implicit_transitions() -> dict[str, list[str]]:
    """tool key -> node keys that tool transitions to, in walker order.

    A copy of :data:`TRANSITIONS` as lists, which is the shape the canvas
    endpoint and the walker were built against. A tool absent from the result
    simply does not move the conversation.
    """
    return {tool: list(targets) for tool, targets in TRANSITIONS.items()}
