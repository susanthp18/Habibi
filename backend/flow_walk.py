"""Traverse an authored flow graph on any channel.

``voice/flows_dynamic.py`` has walked graphs since flows were authorable, but
the traversal lives inside closures over a Pipecat ``FlowManager``: which edge
fires, which node is next, and which tools a step offers are all decided inside
functions that only exist once a ``NodeConfig`` factory has been built. The
consequence is measurable — ``flow`` appears **zero** times in ``bot_runtime.py``
and three times in ``sandbox_runtime.py``, all three drawing a status lozenge.
The authored graph, which the Studio gates at publish and the canvas draws,
runs on exactly one of three mouths.

This module is that traversal with the Pipecat coat taken off: a graph, a
variable bag, and a cursor. ``flows_dynamic`` keeps building ``NodeConfig``
factories and keeps owning everything about *speaking* — pre-actions, TTS,
post-action deferral, ``role_message``. It asks this module only the questions
that are about the graph.

There is deliberately no second implementation. The repository's own audit found
20 duplicated vocabularies and 11 already drifted, with one rule holding: every
duplicate given a drift test agreed, every duplicate without one separated. A
second walker for text would be the twelfth, and it would drift in the direction
that matters most — the text channel silently offering a tool the voice channel
had already gated away.

Not here, on purpose: anything that speaks. No TTS, no ``role_message``, no
post-actions. A caller that needs those is on the audio path and should be
asking ``flows_dynamic``.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

from flow_graph import NAMESPACE_SEP, FlowGraph, FlowNode, resolve_key, split_key
from flow_vars import FlowVariables, evaluate_condition

logger = logging.getLogger(__name__)

#: Generated transition tool, ``go_to_<target key>``. The model transitions by
#: choosing to call one; ``flows_dynamic`` renders the author's condition text as
#: the description, which is what the model actually reads to decide.
TRANSITION_PREFIX = "go_to_"

#: Generated capture tool, present only on a node that declares variables.
EXTRACT_TOOL = "extract_details"

#: A namespaced node key is ``collections/wrap_up``, but ``/`` is illegal in an
#: OpenAI (and Pipecat) function name. The tool spells it ``__``. Nothing ever
#: parses the name back apart — ``FlowWalker`` keeps a forward map from tool name
#: to key, so a local key that happens to contain ``__`` cannot be mis-split.
_TOOL_SEP = "__"


def transition_tool_name(key: str) -> str:
    """``collections/wrap_up`` -> ``go_to_collections__wrap_up``."""
    return f"{TRANSITION_PREFIX}{key.replace(NAMESPACE_SEP, _TOOL_SEP)}"


def entry_node(
    graph: FlowGraph,
    *,
    objective: str | None = None,
    entry_key: str | None = None,
) -> FlowNode | None:
    """Where a call on this graph begins.

    Three tiers, most specific first: a mission naming its own entry node, the
    node claiming this objective in ``entryFor``, then the graph's start node.
    Lifted out of ``flows_dynamic`` so a text mouth begins a conversation on the
    same node the audio path would — an outbound mission that starts three steps
    in must not restart at "the phone rang" because the sandbox picked
    ``start_node`` on its own.
    """
    if entry_key:
        from flow_graph import resolve_key

        keys = [n.key for n in graph.nodes]
        resolved = resolve_key(keys, entry_key) or entry_key
        node = next((n for n in graph.nodes if n.key == resolved), None)
        if node is not None:
            return node
        logger.warning("mission names entry node %r which is not in the graph", entry_key)
    if objective:
        node = graph.entry_for(objective)
        if node is not None:
            return node
        if objective != "inbound":
            logger.warning(
                "authored flow has no entry for mission %r — starting at the start node",
                objective,
            )
    return graph.start_node


class FlowWalker:
    """A cursor over an authored graph, plus the edge rules.

    Construct one per conversation. ``variables`` is shared with the caller, not
    copied: an ``expression`` edge must test what the extract tool just captured,
    so a snapshot taken at build time would evaluate every clause against an
    empty bag.
    """

    def __init__(
        self,
        graph: FlowGraph,
        variables: FlowVariables,
        *,
        start: FlowNode | None = None,
        namespace: str | None = None,
    ) -> None:
        self.graph = graph
        self.variables = variables
        self._by_id = {node.id: node for node in graph.nodes}
        self._by_key = {node.key: node for node in graph.nodes}
        self._by_tool = {transition_tool_name(key): key for key in self._by_key}
        self._outgoing: dict[str, list[Any]] = {}
        for edge in graph.edges:
            # An edge to a node that is not in the graph is not a transition,
            # it is a dangling reference. Dropping it here means every caller
            # sees the same graph the compiler validated.
            if edge.source in self._by_id and edge.target in self._by_id:
                self._outgoing.setdefault(edge.source, []).append(edge)
        self.current: FlowNode | None = start or graph.start_node
        #: The member whose subgraph the cursor is in. Local names resolve here
        #: first, which is what lets two specialists each own a ``wrap_up``. It
        #: follows the cursor, so a hop swaps the namespace by moving.
        self.namespace = namespace or (
            split_key(self.current.key)[0] if self.current else None
        )

    # --- edges -------------------------------------------------------------

    def edges_from(self, node: FlowNode | None = None) -> list[Any]:
        node = node or self.current
        return list(self._outgoing.get(node.id, ())) if node else []

    def prompt_edges(self, node: FlowNode | None = None) -> list[Any]:
        """Edges the model decides, one generated tool each."""
        return [e for e in self.edges_from(node) if e.data.condition.type == "prompt"]

    def deterministic_target(self, node: FlowNode | None = None) -> FlowNode | None:
        """First non-prompt edge whose condition holds, or None.

        ``always`` and ``expression`` edges are never shown to the model. Order
        is authoring order, and the first match wins — an author who lists two
        satisfiable expression edges gets the one drawn first, which is what the
        canvas shows top to bottom.
        """
        for edge in self.edges_from(node):
            if edge.data.condition.type == "prompt":
                continue
            if evaluate_condition(edge.data.condition, self.variables):
                return self._by_id.get(edge.target)
        return None

    def node(self, key: str) -> FlowNode | None:
        """Resolve a node by key, honouring the active namespace.

        ``walker.node("wrap_up")`` inside the collections subgraph reaches
        ``collections/wrap_up``; the same call from the door reaches the door's.
        """
        resolved = resolve_key(self._by_key, key, namespace=self.namespace)
        return self._by_key.get(resolved) if resolved else None

    def narrow(
        self,
        granted: Iterable[str],
        specialist_grants: Mapping[str, Iterable[str]] | None = None,
    ) -> set[str]:
        """``granted`` narrowed to the member the cursor is standing in.

        Intersects, never widens: a member's grant is a slice of the card's, so
        a compiled bundle that named a tool the card cannot grant would still be
        refused at execution. A flat graph, or a namespace with no entry, gets
        the set it was given — today's behaviour on every mouth.
        """
        base = set(granted)
        grant = (specialist_grants or {}).get(self.namespace or "")
        return base if grant is None else base & set(grant)

    def union(
        self,
        granted: Iterable[str],
        specialist_grants: Mapping[str, Iterable[str]] | None = None,
    ) -> set[str]:
        """``granted`` widened to every member this graph contains.

        The counterpart to :meth:`narrow`, and both are needed for the same
        reason. The text mouths gate *execution* on one allowed set computed
        before the turn, so after a hop the receiving member's own tools would
        be refused as ungranted — the mirror image of the bug narrowing fixes.
        Voice does this already when it builds one registry over the union
        (``voice/tools.py``); this is that line, for the mouths that have no
        registry.

        Only members present in this graph are unioned, so an unrelated card's
        grant cannot leak in through a stale bundle. A flat graph adds nothing.
        """
        base = set(granted)
        if not specialist_grants:
            return base
        for namespace in self.namespaces():
            base |= set(specialist_grants.get(namespace) or ())
        return base

    def namespaces(self) -> set[str]:
        """Members whose nodes are in this graph. Empty when it is flat."""
        return {ns for ns in (split_key(key)[0] for key in self._by_key) if ns}

    def key_for_tool(self, tool_name: str) -> str | None:
        """The node key a ``go_to_*`` tool moves to, or None if it is not one.

        The only supported way back from a transition tool name to a key. Both
        mouths dispatch through it so neither has to know that ``/`` was spelled
        ``__``.
        """
        return self._by_tool.get(tool_name)

    def transitions(self, node: FlowNode | None = None) -> list[tuple[str, str]]:
        """``(tool name, description)`` for every edge the model decides.

        The author's condition text *is* the description — it is what the model
        reads to decide — rendered so ``{{variables}}`` resolve. A prompt edge
        with no text falls back to the target's display name, because an
        undescribed choice is one the model cannot make on purpose.

        Both mouths build their tool schema from this: ``flows_dynamic`` wraps it
        in a ``FlowsFunctionSchema``, the text loop in an OpenAI function. The
        name and the description are decided here so they cannot differ.
        """
        out: list[tuple[str, str]] = []
        for edge in self.prompt_edges(node):
            target = self._by_id.get(edge.target)
            if target is None:
                continue
            out.append(
                (
                    transition_tool_name(target.key),
                    self.variables.render(edge.data.condition.prompt)
                    or f"Move to {target.data.name}",
                )
            )
        return out

    # --- offers ------------------------------------------------------------

    def offers(
        self,
        node: FlowNode | None = None,
        *,
        granted: Iterable[str] | None = None,
    ) -> list[str]:
        """Tool names this step offers, in the order ``flows_dynamic`` builds them.

        ``granted`` is the card's effective grant. A business tool the card
        cannot grant is dropped rather than offered, which is what the voice path
        already does at the registry lookup — a node may reference a tool the
        author later removed from the card, and the runtime must not announce it.
        The generated transition and capture tools are not catalog tools and are
        never filtered: they are how the graph moves at all.

        An ``end`` node offers nothing. It closes the call.
        """
        node = node or self.current
        if node is None or node.type == "end":
            return []
        allow = set(granted) if granted is not None else None
        names: list[str] = []
        for key in node.data.tools:
            if allow is not None and key not in allow:
                logger.debug("flow walk: node %s drops ungranted tool %s", node.key, key)
                continue
            names.append(key)
        names.extend(
            transition_tool_name(self._by_id[e.target].key) for e in self.prompt_edges(node)
        )
        if node.data.extractVariables:
            names.append(EXTRACT_TOOL)
        return names

    def extract_properties(self, node: FlowNode | None = None) -> dict[str, dict[str, Any]]:
        """JSON-schema properties for this node's ``extract_details``.

        Same shape ``flows_dynamic._extract_tool`` builds, so a captured value
        lands in the variable bag identically on either mouth — which is what
        makes an ``equals true`` clause behave the same on both.
        """
        node = node or self.current
        if node is None:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for var in node.data.extractVariables:
            entry: dict[str, Any] = {"type": _TYPE_JSON.get(var.type, "string")}
            if var.description:
                entry["description"] = var.description
            out[var.key] = entry
        return out

    # --- movement ----------------------------------------------------------

    def capture(self, args: dict[str, Any] | None) -> list[str]:
        """Record an ``extract_details`` payload; return the keys accepted.

        Only declared keys with a value are taken, matching the voice handler.
        A partial answer must still be recordable, so nothing is required.
        """
        properties = self.extract_properties()
        captured = {
            k: v for k, v in (args or {}).items() if k in properties and v is not None
        }
        self.variables.update(captured)
        return sorted(captured)

    def implicit_target(self, tool_name: str | None) -> FlowNode | None:
        """The node a built-in tool moves to, when the graph uses reserved keys.

        The materialised collections script has twelve nodes and **zero authored
        edges** — it moves because ``voice/tools.py`` transitions by name, which
        is what ``RESERVED_NODE_KEYS`` documents and ``implicit_transitions``
        derives for the canvas. A text mouth that only honoured authored edges
        would greet the caller and then sit on ``greet_disclose`` forever, which
        is exactly what this walker did before this method existed.

        **First target present in the graph wins**, and the order matters: the
        list is derived in source order, so ``disclose_recording`` yields
        ``['discover_intent', 'verify_identity']`` — precisely the fallback chain
        ``voice/tools.py:655`` spells as ``_node("discover_intent") or
        _node("verify_identity")``. For a chain like that this rule is not an
        approximation, it is the same rule.

        ponytail: a few hops are genuinely state-dependent rather than fallback
        chains — ``begin_wrap_up`` yields ``['pre_close', 'wrap_up']`` and the
        live handler picks ``pre_close`` only when the caller still has something
        open, which is call state this module cannot see. Those take the first
        target too, so a text rehearsal can walk a step the audio path would have
        skipped. Named rather than hidden, because the alternative — declining
        the hop — strands the rehearsal on the greeting, which is worse and less
        honest. Upgrade path: have the tool report the node it chose and pass it
        in beside the name.
        """
        if not tool_name:
            return None
        from flow_graph import implicit_transitions

        for key in implicit_transitions().get(tool_name, ()):
            node = self.node(key)
            if node is not None:
                return node
        return None

    def advance(self, tool_name: str | None = None) -> FlowNode | None:
        """Move the cursor and return the new node, or None to stay put.

        A ``go_to_*`` call is the model's decision and wins outright. Anything
        else — a business tool, a capture, or the end of a turn — re-tests the
        deterministic edges, because the variables they read may have just
        changed. This is the same two-point rule the audio path applies with a
        post-action and a tool wrapper; on a text mouth there is no "after the
        bot stops speaking", so both collapse to one call site.
        """
        if tool_name and tool_name.startswith(TRANSITION_PREFIX):
            key = self._by_tool.get(tool_name)
            target = self._by_key.get(key) if key else None
            if target is None:
                logger.warning("flow walk: unknown target node for %s", tool_name)
                return None
            return self.move_to(target)
        target = self.implicit_target(tool_name) or self.deterministic_target()
        if target is None:
            return None
        return self.move_to(target)

    # --- text channel ------------------------------------------------------

    def is_terminal(self, node: FlowNode | None = None) -> bool:
        node = node or self.current
        return node is None or node.type == "end" or bool(node.data.endConversation)

    def text_exits(
        self,
        node: FlowNode | None = None,
        *,
        granted: Iterable[str] | None = None,
        handoffs: bool = False,
    ) -> dict[str, list[str]]:
        """Every way a text mouth can leave ``node``, by kind.

        ``edges`` are authored; ``movers`` are granted tools whose declared hop
        (``flow_graph.TRANSITIONS``) lands on a node present in the graph;
        ``handoff`` is a granted ``handoff_to_agent`` on a card that has
        somewhere to send the call -- a hop is an exit, it just leaves the
        graph. ``pass_through`` is the one place a step's *voice-only* exits
        all lead, for a step the text mouth cannot stand on (see
        :meth:`pass_through`).
        """
        node = node or self.current
        if node is None or self.is_terminal(node):
            return {"edges": [], "movers": [], "handoff": [], "pass_through": []}
        allow = set(granted) if granted is not None else None
        edges = [self._by_id[e.target].key for e in self.edges_from(node) if e.target in self._by_id]
        movers = [
            name
            for name in node.data.tools
            if (allow is None or name in allow) and self.implicit_target(name) is not None
        ]
        handoff = ["handoff_to_agent"] if handoffs and "handoff_to_agent" in node.data.tools and (allow is None or "handoff_to_agent" in allow) else []
        passing: list[str] = []
        if not edges and not movers and not handoff:
            from voice.node_contracts import NODE_REQUIRED

            verbs = set(node.data.tools) | set(NODE_REQUIRED.get(split_key(node.key)[1] or node.key, ()))
            targets = {
                t.key
                for t in (self.implicit_target(v) for v in verbs if allow is None or v not in allow)
                if t is not None
            }
            if len(targets) == 1:
                passing = sorted(targets)
        return {"edges": edges, "movers": movers, "handoff": handoff, "pass_through": passing}

    def pass_through(self, *, granted: Iterable[str] | None = None) -> list[str]:
        """Step off any node a text mouth cannot stand on. Returns the keys passed.

        ``greet_disclose`` exits only through ``disclose_recording``, a voice
        verb: it says the recording line and moves on. A WhatsApp thread has
        no recording to disclose and no such tool, so the walker used to sit
        on the greeting forever and the runtime papered over it with a floor
        that handed the model every tool. The step's own contract says where
        it goes -- one place -- so the text mouth goes there. A step whose
        voice-only exits lead to *two* places is left alone; that is a choice
        the graph did not make for text, and guessing is worse than stopping.
        """
        passed: list[str] = []
        seen: set[str] = set()
        while self.current is not None and self.current.key not in seen:
            seen.add(self.current.key)
            exits = self.text_exits(granted=granted)
            if not exits["pass_through"]:
                break
            target = self.node(exits["pass_through"][0]) or self._by_key.get(exits["pass_through"][0])
            if target is None:
                break
            passed.append(self.current.key)
            self.move_to(target)
        return passed

    def text_reachable(
        self, *, granted: Iterable[str] | None = None, handoffs: bool = False
    ) -> tuple[set[str], list[str]]:
        """``(reachable keys, stuck keys)`` for a text mouth walking from the start.

        Reachability follows every text exit -- authored edges regardless of
        condition, declared hops of granted tools, pass-throughs. A hop off the
        graph and a terminal end the walk. A step is *stuck* when it is
        reachable, not terminal, and has no exit of any kind; a step nobody
        can reach on text is not a text problem, however dead it looks.
        """
        start = self.graph.start_node
        if start is None:
            return set(), []
        reachable: set[str] = set()
        stuck: list[str] = []
        stack = [start]
        while stack:
            node = stack.pop()
            if node.key in reachable:
                continue
            reachable.add(node.key)
            if self.is_terminal(node):
                continue
            exits = self.text_exits(node, granted=granted, handoffs=handoffs)
            nxt: list[str] = list(exits["edges"]) + list(exits["pass_through"])
            # Every destination a mover declares, not only the walker's first
            # pick: `verify_identity` lands on the hub or on a polite ending
            # depending on the answer, and both are reachable.
            from flow_graph import TRANSITIONS

            for name in exits["movers"]:
                for key in TRANSITIONS.get(name, ()):
                    if self.node(key) is not None:
                        nxt.append(key)
            if not nxt and not exits["handoff"]:
                stuck.append(node.key)
            for key in nxt:
                target = self._by_key.get(key) or self.node(key)
                if target is not None:
                    stack.append(target)
        return reachable, stuck

    def move_to(self, target: FlowNode) -> FlowNode:
        """Set the cursor, and follow the namespace across a hop.

        Public because resuming a persisted text conversation is the same
        operation: a stored ``nodeKey`` that names another member's node has to
        restore that member's namespace too, or the next turn resolves local
        names into whoever the conversation started with.

        Crossing into another member's subgraph is what a handoff *is* at the
        graph level. Keeping the namespace pinned to where the call started
        would leave every local name resolving into the sending member, which is
        the tool-grant bug this whole seam exists to close.
        """
        self.current = target
        self.namespace = split_key(target.key)[0] or self.namespace
        return target


def openai_graph_tools(walker: FlowWalker) -> list[dict[str, Any]]:
    """The generated tools of the current node, as OpenAI function dicts.

    Transitions and ``extract_details`` are not catalog tools — there is no
    ``ToolSpec`` to render, because they exist only for this graph at this step.
    Both text mouths need the identical schema, so it is built here rather than
    twice; ``flows_dynamic`` builds the Pipecat equivalent from the same
    ``transitions`` and ``extract_properties``.
    """
    out: list[dict[str, Any]] = []
    for name, description in walker.transitions():
        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            }
        )
    properties = walker.extract_properties()
    if properties:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": EXTRACT_TOOL,
                    "description": (
                        "Record the details the caller has provided. Include only "
                        "fields you are confident about; omit the rest."
                    ),
                    # Nothing required: a partial answer must still be recordable.
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": [],
                    },
                },
            }
        )
    return out


def specialist_entries(compiled: Any) -> dict[str, str]:
    """``entry_by_specialist`` off a compiled bundle dict, defensively.

    Sibling of :func:`specialist_grants`, and defensive for the same reason: a
    bundle that predates the field describes no fleet, and an absent entry means
    a hop records itself without moving — never a crash on the audio path.
    """
    if not isinstance(compiled, dict):
        return {}
    raw = compiled.get("entry_by_specialist")
    if not isinstance(raw, dict):
        return {}
    return {str(slug): str(key) for slug, key in raw.items() if isinstance(key, str) and key}


def specialist_grants(compiled: Any) -> dict[str, set[str]]:
    """``grant_by_specialist`` off a compiled bundle dict, defensively.

    One reader for three mouths. The bundle is JSON that may predate the field,
    so anything unexpected is an empty dict — which means "no fleet", which is
    the correct and safe reading of a bundle that does not describe one.
    """
    if not isinstance(compiled, dict):
        return {}
    raw = compiled.get("grant_by_specialist")
    if not isinstance(raw, dict):
        return {}
    return {
        str(slug): {str(name) for name in names}
        for slug, names in raw.items()
        if isinstance(names, list)
    }


#: Authored variable type -> JSON schema type. Mirrored from ``flows_dynamic``;
#: the parity test pins the two together.
_TYPE_JSON: dict[str, str] = {
    "string": "string",
    "number": "number",
    "boolean": "boolean",
}
