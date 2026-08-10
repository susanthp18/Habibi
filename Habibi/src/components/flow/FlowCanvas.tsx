import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AlertTriangle, CheckCircle2, Plus, PhoneOff } from "lucide-react";

import {
  defaultCondition,
  emptyGraph,
  isEmptyGraph,
  newNodeData,
  useFlowTools,
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
import { EdgeInspector, NodeInspector } from "./FlowInspector";

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
          onValidation?.(result);
        })
        .catch(() => {
          /* transient: keep the last known issues rather than clearing them */
        });
    }, 400);
    return () => window.clearTimeout(timer);
  }, [graph, onValidation]);

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
      // Selection is owned by the inspector, not by xyflow, so those changes
      // are dropped here and re-derived above. Removals are handled explicitly
      // so their edges go with them.
      const positional = changes.filter(
        (c) => c.type !== "select" && c.type !== "remove",
      );
      const removed = changes
        .filter((c): c is NodeChange & { type: "remove"; id: string } => c.type === "remove")
        .map((c) => c.id);

      let nodes = graph.nodes;
      if (positional.length > 0) {
        const applied = applyNodeChanges(positional, rfNodes);
        const positions = new Map(applied.map((n) => [n.id, n.position]));
        nodes = nodes.map((n) => ({ ...n, position: positions.get(n.id) ?? n.position }));
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
          .map((c) => c.id),
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
    const node: ApiNode = {
      id: uniqueId("n"),
      key: keyFromName(name, taken),
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

  const errorCount = issues.filter((i) => i.severity === "error").length;
  const warningCount = issues.length - errorCount;

  const nodeName = (id: string) =>
    graph.nodes.find((n) => n.id === id)?.data.name ?? "(deleted)";

  return (
    <div className="flex h-full min-h-0 gap-150">
      <div className="relative min-w-0 flex-1 overflow-hidden rounded-medium border border-border">
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={flowNodeTypes}
          edgeTypes={flowEdgeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={(_, node) => setSelection({ kind: "node", id: node.id })}
          onEdgeClick={(_, edge) => setSelection({ kind: "edge", id: edge.id })}
          onPaneClick={() => setSelection({ kind: "none" })}
          nodesConnectable={!readOnly}
          nodesDraggable={!readOnly}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable className="!bg-surface-sunken" />

          <Panel position="top-left" className="flex gap-050">
            <Button variant="outline" size="sm" onClick={() => addNode("conversation")} disabled={readOnly}>
              <Plus className="mr-050 h-3.5 w-3.5" /> Step
            </Button>
            <Button variant="outline" size="sm" onClick={() => addNode("end")} disabled={readOnly}>
              <PhoneOff className="mr-050 h-3.5 w-3.5" /> End
            </Button>
          </Panel>

          <Panel position="top-right">
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

      <aside className="w-80 shrink-0 overflow-y-auto rounded-medium border border-border bg-surface p-150">
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
          <div className="space-y-100 text-body-small leading-relaxed text-text-subtlest">
            <p className="font-semibold text-text">Nothing selected</p>
            <p>
              Click a step to edit its instructions, tools and captured values.
              Click a transition to set when it fires.
            </p>
            <p>Drag from the bottom of a step to its next step to connect them.</p>
            {issues.length > 0 && (
              <ul className="space-y-050 pt-100">
                {issues.map((issue, i) => (
                  <li
                    key={`${issue.code}-${i}`}
                    className={cn(
                      "rounded-small px-100 py-075",
                      issue.severity === "error"
                        ? "bg-background-danger text-text-danger"
                        : "bg-surface-sunken text-text-subtle",
                    )}
                  >
                    {issue.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}

export { emptyGraph };
