import { useMemo } from "react";
import type { Edge, Node } from "@xyflow/react";
import type { FlowGraph, FlowIssue, FlowTool } from "@/api/flow";
import { IMPLICIT_PREFIX } from "./layout";
import type { CanvasNodeData, NodeTool } from "../FlowNodes";

export type Selection =
  { kind: "none" } | { kind: "node"; id: string } | { kind: "edge"; id: string };

/**
 * The authored graph as xyflow draws it: the nodes with everything their
 * cards show that is not stored on them, the authored edges with their
 * verdicts, and the hops the built-in tools perform that nobody drew.
 */
export function useCanvasGraph({
  graph,
  grantTools,
  tools,
  transitions,
  reserved: reservedKeys,
  issuesByNode,
  issuesByEdge,
  selection,
}: {
  graph: FlowGraph;
  grantTools?: string[];
  tools: FlowTool[] | undefined;
  transitions: Record<string, string[]> | undefined;
  reserved: Record<string, string> | undefined;
  issuesByNode: Map<string, FlowIssue[]>;
  issuesByEdge: Map<string, FlowIssue[]>;
  selection: Selection;
}) {
  /**
   * Edges the built-in tools perform, which no author drew.
   *
   * A node exposing `begin_dispute` really does move the call to
   * `handle_dispute` — the tool calls `_node("handle_dispute")`. Without these
   * the materialised collections script renders as twelve disconnected boxes.
   * Rendered read-only and never written into the graph: they are a property of
   * the tool, not of the authored flow, and inventing real edges here would
   * publish transitions the runtime then applies twice.
   */
  /**
   * Tools this card cannot grant, so a hop of theirs is not a way out.
   *
   * A node may name any tool in the catalog — the picker allowed it,
   * `/flow/validate` allowed it and G1 allowed it — and the runtime then
   * filters its registry to the grant and skips the rest with a log line. The
   * canvas drew the hop anyway, so a step whose only exit the call would never
   * be offered looked like a step with an exit, and "Nothing leaves this step"
   * never fired on it. G16 reports the same intersection at compile.
   *
   * Flow-control verbs are on the runtime floor and are never dropped.
   */
  const ungranted = useMemo(() => {
    if (!grantTools) return null;
    const allowed = new Set(grantTools);
    return new Set(
      (tools ?? [])
        .filter((t) => t.kind !== "flow_control" && !t.alwaysOn && !allowed.has(t.key))
        .map((t) => t.key),
    );
  }, [tools, grantTools]);

  const implicitEdges: Edge[] = useMemo(() => {
    const map = transitions;
    if (!map) return [];
    // Duplicate node keys make this lookup last-wins, and drafts are savable
    // with `duplicate_node_key` — so a mid-edit graph with two nodes named
    // `verify` drew every tool hop into whichever one happened to be second in
    // the array, silently and with no indication that the destination shown is
    // a coin toss. Ambiguous keys resolve to nothing instead: no ghost edge is
    // a visible absence, a wrong ghost edge is not.
    const keyCounts = new Map<string, number>();
    for (const n of graph.nodes) keyCounts.set(n.key, (keyCounts.get(n.key) ?? 0) + 1);
    const byKey = new Map(
      graph.nodes.filter((n) => keyCounts.get(n.key) === 1).map((n) => [n.key, n.id]),
    );
    const authored = new Set(graph.edges.map((e) => `${e.source}->${e.target}`));
    const seen = new Set<string>();
    const out: Edge[] = [];
    for (const node of graph.nodes) {
      for (const tool of node.data.tools) {
        if (ungranted?.has(tool)) continue;
        for (const targetKey of map[tool] ?? []) {
          const target = byKey.get(targetKey);
          if (!target || target === node.id) continue;
          const pair = `${node.id}->${target}`;
          // An authored edge already says this; do not draw it twice.
          if (authored.has(pair) || seen.has(pair)) continue;
          seen.add(pair);
          out.push({
            id: `${IMPLICIT_PREFIX}${node.id}:${tool}:${target}`,
            source: node.id,
            target,
            // A real edge type, not `style` + `label` props. Those two are
            // dropped on the floor: `flowEdgeTypes.default` is
            // FlowConditionEdge, which sets its own stroke and never reads
            // `label` — so these arrived solid and unlabelled, identical to
            // the edges the author drew.
            type: "implicit",
            data: { tool },
            selectable: false,
            deletable: false,
            focusable: false,
          });
        }
      }
    }
    return out;
  }, [transitions, graph.nodes, graph.edges, ungranted]);

  /**
   * Everything a node card shows that is not stored on the node.
   *
   * Degree counts fold in the implicit hops, because "does anything leave this
   * step" is a question about the call, not about which edges someone drew by
   * hand — a node whose only exit is `begin_dispute` is not a dead end.
   */
  const nodeContext = useMemo(() => {
    const catalog = new Map((tools ?? []).map((t) => [t.key, t]));
    const catalogLoaded = (tools?.length ?? 0) > 0;
    const reserved = reservedKeys ?? {};
    const degree = new Map<
      string,
      { out: number; in: number; implicitOut: number; implicitIn: number }
    >();
    const bump = (id: string) => {
      let d = degree.get(id);
      if (!d) {
        d = { out: 0, in: 0, implicitOut: 0, implicitIn: 0 };
        degree.set(id, d);
      }
      return d;
    };
    for (const e of graph.edges) {
      bump(e.source).out += 1;
      bump(e.target).in += 1;
    }
    for (const e of implicitEdges) {
      bump(e.source).implicitOut += 1;
      bump(e.target).implicitIn += 1;
    }
    const globalToolCount = graph.globalTools?.length ?? 0;
    return { catalog, catalogLoaded, reserved, degree, globalToolCount };
  }, [tools, reservedKeys, graph.edges, graph.globalTools, implicitEdges]);

  const rfNodes: Node[] = useMemo(
    () =>
      graph.nodes.map((n) => {
        const own = issuesByNode.get(n.id) ?? [];
        const degree = nodeContext.degree.get(n.id);
        const toolDetail: NodeTool[] = n.data.tools.map((key) => {
          const tool = nodeContext.catalog.get(key);
          return {
            key,
            moves: tool?.transitions ?? false,
            locked: tool?.locked ?? false,
            // Only claim a tool is unknown once the catalog has actually
            // loaded; otherwise every tool on the graph flashes red on the
            // first paint and settles a moment later.
            unknown: nodeContext.catalogLoaded && !tool,
          };
        });
        const data: CanvasNodeData = {
          ...n.data,
          nodeKey: n.key,
          errorCount: own.filter((i) => i.severity === "error").length,
          warningCount: own.filter((i) => i.severity === "warning").length,
          toolDetail,
          reservedHint: nodeContext.reserved[n.key] ?? null,
          outCount: degree?.out ?? 0,
          inCount: degree?.in ?? 0,
          implicitOut: degree?.implicitOut ?? 0,
          implicitIn: degree?.implicitIn ?? 0,
          // Most steps in the built-in script move by calling a tool, not by an
          // authored edge, so those hops are only known once /flow/transitions
          // answers. Without this flag a failed read made `implicitOut` zero on
          // every node and the canvas told the author, confidently and about
          // their whole graph, that nothing leaves any step.
          transitionsUnknown: !transitions,
          globalToolCount: nodeContext.globalToolCount,
        };
        return {
          id: n.id,
          type: n.type,
          position: n.position,
          data,
          selected: selection.kind === "node" && selection.id === n.id,
        };
      }),
    [graph.nodes, issuesByNode, selection, nodeContext],
  );

  const rfEdges: Edge[] = useMemo(
    () =>
      graph.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        animated: e.data.condition.type === "prompt",
        selected: selection.kind === "edge" && selection.id === e.id,
        data: {
          condition: e.data.condition,
          hasError: (issuesByEdge.get(e.id) ?? []).some((i) => i.severity === "error"),
        },
      })),
    [graph.edges, issuesByEdge, selection],
  );

  return { implicitEdges, rfNodes, rfEdges };
}
