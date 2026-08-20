import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  useNodesInitialized,
  useStore,
  useReactFlow,
  useUpdateNodeInternals,
  type EdgeProps,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlertTriangle,
  CheckCircle2,
  Plus,
  PhoneOff,
  Maximize2,
  Minimize2,
  LayoutGrid,
  Crosshair,
  RotateCcw,
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
import { cn } from "@/lib/utils";
import { flowEdgeTypes } from "./FlowConditionEdge";
import { flowNodeTypes, type CanvasNodeData } from "./FlowNodes";
import { EdgeInspector, GraphInspector, NodeInspector } from "./FlowInspector";

type Selection =
  | { kind: "none" }
  | { kind: "node"; id: string }
  | { kind: "edge"; id: string };

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


/**
 * Move the camera to the graph whenever the node set changes.
 *
 * The `fitView` prop only fits during init, and it fits against whatever
 * dimensions exist at that moment — custom nodes are measured after the first
 * paint, so the initial fit lands on zero-sized nodes and the camera stays put.
 * Loading the built-in script made that obvious: 12 nodes spanning x 0..2240
 * arrived and the pane looked empty.
 *
 * Keyed on the node ids rather than the whole graph, so dragging a node or
 * editing its text does not yank the camera back mid-edit.
 *
 * Lives inside <ReactFlow> because that is what provides the store the hooks
 * read; the parent component is outside it.
 */
const IMPLICIT_PREFIX = "implicit:";



/** Layered top-down positions, keyed by node id. Used by Auto-layout. */
function layeredLayout(
  nodes: { id: string; data: { isStart: boolean } }[],
  edges: { source: string; target: string }[],
): Record<string, { x: number; y: number }> {
  const COL = 320;
  const ROW = 170;
  const out: Record<string, { x: number; y: number }> = {};
  if (nodes.length === 0) return out;

  const outgoing = new Map<string, string[]>();
  for (const e of edges) {
    if (e.source === e.target) continue;
    outgoing.set(e.source, [...(outgoing.get(e.source) ?? []), e.target]);
  }

  // Depth by BFS from the start node. Anything the walk cannot reach — an
  // orphan, or a node only reachable through a tool hop we do not model — is
  // parked in a trailing layer rather than dropped on the origin.
  const start = nodes.find((n) => n.data.isStart) ?? nodes[0];
  const depth = new Map<string, number>([[start.id, 0]]);
  const queue = [start.id];
  while (queue.length) {
    const id = queue.shift() as string;
    for (const next of outgoing.get(id) ?? []) {
      if (depth.has(next)) continue;
      depth.set(next, (depth.get(id) ?? 0) + 1);
      queue.push(next);
    }
  }
  const maxDepth = Math.max(0, ...depth.values());
  for (const n of nodes) if (!depth.has(n.id)) depth.set(n.id, maxDepth + 1);

  const layers = new Map<number, string[]>();
  for (const n of nodes) {
    const d = depth.get(n.id) ?? 0;
    layers.set(d, [...(layers.get(d) ?? []), n.id]);
  }
  for (const [d, ids] of layers) {
    ids.forEach((id, i) => {
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
  const toolsQuery = useFlowTools();
  const reservedQuery = useReservedKeys();
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
      return;
    }
    const timer = window.setTimeout(() => {
      void validateFlow(graph)
        .then((result) => {
          setIssues(result.issues);
          onValidationRef.current?.(result);
        })
        .catch(() => {
          /* transient: keep the last known issues rather than clearing them */
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

  const rfNodes: Node[] = useMemo(
    () =>
      graph.nodes.map((n) => {
        const own = issuesByNode.get(n.id) ?? [];
        const data: CanvasNodeData = {
          ...n.data,
          nodeKey: n.key,
          errorCount: own.filter((i) => i.severity === "error").length,
          warningCount: own.filter((i) => i.severity === "warning").length,
        };
        return {
          id: n.id,
          type: n.type,
          position: n.position,
          data: data as unknown as Record<string, unknown>,
          selected: selection.kind === "node" && selection.id === n.id,
        };
      }),
    [graph.nodes, issuesByNode, selection],
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
          hasError: (issuesByEdge.get(e.id) ?? []).some(
            (i) => i.severity === "error",
          ),
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

      let nodes = graph.nodes;
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
        if (!moved) nodes = graph.nodes;
      }
      if (removed.length === 0) {
        if (nodes !== graph.nodes) onChange({ ...graph, nodes });
        return;
      }
      const gone = new Set(removed);
      onChange({
        ...graph,
        nodes: nodes.filter((n) => !gone.has(n.id)),
        // An edge to a deleted node is a dangling reference, i.e. a save error.
        edges: graph.edges.filter((e) => !gone.has(e.source) && !gone.has(e.target)),
      });
      setSelection({ kind: "none" });
    },
    [graph, onChange, readOnly, rfNodes],
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
      onChange({ ...graph, edges: graph.edges.filter((e) => !removed.has(e.id)) });
      setSelection({ kind: "none" });
    },
    [graph, onChange, readOnly],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (readOnly || !connection.source || !connection.target) return;
      // A node that transitions to itself is a loop the runtime takes forever;
      // on the canvas it draws as a stub behind the card, so the author cannot
      // see what they made. Rejected here and by the validator.
      if (connection.source === connection.target) return;
      const exists = graph.edges.some(
        (e) => e.source === connection.source && e.target === connection.target,
      );
      // Rejected here rather than at save: the duplicate is invisible on the
      // canvas (the two edges overlap exactly) and the error would be baffling.
      if (exists) return;
      const edge: ApiEdge = {
        id: uniqueId("e"),
        source: connection.source,
        target: connection.target,
        data: { condition: defaultCondition("prompt") },
      };
      onChange({ ...graph, edges: [...graph.edges, edge] });
      setSelection({ kind: "edge", id: edge.id });
    },
    [graph, onChange, readOnly],
  );

  const addNode = (type: "conversation" | "end") => {
    if (readOnly) return;
    const taken = new Set(graph.nodes.map((n) => n.key));
    const name = type === "end" ? "End call" : `Step ${graph.nodes.length + 1}`;
    // "End call" derives the key `end_call`, which is the name of a *tool*, not
    // the terminal node the built-in tools transition to. Claim the reserved
    // key instead when it is free, so an end node added here is the one the
    // runtime already knows how to reach.
    const key =
      type === "end" && !taken.has("call_ended")
        ? "call_ended"
        : keyFromName(name, taken);
    const node: ApiNode = {
      id: uniqueId("n"),
      key,
      type,
      position: {
        x: 60 + (graph.nodes.length % 3) * 300,
        y: 60 + Math.floor(graph.nodes.length / 3) * 220,
      },
      data: {
        ...newNodeData(name),
        endConversation: type === "end",
      },
    };
    onChange({ ...graph, nodes: [...graph.nodes, node] });
    setSelection({ kind: "node", id: node.id });
  };

  const selectedNode =
    selection.kind === "node"
      ? graph.nodes.find((n) => n.id === selection.id) ?? null
      : null;
  const selectedEdge =
    selection.kind === "edge"
      ? graph.edges.find((e) => e.id === selection.id) ?? null
      : null;

  // Identity of the *set* of nodes — a load or an add/delete refits, a drag does not.
  const fitSignature = useMemo(
    () => rfNodes.map((n) => n.id).sort().join("|"),
    [rfNodes],
  );

  const transitionsQuery = useFlowTransitions();
  const { fitView } = useReactFlow();

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
    const byKey = new Map(graph.nodes.map((n) => [n.key, n.id]));
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

  const allEdges = useMemo(() => [...rfEdges, ...implicitEdges], [rfEdges, implicitEdges]);

  const autoLayout = useCallback(() => {
    const positions = layeredLayout(
      graph.nodes.map((n) => ({ id: n.id, data: { isStart: n.data.isStart } })),
      [...graph.edges, ...implicitEdges].map((e) => ({ source: e.source, target: e.target })),
    );
    onChange({
      ...graph,
      nodes: graph.nodes.map((n) => ({ ...n, position: positions[n.id] ?? n.position })),
    });
  }, [graph, implicitEdges, onChange]);

  const errorCount = issues.filter((i) => i.severity === "error").length;
  const warningCount = issues.length - errorCount;

  const nodeName = (id: string) =>
    graph.nodes.find((n) => n.id === id)?.data.name ?? "(deleted)";

  // Fullscreen escapes the Studio's three-column grid via `fixed`, so the
  // parent needs to know nothing about it. The canvas otherwise gets about a
  // third of the width and a fixed 576px height, which is unusable for a graph
  // of any size.
  const [fullscreen, setFullscreen] = useState(false);
  const [reloading, setReloading] = useState(false);

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
    if (
      !window.confirm(
        "Replace this graph with the current built-in script?\n\n" +
          "Every node, transition and edit on this canvas is discarded. " +
          "Nothing changes for live callers until you publish.",
      )
    ) {
      return;
    }
    setReloading(true);
    void fetchBuiltInFlow()
      .then((g) => {
        onChange(g);
        setSelection({ kind: "none" });
      })
      .finally(() => setReloading(false));
  }, [onChange, readOnly]);

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

  return (
    <div
      className={cn(
        "flex min-h-0 gap-150",
        fullscreen
          ? "fixed inset-0 z-50 h-screen w-screen bg-background p-200"
          : "h-full",
      )}
    >
      <SplitPanes
        storageKey="flow.canvas.panes"
        defaultWidths={[68, 32]}
        minWidthsPx={[360, 280]}
        className="min-h-0 flex-1"
      >
      <div className="relative h-full min-h-0 min-w-0 overflow-hidden rounded-medium border border-border">
        <ReactFlow
          nodes={rfNodes}
          edges={allEdges}
          nodeTypes={flowNodeTypes}
          edgeTypes={flowEdgeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={(_, node) => setSelection({ kind: "node", id: node.id })}
          onEdgeClick={(_, edge) => {
            // Implicit edges belong to a tool, not the graph — selecting one
            // would point the inspector at an id it cannot find.
            if (edge.id.startsWith(IMPLICIT_PREFIX)) return;
            setSelection({ kind: "edge", id: edge.id });
          }}
          onPaneClick={() => setSelection({ kind: "none" })}
          nodesConnectable={!readOnly}
          nodesDraggable={!readOnly}
          fitView
          colorMode={dark ? "dark" : "light"}
          proOptions={{ hideAttribution: true }}
        >
          <FitToGraph signature={`${fullscreen ? "fs" : "inline"}|${fitSignature}`} />
          <Background />
          <Controls showInteractive={false} />
          {/* Colours are explicit because the defaults are invisible here: the
              minimap paints nodes #e2e2e2 on its own white background, which is
              within a hair of --surface-sunken in light mode and ignores the
              dark theme entirely — the widget rendered, and looked like an
              empty grey box. Since every node has to be painted anyway, the
              fill carries meaning: what is broken, where the call starts, and
              where it ends. */}

          <Panel position="top-left" className="flex gap-050">
            <Button variant="outline" size="sm" onClick={() => addNode("conversation")} disabled={readOnly}>
              <Plus className="mr-050 h-3.5 w-3.5" /> Step
            </Button>
            <Button variant="outline" size="sm" onClick={() => addNode("end")} disabled={readOnly}>
              <PhoneOff className="mr-050 h-3.5 w-3.5" /> End
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={autoLayout}
              disabled={readOnly || graph.nodes.length === 0}
              title="Lay the graph out top-down, following its transitions"
            >
              <LayoutGrid className="mr-050 h-3.5 w-3.5" /> Tidy
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={reloadBuiltIn}
              disabled={readOnly || reloading}
              title="Replace this graph with the current built-in collections script"
            >
              <RotateCcw className="mr-050 h-3.5 w-3.5" />
              {reloading ? "Loading…" : "Reload built-in"}
            </Button>
          </Panel>

          <Panel position="top-right" className="flex items-center gap-050">
            {(graph.globalTools?.length ?? 0) > 0 && (
              <span
                className="rounded-small border border-border bg-surface px-100 py-050 text-caption text-text-subtlest"
                title={`Available from every step: ${(graph.globalTools ?? []).join(", ")}. Click empty canvas to edit.`}
              >
                {graph.globalTools.length} global
              </span>
            )}
            {implicitEdges.length > 0 && (
              <span
                className="rounded-small border border-border bg-surface px-100 py-050 text-caption text-text-subtlest"
                title="Dashed edges are performed by the built-in tools, not authored here. They are not saved with the graph."
              >
                {implicitEdges.length} implicit
              </span>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => void fitView({ padding: 0.15, duration: 200 })}
              title="Fit the graph to the view"
            >
              <Crosshair className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setFullscreen((v) => !v)}
              title={fullscreen ? "Exit full screen (Esc)" : "Full screen"}
            >
              {fullscreen ? (
                <Minimize2 className="h-3.5 w-3.5" />
              ) : (
                <Maximize2 className="h-3.5 w-3.5" />
              )}
            </Button>
            <div
              className={cn(
                "flex items-center gap-050 rounded-small border px-100 py-050 text-body-small",
                errorCount > 0
                  ? "border-border-danger bg-surface text-text-danger"
                  : "border-border bg-surface text-text-subtle",
              )}
            >
              {errorCount > 0 ? (
                <>
                  <AlertTriangle className="h-3.5 w-3.5" />
                  {errorCount} error{errorCount === 1 ? "" : "s"}
                </>
              ) : (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5 text-text-success" />
                  Valid
                </>
              )}
              {warningCount > 0 && (
                <span className="text-text-subtlest">· {warningCount} warning{warningCount === 1 ? "" : "s"}</span>
              )}
            </div>
          </Panel>
        </ReactFlow>
      </div>

      <aside className="h-full min-h-0 w-full overflow-y-auto rounded-medium border border-border bg-surface p-150">
        {selectedNode ? (
          <NodeInspector
            key={selectedNode.id}
            node={selectedNode}
            tools={toolsQuery.data ?? []}
            reservedKeys={reservedQuery.data ?? {}}
            issues={issuesByNode.get(selectedNode.id) ?? []}
            onChange={(next) =>
              onChange({
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
            onChange={(next) =>
              onChange({
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
            readOnly={readOnly}
            onChange={(next) => onChange({ ...graph, globalTools: next })}
          />
        )}
      </aside>
      </SplitPanes>
    </div>
  );
}

export { emptyGraph };
