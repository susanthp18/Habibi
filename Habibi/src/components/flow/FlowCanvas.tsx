import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  useStore,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { toast } from "sonner";
import {
  Crosshair,
  LayoutGrid,
  Maximize2,
  Minimize2,
  MoreHorizontal,
  PhoneOff,
  Plus,
  RotateCcw,
} from "lucide-react";
import { SplitPanes } from "@/components/shared/SplitPanes";
import { useTheme } from "@/lib/theme";

import {
  defaultCondition,
  emptyGraph,
  fetchBuiltInFlow,
  newNodeData,
  useFlowTools,
  useFlowTransitions,
  useReservedKeys,
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
import { cn } from "@/lib/utils";
import { flowToolChoices } from "@/lib/studio-contract";
import { FlowEdgeMarkers, flowEdgeTypes } from "./FlowConditionEdge";
import { flowNodeTypes } from "./FlowNodes";
import { EdgeInspector, GraphInspector, NodeInspector } from "./inspector";
import { IMPLICIT_PREFIX, NODE_W, keyFromName, layeredLayout, uniqueId } from "./canvas/layout";
import {
  CanvasStatusBar,
  FitToGraph,
  MAX_ZOOM,
  MIN_ZOOM,
  ReloadBuiltInDialog,
  Rule,
  ValidityPill,
} from "./canvas/chrome";
import { useCanvasValidation } from "./canvas/useCanvasValidation";
import { useCanvasGraph, type Selection } from "./canvas/useCanvasGraph";

export function FlowCanvas({
  graph,
  onChange,
  onValidation,
  readOnly = false,
  grantTools,
}: {
  graph: FlowGraph;
  onChange: (next: FlowGraph) => void;
  onValidation?: (result: { ok: boolean; issues: FlowIssue[] }) => void;
  readOnly?: boolean;
  /** Compiled grant. Flow choices intersect this with the catalog. */
  grantTools?: string[];
}) {
  return (
    <ReactFlowProvider>
      <FlowCanvasInner
        graph={graph}
        onChange={onChange}
        onValidation={onValidation}
        readOnly={readOnly}
        grantTools={grantTools}
      />
    </ReactFlowProvider>
  );
}

function FlowCanvasInner({
  graph,
  onChange,
  onValidation,
  readOnly,
  grantTools,
}: {
  graph: FlowGraph;
  onChange: (next: FlowGraph) => void;
  onValidation?: (result: { ok: boolean; issues: FlowIssue[] }) => void;
  readOnly: boolean;
  grantTools?: string[];
}) {
  const [selection, setSelection] = useState<Selection>({ kind: "none" });
  const check = useCanvasValidation(graph, onValidation);
  const { issues, issuesByNode, issuesByEdge } = check;
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
  const pickerTools = flowToolChoices(toolsQuery.data ?? [], grantTools);
  const reservedQuery = useReservedKeys();
  const transitionsQuery = useFlowTransitions();
  const dark = useTheme() === "dark";

  const { implicitEdges, rfNodes, rfEdges } = useCanvasGraph({
    graph,
    grantTools,
    tools: toolsQuery.data,
    transitions: transitionsQuery.data,
    reserved: reservedQuery.data,
    issuesByNode,
    issuesByEdge,
    selection,
  });

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
            {transitionsQuery.isError ? (
              <div
                role="status"
                className="shrink-0 border-b border-border-warning bg-background-warning-subtler px-100 py-075 text-body-small text-text-warning-bolder"
              >
                Tool-driven hops could not be read, so the dashed edges are missing and no step is
                marked a dead end. The graph is unchanged — this is the canvas missing information,
                not the script missing exits.
              </div>
            ) : null}
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
                <ValidityPill
                  neverChecked={check.neverChecked}
                  stale={check.stale}
                  errorCount={check.errorCount}
                  warningCount={check.warningCount}
                />
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

            <CanvasStatusBar
              graph={graph}
              implicitCount={implicitEdges.length}
              showLegend={allEdges.length > 0 && paneWidth >= 720}
              onEditGlobals={() => setSelection({ kind: "none" })}
            />
          </div>

          {/* ────────────────────────── inspector ────────────────────────── */}
          <div className="h-full min-h-0">
            {selectedNode ? (
              <NodeInspector
                key={selectedNode.id}
                node={selectedNode}
                tools={pickerTools}
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
                graph={graph}
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
                tools={pickerTools}
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
      <ReloadBuiltInDialog
        open={confirmReload}
        onOpenChange={setConfirmReload}
        onConfirm={reloadBuiltIn}
      />
    </div>
  );
}

export { emptyGraph };
