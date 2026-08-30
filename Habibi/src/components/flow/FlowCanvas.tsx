import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  useNodesInitialized,
  useStore,
  useReactFlow,
  useUpdateNodeInternals,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { toast } from "sonner";
import {
  AlertTriangle,
  CheckCircle2,
  Crosshair,
  LayoutGrid,
  Loader2,
  Maximize2,
  Minimize2,
  MoreHorizontal,
  PhoneOff,
  Plus,
  RotateCcw,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { SplitPanes } from "@/components/inbox/SplitPanes";
import { useDarkMode } from "@/components/charts/use-dark-mode";

import {
  defaultCondition,
  emptyGraph,
  fetchBuiltInFlow,
  isEmptyGraph,
  newNodeData,
  useFlowTools,
  useFlowTransitions,
  useReservedKeys,
  validateFlow,
  type FlowEdge as ApiEdge,
  type FlowGraph,
  type FlowIssue,
  type FlowNode as ApiNode,
} from "@/api/flow";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Lozenge } from "@/components/ui/lozenge";
import { cn } from "@/lib/utils";
import { FlowEdgeMarkers, flowEdgeTypes } from "./FlowConditionEdge";
import { flowNodeTypes, type CanvasNodeData, type NodeTool } from "./FlowNodes";
import { EdgeInspector, GraphInspector, NodeInspector } from "./FlowInspector";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

type Selection = { kind: "none" } | { kind: "node"; id: string } | { kind: "edge"; id: string };

/** Card width in FlowNodes (`w-72`), which the layout has to reserve room for. */
const NODE_W = 288;

const MIN_ZOOM = 0.15;
const MAX_ZOOM = 2;

/**
 * The zoom readout and its two buttons.
 *
 * Its own component so the subscription lives at the leaf. Read from
 * FlowCanvasInner, `s.transform[2]` re-renders the entire canvas on every wheel
 * tick — the node and edge renderers deliberately select booleans from the same
 * value for exactly this reason.
 */
function ZoomControls() {
  const zoom = useStore((s) => s.transform[2]);
  const { zoomIn, zoomOut } = useReactFlow();
  return (
    <div className="flex shrink-0 items-center gap-025">
      <Button
        variant="ghost"
        size="icon-compact"
        onClick={() => void zoomOut({ duration: 120 })}
        disabled={zoom <= MIN_ZOOM + 0.001}
        title="Zoom out"
      >
        <ZoomOut className="h-3.5 w-3.5" />
      </Button>
      <span className="w-10 text-center tabular-nums text-text-subtle">
        {Math.round(zoom * 100)}%
      </span>
      <Button
        variant="ghost"
        size="icon-compact"
        onClick={() => void zoomIn({ duration: 120 })}
        disabled={zoom >= MAX_ZOOM - 0.001}
        title="Zoom in"
      >
        <ZoomIn className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

/** Divider between toolbar groups, so the groups read as groups. */
function Rule() {
  return <span aria-hidden className="h-4 w-px shrink-0 bg-border" />;
}

/** A sample of one edge treatment, for the legend in the status bar. */
function EdgeSwatch({
  color,
  dash,
  width = 1.6,
  round = false,
}: {
  color: string;
  dash?: string;
  width?: number;
  round?: boolean;
}) {
  return (
    <svg width="20" height="6" aria-hidden className="shrink-0">
      <line
        x1="0"
        y1="3"
        x2="20"
        y2="3"
        stroke={color}
        strokeWidth={width}
        strokeDasharray={dash}
        strokeLinecap={round ? "round" : undefined}
      />
    </svg>
  );
}

let idCounter = 0;
/**
 * Date.now() alone collides for two nodes added in the same millisecond, which
 * produces a graph with duplicate ids that only fails at save.
 */
function uniqueId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${Date.now().toString(36)}-${idCounter}`;
}

function keyFromName(name: string, taken: Set<string>): string {
  const base =
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/^([^a-z])/, "n$1")
      .slice(0, 40) || "node";
  let key = base;
  let n = 2;
  while (taken.has(key)) key = `${base}_${n++}`;
  return key;
}

const IMPLICIT_PREFIX = "implicit:";

/**
 * Layered top-down positions, keyed by node id. Used by Auto-layout.
 *
 * Three passes beyond the plain BFS this replaces, which is what made "Tidy"
 * worth pressing once and never again:
 *
 * - Cycles are broken first, for layering only. A collections script loops on
 *   purpose — `return_to_position` goes back to the hub — and longest-path
 *   layering over a loop has no fixed point: every pass pushes the nodes in it
 *   one row further down until the cap stops them, which draws the busiest part
 *   of the graph as a long thin column. A depth-first pass marks the edges that
 *   close a loop; the layering ignores them and they still render, as an edge
 *   that runs back up the canvas.
 * - Layers come from the *longest* remaining path to a node, not the first one
 *   found. On a BFS depth, a node reachable in one hop and again in four sits in
 *   row 1 with a four-row edge dropping past three other cards to reach it.
 * - Within a layer, nodes are ordered by the mean slot of their parents (the
 *   barycentre heuristic) rather than by whatever order they arrived in. One
 *   pass of it removes most of the crossings on the built-in twelve-node
 *   script, and the graph reads as a script instead of a tangle.
 */
function layeredLayout(
  nodes: { id: string; data: { isStart: boolean } }[],
  edges: { source: string; target: string }[],
): Record<string, { x: number; y: number }> {
  const COL = NODE_W + 72;
  const ROW = 230;
  const out: Record<string, { x: number; y: number }> = {};
  if (nodes.length === 0) return out;

  const known = new Set(nodes.map((n) => n.id));
  const outgoing = new Map<string, string[]>();
  for (const e of edges) {
    if (e.source === e.target) continue;
    if (!known.has(e.source) || !known.has(e.target)) continue;
    const list = outgoing.get(e.source);
    if (!list) outgoing.set(e.source, [e.target]);
    else if (!list.includes(e.target)) list.push(e.target);
  }

  const start = nodes.find((n) => n.data.isStart) ?? nodes[0];

  // Iterative three-colour DFS. Iterative rather than recursive so a wide graph
  // cannot overflow the stack inside a render.
  const back = new Set<string>();
  const colour = new Map<string, 0 | 1 | 2>();
  for (const root of [start.id, ...nodes.map((n) => n.id)]) {
    if ((colour.get(root) ?? 0) !== 0) continue;
    colour.set(root, 1);
    const stack: { id: string; i: number }[] = [{ id: root, i: 0 }];
    while (stack.length) {
      const top = stack[stack.length - 1];
      const kids = outgoing.get(top.id) ?? [];
      if (top.i >= kids.length) {
        colour.set(top.id, 2);
        stack.pop();
        continue;
      }
      const next = kids[top.i];
      top.i += 1;
      const c = colour.get(next) ?? 0;
      // Grey means `next` is still on the stack, so this edge closes a loop.
      if (c === 1) back.add(`${top.id}->${next}`);
      if (c !== 0) continue;
      colour.set(next, 1);
      stack.push({ id: next, i: 0 });
    }
  }

  const forward = (source: string) =>
    (outgoing.get(source) ?? []).filter((t) => !back.has(`${source}->${t}`));

  const incoming = new Map<string, string[]>();
  for (const source of outgoing.keys()) {
    for (const target of forward(source)) {
      incoming.set(target, [...(incoming.get(target) ?? []), source]);
    }
  }

  // Longest path over the acyclic remainder, relaxed until it settles. Bounded
  // by the node count, which is also the deepest a simple path can be.
  const depth = new Map<string, number>([[start.id, 0]]);
  for (let pass = 0; pass < nodes.length; pass += 1) {
    let changed = false;
    for (const [source] of outgoing) {
      const from = depth.get(source);
      if (from === undefined) continue;
      for (const target of forward(source)) {
        const current = depth.get(target);
        if (current === undefined || current < from + 1) {
          depth.set(target, from + 1);
          changed = true;
        }
      }
    }
    if (!changed) break;
  }

  // Anything the walk cannot reach — an orphan, or a node only reachable
  // through a tool hop we do not model — is parked in a trailing layer rather
  // than dropped on the origin.
  const maxDepth = Math.max(0, ...depth.values());
  for (const n of nodes) if (!depth.has(n.id)) depth.set(n.id, maxDepth + 1);

  const layers = new Map<number, string[]>();
  for (const n of nodes) {
    const d = depth.get(n.id) ?? 0;
    layers.set(d, [...(layers.get(d) ?? []), n.id]);
  }

  const slot = new Map<string, number>();
  for (const d of [...layers.keys()].sort((a, b) => a - b)) {
    const ids = layers.get(d) ?? [];
    if (d > 0) {
      const scored = ids.map((id, i) => {
        const parents = (incoming.get(id) ?? [])
          .map((parent) => slot.get(parent))
          .filter((s): s is number => s !== undefined);
        return {
          id,
          // No placed parent keeps its incoming order rather than jumping to
          // the left edge, which is what `?? 0` would have done.
          score: parents.length ? parents.reduce((a, b) => a + b, 0) / parents.length : i,
        };
      });
      scored.sort((a, b) => a.score - b.score);
      ids.splice(0, ids.length, ...scored.map((entry) => entry.id));
    }
    ids.forEach((id, i) => {
      slot.set(id, i);
      out[id] = { x: (i - (ids.length - 1) / 2) * COL, y: d * ROW };
    });
  }
  return out;
}

function FitToGraph({ signature }: { signature: string }) {
  // `signature` folds in anything that should re-frame and re-measure the
  // graph: the node set, and the shape of the pane. Entering full screen keeps
  // the component mounted, so without the pane in the key the camera stayed on
  // the crop it had at a third of the width — a zoomed-in corner of the graph,
  // with the rest off-screen.
  const { fitView } = useReactFlow();
  const initialized = useNodesInitialized();
  const updateNodeInternals = useUpdateNodeInternals();
  const nodeIds = useMemo(
    // The leading segment is the pane key, not a node id.
    () => signature.split("|").slice(1),
    [signature],
  );
  // Switching tabs unmounts this canvas, and on the way back the pane is
  // mounted before layout has given it a size. `initialized` flips true while
  // the pane is still 0x0, so fitView framed a degenerate box, parked the
  // camera off the graph, and marked the fit done — the canvas came back blank
  // and stayed blank. Waiting for real dimensions is what makes the return trip
  // survivable.
  const paneReady = useStore((s) => s.width > 0 && s.height > 0);
  // Every node has a real measured box.
  //
  // `useNodesInitialized()` is not enough on its own: it can report true while
  // the nodes still have no dimensions, and fitView against a collapsed
  // bounding box does not fail — it computes an enormous zoom, clamps to
  // maxZoom (2), and parks there. The canvas then opens showing two or three
  // giant cards with the rest of the graph off-screen, and because the fit
  // marked itself done it never corrects once the real sizes arrive. A graph
  // that looks permanently "zoomed in" is this, not a zoom anyone asked for.
  const measured = useStore((s) => {
    if (s.nodeLookup.size === 0) return false;
    for (const node of s.nodeLookup.values()) {
      if (!node.measured?.width || !node.measured?.height) return false;
    }
    return true;
  });
  const fitted = useRef<string | null>(null);
  const remeasured = useRef<string | null>(null);

  // Force a re-read of every node's DOM box once the pane has a size.
  //
  // xyflow measures nodes with a ResizeObserver, and an observer never
  // delivers a first entry for an element that was mounted without layout —
  // which is exactly what a hidden tab panel is, and what a background browser
  // tab is. The nodes then stay unmeasured: xyflow renders each one
  // `visibility: hidden` and refuses to draw a single edge, so the canvas comes
  // back from a tab switch as an empty grid. Nothing recovers on its own,
  // because nothing resizes afterwards and the observer stays silent for the
  // life of the component. Twelve nodes, twenty-one transitions, and not one
  // line on screen.
  useEffect(() => {
    if (!paneReady || nodeIds.length === 0) return;
    if (remeasured.current === signature) return;
    remeasured.current = signature;
    updateNodeInternals(nodeIds);
  }, [paneReady, signature, nodeIds, updateNodeInternals]);

  useEffect(() => {
    if (!initialized || !paneReady || !measured || !signature) return;
    if (fitted.current === signature) return;
    fitted.current = signature;
    void fitView({ padding: 0.15, duration: 200 });
  }, [initialized, paneReady, measured, signature, fitView]);

  return null;
}

export function FlowCanvas({
  graph,
  onChange,
  onValidation,
  readOnly = false,
}: {
  graph: FlowGraph;
  onChange: (next: FlowGraph) => void;
  onValidation?: (result: { ok: boolean; issues: FlowIssue[] }) => void;
  readOnly?: boolean;
}) {
  return (
    <ReactFlowProvider>
      <FlowCanvasInner
        graph={graph}
        onChange={onChange}
        onValidation={onValidation}
        readOnly={readOnly}
      />
    </ReactFlowProvider>
  );
}

function FlowCanvasInner({
  graph,
  onChange,
  onValidation,
  readOnly,
}: {
  graph: FlowGraph;
  onChange: (next: FlowGraph) => void;
  onValidation?: (result: { ok: boolean; issues: FlowIssue[] }) => void;
  readOnly: boolean;
}) {
  const [selection, setSelection] = useState<Selection>({ kind: "none" });
  const [issues, setIssues] = useState<FlowIssue[]>([]);
  /**
   * The exact graph object the current `issues` describe, or null if none.
   *
   * `issues` starts empty, and an empty issue list is indistinguishable from a
   * clean bill of health — so the status pill rendered a green "Valid" for a
   * graph that had not been checked yet, and went on rendering it if
   * `/flow/validate` was unreachable, because the catch deliberately keeps the
   * last known issues and the last known issues were `[]`.
   *
   * Publish is gated server-side, so nothing invalid could ship. What could
   * happen is worse for the author than for the caller: a graph with four
   * errors that says "Valid" until the response lands, and says it forever if
   * the response never does.
   *
   * Compared by reference, not by fingerprint — `commit` produces a new object
   * for every change, so identity is exact and costs nothing.
   */
  const [validatedGraph, setValidatedGraph] = useState<FlowGraph | null>(null);

  /**
   * The graph as of the last change *this tick*, which is not the same thing as
   * the `graph` prop.
   *
   * Deleting a node that has edges makes xyflow call `onNodesChange` and then
   * `onEdgesChange` back to back, inside one event, before React has re-rendered
   * with the result of the first. Both handlers closed over the same stale
   * `graph`, so the edge handler's `{...graph, edges}` carried the old node list
   * and put the node it had just deleted straight back on the canvas — with its
   * other edges gone. Reading and writing through a ref is what lets the two
   * compose.
   */
  const graphRef = useRef(graph);
  graphRef.current = graph;
  const commit = useCallback(
    (next: FlowGraph) => {
      graphRef.current = next;
      onChange(next);
    },
    [onChange],
  );
  const toolsQuery = useFlowTools();
  const reservedQuery = useReservedKeys();
  const transitionsQuery = useFlowTransitions();
  const dark = useDarkMode();

  // The callback lives in a ref so it is not an effect dependency.
  //
  // It is an inline arrow in the Studio, so its identity changes on every
  // parent render — and the effect below both depends on it and causes a
  // parent render by calling it. That closed a loop: validate -> setFlowIssues
  // -> re-render -> new callback identity -> effect re-runs -> validate. The
  // canvas hammered POST /flow/validate about twice a second for as long as
  // the Flow tab stayed open, and no amount of memoising in the parent would
  // have been load-bearing enough to trust.
  const onValidationRef = useRef(onValidation);
  useEffect(() => {
    onValidationRef.current = onValidation;
  }, [onValidation]);

  // Server-side validation, debounced. The same validator gates publish, so
  // the canvas can never show "fine" for something the backend will reject.
  useEffect(() => {
    if (isEmptyGraph(graph)) {
      setIssues([]);
      // An empty graph is a known state, not an unchecked one: the runtime
      // reads it as "use the built-in script", which is valid by construction.
      setValidatedGraph(graph);
      return;
    }
    const timer = window.setTimeout(() => {
      void validateFlow(graph)
        .then((result) => {
          setIssues(result.issues);
          setValidatedGraph(graph);
          onValidationRef.current?.(result);
        })
        .catch(() => {
          // Keep the last known issues rather than clearing them — but do NOT
          // keep reporting the last known verdict as if it applied to the graph
          // on screen. The publish gate starts open (`flowValid = true`) and
          // holds whatever it was last told, so a validator that dies mid-edit
          // left the editor asserting a graph is publishable on the strength of
          // a check that ran against different content. The server re-validates
          // on publish, so the cost is a late 422 rather than a bad deploy —
          // but the editor should not be the thing that promises otherwise.
          onValidationRef.current?.({
            ok: false,
            issues: [
              {
                severity: "warning",
                code: "validator_unreachable",
                message:
                  "The flow validator could not be reached, so this graph has not been checked. Publish will re-run it server-side.",
                nodeId: null,
                edgeId: null,
              },
            ],
          });
        });
    }, 400);
    return () => window.clearTimeout(timer);
  }, [graph]);

  const issuesByNode = useMemo(() => {
    const map = new Map<string, FlowIssue[]>();
    for (const issue of issues) {
      if (!issue.nodeId) continue;
      map.set(issue.nodeId, [...(map.get(issue.nodeId) ?? []), issue]);
    }
    return map;
  }, [issues]);

  const issuesByEdge = useMemo(() => {
    const map = new Map<string, FlowIssue[]>();
    for (const issue of issues) {
      if (!issue.edgeId) continue;
      map.set(issue.edgeId, [...(map.get(issue.edgeId) ?? []), issue]);
    }
    return map;
  }, [issues]);

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
  const implicitEdges: Edge[] = useMemo(() => {
    const map = transitionsQuery.data;
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
  }, [transitionsQuery.data, graph.nodes, graph.edges]);

  /**
   * Everything a node card shows that is not stored on the node.
   *
   * Degree counts fold in the implicit hops, because "does anything leave this
   * step" is a question about the call, not about which edges someone drew by
   * hand — a node whose only exit is `begin_dispute` is not a dead end.
   */
  const nodeContext = useMemo(() => {
    const catalog = new Map((toolsQuery.data ?? []).map((t) => [t.key, t]));
    const catalogLoaded = (toolsQuery.data?.length ?? 0) > 0;
    const reserved = reservedQuery.data ?? {};
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
  }, [toolsQuery.data, reservedQuery.data, graph.edges, graph.globalTools, implicitEdges]);

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
          globalToolCount: nodeContext.globalToolCount,
        };
        return {
          id: n.id,
          type: n.type,
          position: n.position,
          data: data as unknown as Record<string, unknown>,
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

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      if (readOnly) return;
      // Position changes only.
      //
      // The old filter was "anything that is not select or remove", which also
      // caught `dimensions` — the change xyflow emits every time it measures a
      // node. Feeding those back through onChange produced a new graph object,
      // which re-created every node, which triggered another measure: an
      // infinite loop that pegged the canvas, left the nodes unpainted, and
      // spammed the autosave with draft after draft. It stayed dormant only
      // because no card had ever stored a node, so nothing was ever measured.
      //
      // Measured sizes are xyflow's own business in a controlled flow; they are
      // not part of the authored graph and must never round-trip through it.
      // Selection is owned by the inspector and re-derived above. Removals are
      // handled explicitly so their edges go with them.
      const moves = changes.filter(
        (c): c is NodeChange & { type: "position" } => c.type === "position",
      );
      const removed = changes
        .filter((c): c is NodeChange & { type: "remove"; id: string } => c.type === "remove")
        .map((c) => c.id);

      const current = graphRef.current;
      let nodes = current.nodes;
      if (moves.length > 0) {
        const applied = applyNodeChanges(moves, rfNodes);
        const positions = new Map(applied.map((n) => [n.id, n.position]));
        // Compare before rebuilding: `.map` always returns a new array, so the
        // identity check below fired on drag events that moved nothing.
        let moved = false;
        nodes = nodes.map((n) => {
          const next = positions.get(n.id);
          if (!next || (next.x === n.position.x && next.y === n.position.y)) return n;
          moved = true;
          return { ...n, position: next };
        });
        if (!moved) nodes = current.nodes;
      }
      if (removed.length === 0) {
        if (nodes !== current.nodes) commit({ ...current, nodes });
        return;
      }
      const gone = new Set(removed);
      const orphaned = current.edges.filter((e) => gone.has(e.source) || gone.has(e.target)).length;
      commit({
        ...current,
        nodes: nodes.filter((n) => !gone.has(n.id)),
        // An edge to a deleted node is a dangling reference, i.e. a save error.
        edges: current.edges.filter((e) => !gone.has(e.source) && !gone.has(e.target)),
      });
      setSelection({ kind: "none" });
      if (orphaned > 0) {
        // Deleting one node silently deleting four transitions is the kind of
        // thing you only notice at publish, by which point you cannot tell
        // which ones went.
        toast.info(
          `Removed ${removed.length} step${removed.length === 1 ? "" : "s"} and ` +
            `${orphaned} transition${orphaned === 1 ? "" : "s"} that touched ${
              removed.length === 1 ? "it" : "them"
            }.`,
        );
      }
    },
    [commit, readOnly, rfNodes],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      if (readOnly) return;
      const removed = new Set(
        changes
          .filter((c): c is EdgeChange & { type: "remove"; id: string } => c.type === "remove")
          .map((c) => c.id)
          // Never authored, so never removable — guard rather than rely on the
          // deletable flag, which only governs the default delete affordances.
          .filter((id) => !id.startsWith(IMPLICIT_PREFIX)),
      );
      if (removed.size === 0) return;
      const current = graphRef.current;
      commit({
        ...current,
        edges: current.edges.filter((e) => !removed.has(e.id)),
      });
      setSelection({ kind: "none" });
    },
    [commit, readOnly],
  );

  /**
   * Why a connection is refused, or null when it is fine.
   *
   * Shared by `isValidConnection` and `onConnect` so the drag shows the refusal
   * as you hover — xyflow paints an invalid target differently — and the drop
   * says what it was. Both cases used to be a bare `return`: you dragged a
   * line, let go, and nothing whatsoever happened.
   */
  const connectionProblem = useCallback(
    (connection: Connection | Edge): string | null => {
      const { source, target } = connection;
      if (!source || !target) return "Incomplete connection.";
      // A node that transitions to itself is a loop the runtime takes forever;
      // on the canvas it draws as a stub behind the card, so the author cannot
      // see what they made. Rejected here and by the validator.
      if (source === target) {
        return "A step cannot transition to itself — staying put is what happens when no transition fires.";
      }
      const sourceNode = graph.nodes.find((n) => n.id === source);
      if (sourceNode?.type === "end") {
        return "An end node cannot transition anywhere.";
      }
      if (graph.edges.some((e) => e.source === source && e.target === target)) {
        // Rejected here rather than at save: the duplicate is invisible on the
        // canvas (the two edges overlap exactly) and the error would be baffling.
        return "These two steps are already connected.";
      }
      return null;
    },
    [graph.nodes, graph.edges],
  );

  const isValidConnection = useCallback(
    (connection: Connection | Edge) => connectionProblem(connection) === null,
    [connectionProblem],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (readOnly) return;
      const problem = connectionProblem(connection);
      if (problem) {
        toast.error(problem);
        return;
      }
      const edge: ApiEdge = {
        id: uniqueId("e"),
        source: connection.source,
        target: connection.target,
        data: { condition: defaultCondition("prompt") },
      };
      commit({ ...graph, edges: [...graph.edges, edge] });
      setSelection({ kind: "edge", id: edge.id });
    },
    [graph, commit, readOnly, connectionProblem],
  );

  const { fitView, getViewport } = useReactFlow();
  // Two scalar selectors, not one `s => ({width, height})`. xyflow compares
  // selector results with Object.is, so an object literal is a new value on
  // every store tick — and the store ticks on every pointer move over the pane.
  const paneWidth = useStore((s) => s.width);
  const paneHeight = useStore((s) => s.height);

  /**
   * Somewhere visible, and not on top of anything.
   *
   * The old formula was `60 + (nodeCount % 3) * 300`, which has two failure
   * modes that both bite immediately: delete a node and the next one you add
   * lands exactly on an existing card, and pan away from the origin and it
   * lands off-screen where you cannot find it. Start from the middle of what
   * the author is actually looking at, then step down and right until the box
   * is clear.
   */
  const freeSpot = useCallback((): { x: number; y: number } => {
    const NODE_H = 150;
    // Pane coordinates through the current transform. `screenToFlowPosition`
    // wants client coordinates, which the pane's own width and height are not
    // unless the pane happens to start at the window edge.
    const { x: tx, y: ty, zoom } = getViewport();
    let spot = {
      x: (paneWidth / 2 - tx) / zoom - NODE_W / 2,
      y: (paneHeight / 3 - ty) / zoom,
    };
    const overlaps = (p: { x: number; y: number }) =>
      graph.nodes.some(
        (n) =>
          Math.abs(n.position.x - p.x) < NODE_W * 0.75 &&
          Math.abs(n.position.y - p.y) < NODE_H * 0.75,
      );
    for (let i = 0; i < 60 && overlaps(spot); i += 1) {
      spot = { x: spot.x + 40, y: spot.y + 40 };
    }
    return { x: Math.round(spot.x), y: Math.round(spot.y) };
  }, [graph.nodes, getViewport, paneWidth, paneHeight]);

  const addNode = useCallback(
    (type: "conversation" | "end") => {
      if (readOnly) return;
      const taken = new Set(graph.nodes.map((n) => n.key));
      const name = type === "end" ? "End call" : `Step ${graph.nodes.length + 1}`;
      // "End call" derives the key `end_call`, which is the name of a *tool*, not
      // the terminal node the built-in tools transition to. Claim the reserved
      // key instead when it is free, so an end node added here is the one the
      // runtime already knows how to reach.
      const key =
        type === "end" && !taken.has("call_ended") ? "call_ended" : keyFromName(name, taken);
      // A graph with no start node is a publish error, and the first node you
      // draw on a blank canvas is obviously the start. Claiming it here means
      // one fewer error to chase on a graph you have barely begun.
      const hasStart = graph.nodes.some((n) => n.data.isStart);
      const node: ApiNode = {
        id: uniqueId("n"),
        key,
        type,
        position: freeSpot(),
        data: {
          ...newNodeData(name),
          isStart: type === "conversation" && !hasStart,
          endConversation: type === "end",
        },
      };
      commit({ ...graph, nodes: [...graph.nodes, node] });
      setSelection({ kind: "node", id: node.id });
    },
    [graph, commit, readOnly, freeSpot],
  );

  const selectedNode =
    selection.kind === "node" ? (graph.nodes.find((n) => n.id === selection.id) ?? null) : null;
  const selectedEdge =
    selection.kind === "edge" ? (graph.edges.find((e) => e.id === selection.id) ?? null) : null;

  // Identity of the *set* of nodes — a load or an add/delete refits, a drag does not.
  const fitSignature = useMemo(
    () =>
      rfNodes
        .map((n) => n.id)
        .sort()
        .join("|"),
    [rfNodes],
  );

  const autoLayout = useCallback(() => {
    const positions = layeredLayout(
      graph.nodes.map((n) => ({ id: n.id, data: { isStart: n.data.isStart } })),
      [...graph.edges, ...implicitEdges].map((e) => ({ source: e.source, target: e.target })),
    );
    commit({
      ...graph,
      nodes: graph.nodes.map((n) => ({ ...n, position: positions[n.id] ?? n.position })),
    });
    // Positions change but the node *set* does not, so FitToGraph deliberately
    // stays put — the camera has to be moved by hand here or the freshly tidied
    // graph is laid out somewhere off-screen.
    window.setTimeout(() => void fitView({ padding: 0.15, duration: 300 }), 60);
  }, [graph, implicitEdges, commit, fitView]);

  const allEdges = useMemo(() => [...rfEdges, ...implicitEdges], [rfEdges, implicitEdges]);

  const errorCount = issues.filter((i) => i.severity === "error").length;
  const warningCount = issues.length - errorCount;
  // `issues` describes `validatedGraph`, which is only `graph` once a response
  // for this exact object has landed.
  const stale = validatedGraph !== graph;
  const neverChecked = validatedGraph === null;

  const nodeName = (id: string) => graph.nodes.find((n) => n.id === id)?.data.name ?? "(deleted)";

  /** Move the camera onto a node or edge and select it. Used by the issue list. */
  const revealIssue = useCallback(
    (issue: FlowIssue) => {
      if (issue.nodeId && graph.nodes.some((n) => n.id === issue.nodeId)) {
        setSelection({ kind: "node", id: issue.nodeId });
        void fitView({
          nodes: [{ id: issue.nodeId }],
          padding: 0.6,
          duration: 300,
          maxZoom: 1.2,
        });
        return;
      }
      if (issue.edgeId) {
        const edge = graph.edges.find((e) => e.id === issue.edgeId);
        if (!edge) return;
        setSelection({ kind: "edge", id: edge.id });
        void fitView({
          nodes: [{ id: edge.source }, { id: edge.target }],
          padding: 0.4,
          duration: 300,
          maxZoom: 1.2,
        });
      }
    },
    [graph.nodes, graph.edges, fitView],
  );

  // Fullscreen escapes the Studio's three-column grid via `fixed`, so the
  // parent needs to know nothing about it. The canvas otherwise gets about a
  // third of the width and a fixed 576px height, which is unusable for a graph
  // of any size.
  const [fullscreen, setFullscreen] = useState(false);
  const [reloading, setReloading] = useState(false);
  /** Reload-built-in confirmation; see the AlertDialog at the foot of this component. */
  const [confirmReload, setConfirmReload] = useState(false);

  /**
   * Replace the graph with the built-in script as it exists today.
   *
   * The only way to load it used to be the empty-state button, which a graph
   * you already have hides — so a card whose stored graph was exported before a
   * fix to `voice/flows.py` had no route to the corrected version except
   * deleting every node by hand. That is exactly how a published clone kept a
   * `gated_upsell` node with no way out of it.
   */
  const reloadBuiltIn = useCallback(() => {
    if (readOnly) return;
    setReloading(true);
    void fetchBuiltInFlow()
      .then((g) => {
        commit(g);
        setSelection({ kind: "none" });
        toast.success(
          `Loaded the built-in script — ${g.nodes.length} steps. Publish to make it live.`,
        );
      })
      // Without this the request failing was an unhandled rejection and a
      // button that quietly stopped saying "Loading…": the graph you were
      // about to replace is still there, and nothing tells you why.
      .catch((err: unknown) =>
        toast.error(err instanceof Error ? err.message : "Could not load the built-in flow"),
      )
      .finally(() => setReloading(false));
  }, [commit, readOnly]);

  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false);
    };
    window.addEventListener("keydown", onKey);
    // Stop the page behind the overlay from scrolling under it.
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [fullscreen]);

  const stats = [
    `${graph.nodes.length} step${graph.nodes.length === 1 ? "" : "s"}`,
    `${graph.edges.length} transition${graph.edges.length === 1 ? "" : "s"}`,
  ].join(" · ");

  return (
    <div
      className={cn(
        "flex min-h-0",
        fullscreen ? "fixed inset-0 z-50 h-screen w-screen bg-background p-200" : "h-full",
      )}
    >
      {/* One surface, split — not two bordered cards.
          SplitPanes draws its own 6px rule between the panes, so a border on
          each side of it stacked three vertical lines in a row and made the
          inspector read as a separate window rather than the other half of the
          editor. The frame belongs to the pair; the rule is internal to it. */}
      <div className="flex min-h-0 flex-1 overflow-hidden rounded-medium border border-border bg-surface">
        <SplitPanes
          storageKey="flow.canvas.panes"
          defaultWidths={[70, 30]}
          minWidthsPx={[420, 300]}
          className="min-h-0 flex-1"
        >
          {/* ─────────────────────────── canvas ─────────────────────────── */}
          <div className="flex h-full min-h-0 flex-col">
            {/* Chrome in the layout, not floating over the drawing.
                Every control here used to be an absolutely-positioned overlay,
                which cost the canvas its most useful strip — the top, where the
                start step lands after a fit — and left the groups with no shared
                baseline to align to. A real toolbar cannot collide with a real
                status bar, at any width, ever. */}
            <div className="flex shrink-0 items-center gap-100 overflow-x-auto border-b border-border px-100 py-075">
              <div className="flex shrink-0 items-center gap-050">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => addNode("conversation")}
                  disabled={readOnly}
                >
                  <Plus className="mr-050 h-3.5 w-3.5" /> Step
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => addNode("end")}
                  disabled={readOnly}
                  title="A terminal step — the call hangs up here"
                >
                  <PhoneOff className="mr-050 h-3.5 w-3.5" /> End
                </Button>
              </div>

              <Rule />

              <Button
                variant="ghost"
                size="sm"
                onClick={autoLayout}
                disabled={readOnly || graph.nodes.length === 0}
                title="Lay the graph out top-down, following its transitions"
              >
                <LayoutGrid className="mr-050 h-3.5 w-3.5" /> Tidy
              </Button>

              {/* Reload discards every step, transition and edit on the canvas.
                  Beside "Tidy" — one click away, same size, same weight — it was
                  a destructive action dressed as a view action. Behind an
                  overflow menu it is still one click away for anyone who wants
                  it, and no longer something you hit on the way to Tidy. */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" title="More actions">
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-64">
                  <DropdownMenuItem
                    disabled={readOnly || reloading}
                    // Straight to state. This used to schedule the action on
                    // a zero-delay timer purely because `window.confirm` blocks
                    // the renderer, and blocking inside `onSelect` froze Radix
                    // mid-close with the menu still painted behind the browser
                    // dialog. An in-app AlertDialog does not block, so the
                    // workaround leaves with the thing it was working around.
                    onSelect={() => setConfirmReload(true)}
                  >
                    <RotateCcw className="mr-075 h-3.5 w-3.5" />
                    {reloading ? "Loading…" : "Reload built-in script…"}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>

              <div className="ml-auto flex shrink-0 items-center gap-050">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => void fitView({ padding: 0.15, duration: 200 })}
                  title="Fit the graph to the view"
                >
                  <Crosshair className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setFullscreen((v) => !v)}
                  title={fullscreen ? "Exit full screen (Esc)" : "Full screen"}
                >
                  {fullscreen ? (
                    <Minimize2 className="h-4 w-4" />
                  ) : (
                    <Maximize2 className="h-4 w-4" />
                  )}
                </Button>

                <Rule />

                {/* The one piece of state that decides whether this can be
                    published, so it takes the semantic pill rather than another
                    grey chip at the same weight as the fullscreen toggle. */}
                {neverChecked ? (
                  // Says what it knows. "Valid" here would be a green tick for
                  // a graph nobody has looked at.
                  <Lozenge tone="neutral">
                    <Loader2 className="animate-spin" />
                    Checking…
                  </Lozenge>
                ) : (
                  <Lozenge
                    // Dimmed while the answer describes the previous edit. The
                    // counts are usually still right and flickering them to
                    // "Checking…" on every keystroke would be unreadable, but
                    // they must not look confirmed when they are not.
                    className={cn(stale && "opacity-60")}
                    title={
                      stale ? "Re-checking — these counts describe the previous edit" : undefined
                    }
                    tone={errorCount > 0 ? "danger" : warningCount > 0 ? "warning" : "success"}
                  >
                    {errorCount > 0 ? (
                      <>
                        <AlertTriangle />
                        {errorCount} error{errorCount === 1 ? "" : "s"}
                      </>
                    ) : warningCount > 0 ? (
                      <>
                        <AlertTriangle />
                        {warningCount} warning{warningCount === 1 ? "" : "s"}
                      </>
                    ) : (
                      <>
                        <CheckCircle2 />
                        Valid
                      </>
                    )}
                  </Lozenge>
                )}
              </div>
            </div>

            <div className="relative min-h-0 flex-1">
              <FlowEdgeMarkers />
              <ReactFlow
                nodes={rfNodes}
                edges={allEdges}
                nodeTypes={flowNodeTypes}
                edgeTypes={flowEdgeTypes}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                isValidConnection={isValidConnection}
                onNodeClick={(_, node) => setSelection({ kind: "node", id: node.id })}
                onEdgeClick={(_, edge) => {
                  // Implicit edges belong to a tool, not the graph — selecting
                  // one would point the inspector at an id it cannot find.
                  if (edge.id.startsWith(IMPLICIT_PREFIX)) return;
                  setSelection({ kind: "edge", id: edge.id });
                }}
                onPaneClick={() => setSelection({ kind: "none" })}
                nodesConnectable={!readOnly}
                nodesDraggable={!readOnly}
                // Backspace alone is the xyflow default, and on Windows the key
                // people press to delete a selected thing is Delete.
                deleteKeyCode={readOnly ? null : ["Backspace", "Delete"]}
                minZoom={MIN_ZOOM}
                maxZoom={MAX_ZOOM}
                fitView
                colorMode={dark ? "dark" : "light"}
                proOptions={{ hideAttribution: true }}
              >
                <FitToGraph signature={`${fullscreen ? "fs" : "inline"}|${fitSignature}`} />
                <Background gap={18} size={1} />
              </ReactFlow>
            </div>

            {/* Document stats, zoom, and the key to the three edge treatments —
                the things you consult rather than operate, along the bottom edge
                where a document's status belongs. */}
            <div className="flex shrink-0 items-center gap-100 overflow-hidden border-t border-border px-100 py-050 text-body-micro text-text-subtlest">
              <ZoomControls />

              <Rule />

              <span className="truncate tabular-nums">{stats}</span>

              {implicitEdges.length > 0 && (
                <span
                  className="shrink-0 tabular-nums"
                  title="Performed by the built-in tools, not authored here. Not saved with the graph."
                >
                  · {implicitEdges.length} implicit
                </span>
              )}
              {(graph.globalTools?.length ?? 0) > 0 && (
                <button
                  type="button"
                  onClick={() => setSelection({ kind: "none" })}
                  className="focus-ring shrink-0 rounded-small tabular-nums underline-offset-2 hover:text-text hover:underline"
                  title={`Available from every step: ${(graph.globalTools ?? []).join(", ")}. Click to edit.`}
                >
                  · {graph.globalTools.length} global
                </button>
              )}

              {/* Three edge treatments carry three different meanings and none
                  of them is guessable. Dropped rather than wrapped when the pane
                  is too narrow to hold it on one line. */}
              {allEdges.length > 0 && paneWidth >= 720 && (
                <div className="ml-auto flex shrink-0 items-center gap-150">
                  <span className="flex items-center gap-050">
                    <EdgeSwatch color="var(--border-bold)" />
                    the model decides
                  </span>
                  <span className="flex items-center gap-050">
                    <EdgeSwatch color="var(--border-bold)" dash="7 4" />a captured value
                  </span>
                  <span className="flex items-center gap-050">
                    <EdgeSwatch color="var(--text-subtlest)" dash="1 4" width={1.2} round />a tool
                    moves the call
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* ────────────────────────── inspector ────────────────────────── */}
          <div className="h-full min-h-0">
            {selectedNode ? (
              <NodeInspector
                key={selectedNode.id}
                node={selectedNode}
                tools={toolsQuery.data ?? []}
                reservedKeys={reservedQuery.data ?? {}}
                issues={issuesByNode.get(selectedNode.id) ?? []}
                readOnly={readOnly}
                onChange={(next) =>
                  commit({
                    ...graph,
                    nodes: graph.nodes.map((n) =>
                      n.id === next.id
                        ? next
                        : // Only one node can be the start node.
                          next.data.isStart && n.data.isStart
                          ? { ...n, data: { ...n.data, isStart: false } }
                          : n,
                    ),
                  })
                }
                onDelete={() => onNodesChange([{ type: "remove", id: selectedNode.id }])}
              />
            ) : selectedEdge ? (
              <EdgeInspector
                key={selectedEdge.id}
                edge={selectedEdge}
                sourceName={nodeName(selectedEdge.source)}
                targetName={nodeName(selectedEdge.target)}
                issues={issuesByEdge.get(selectedEdge.id) ?? []}
                readOnly={readOnly}
                onChange={(next) =>
                  commit({
                    ...graph,
                    edges: graph.edges.map((e) => (e.id === next.id ? next : e)),
                  })
                }
                onDelete={() => onEdgesChange([{ type: "remove", id: selectedEdge.id }])}
              />
            ) : (
              <GraphInspector
                globalTools={graph.globalTools ?? []}
                tools={toolsQuery.data ?? []}
                issues={issues}
                nodeNames={new Map(graph.nodes.map((n) => [n.id, n.data.name || n.key]))}
                readOnly={readOnly}
                onSelectIssue={revealIssue}
                onChange={(next) => commit({ ...graph, globalTools: next })}
              />
            )}
          </div>
        </SplitPanes>
      </div>
      {/* Replaces a window.confirm. Reload discards every node, transition and
          edit on the canvas, so it is worth asking — but asked in the product's
          own surface: themed, escapable, and it names what is lost rather than
          restating the click. */}
      <AlertDialog
        open={confirmReload}
        onOpenChange={(next) => {
          if (!next) setConfirmReload(false);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Replace this graph with the built-in script?</AlertDialogTitle>
            <AlertDialogDescription>
              Every node, transition and edit on this canvas is discarded. Nothing changes for live
              callers until you publish.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep this graph</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setConfirmReload(false);
                reloadBuiltIn();
              }}
            >
              Replace it
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export { emptyGraph };
