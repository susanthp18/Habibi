import dagre from '@dagrejs/dagre';
import { ReactFlowInstance } from "@xyflow/react";

import { FlowEdge, FlowNode, NodeType } from "@/agentstudio/components/flow/types";

// Fallback card size before React Flow has measured a node (BaseNode is
// 320-400px wide and grows with its prompt).
const NODE_WIDTH = 360;
const NODE_HEIGHT = 200;
const GAP_X = 120; // between cards side by side
const GAP_Y = 160; // between rows
const SECTION_GAP = 240; // between the conversation and the side columns

const isStart = (n: FlowNode) => n.type === NodeType.START_CALL;
const isEnd = (n: FlowNode) => n.type === NodeType.END_CALL;
const isConversation = (n: FlowNode) => n.type === NodeType.START_CALL || n.type === NodeType.AGENT_NODE;
const isLeftRail = (n: FlowNode) => n.type === NodeType.GLOBAL_NODE || n.type === NodeType.TRIGGER;

const size = (n: FlowNode) => ({
    width: n.measured?.width ?? NODE_WIDTH,
    height: n.measured?.height ?? NODE_HEIGHT,
});

/** Stack ``column`` top-down at ``x`` from ``top``. */
function stack(column: FlowNode[], x: number, top: number): FlowNode[] {
    let y = top;
    return column.map((node) => {
        const placed = { ...node, position: { x, y } };
        y += size(node).height + GAP_Y / 2;
        return placed;
    });
}

/**
 * A readable layout for any workflow graph.
 *
 * The conversation (start and agent nodes) is laid out top-down by dagre
 * using the cards' real sizes; loops back to earlier steps are ignored for
 * ranking. Every exit (end node) goes in one row underneath, ordered by the
 * nodes that lead to it, so shared exits such as "stop contact" no longer
 * drag the flow apart. Global and trigger nodes sit in a column on the left,
 * everything else (webhooks, QA) on the right.
 */
export function arrangeNodes(nodes: FlowNode[], edges: FlowEdge[]): FlowNode[] {
    const conversation = nodes.filter(isConversation);
    if (conversation.length === 0) return nodes;
    const ends = nodes.filter(isEnd);
    const left = nodes.filter(isLeftRail).sort((a, b) =>
        (a.type === NodeType.GLOBAL_NODE ? 0 : 1) - (b.type === NodeType.GLOBAL_NODE ? 0 : 1));
    const right = nodes.filter((n) => !isConversation(n) && !isEnd(n) && !isLeftRail(n));

    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: 'TB', nodesep: GAP_X, ranksep: GAP_Y, acyclicer: 'greedy', ranker: 'network-simplex' });
    g.setDefaultEdgeLabel(() => ({}));
    // Start first, so dagre ranks from it.
    [...conversation].sort((a, b) => Number(isStart(b)) - Number(isStart(a)))
        .forEach((n) => g.setNode(n.id, size(n)));
    const inConversation = new Set(conversation.map((n) => n.id));
    edges.filter((e) => inConversation.has(e.source) && inConversation.has(e.target) && e.source !== e.target)
        .forEach((e) => g.setEdge(e.source, e.target));
    dagre.layout(g);

    const placed = new Map<string, FlowNode>();
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const node of conversation) {
        const { x, y } = g.node(node.id);
        const { width, height } = size(node);
        const position = { x: x - width / 2, y: y - height / 2 };
        placed.set(node.id, { ...node, position });
        minX = Math.min(minX, position.x);
        maxX = Math.max(maxX, position.x + width);
        minY = Math.min(minY, position.y);
        maxY = Math.max(maxY, position.y + height);
    }

    // Exits: one row under the flow, ordered by where their callers are.
    const centreOf = (id: string) => {
        const n = placed.get(id);
        return n ? n.position.x + size(n).width / 2 : (minX + maxX) / 2;
    };
    const anchor = (end: FlowNode) => {
        const sources = edges.filter((e) => e.target === end.id).map((e) => centreOf(e.source));
        return sources.length ? sources.reduce((a, b) => a + b, 0) / sources.length : maxX;
    };
    const orderedEnds = [...ends].sort((a, b) => anchor(a) - anchor(b));
    const rowWidth = orderedEnds.reduce((w, n) => w + size(n).width, 0) + GAP_X * Math.max(0, orderedEnds.length - 1);
    let x = (minX + maxX) / 2 - rowWidth / 2;
    const endsY = maxY + GAP_Y;
    for (const end of orderedEnds) {
        placed.set(end.id, { ...end, position: { x, y: endsY } });
        x += size(end).width + GAP_X;
    }
    const flowLeft = Math.min(minX, (minX + maxX) / 2 - rowWidth / 2);
    const flowRight = Math.max(maxX, (minX + maxX) / 2 + rowWidth / 2);

    const leftWidth = Math.max(0, ...left.map((n) => size(n).width));
    stack(left, flowLeft - SECTION_GAP - leftWidth, minY).forEach((n) => placed.set(n.id, n));
    stack(right, flowRight + SECTION_GAP, minY).forEach((n) => placed.set(n.id, n));

    return nodes.map((n) => placed.get(n.id) ?? n);
}

/** Whether any two cards overlap: the graph needs arranging. */
export function hasOverlaps(nodes: FlowNode[]): boolean {
    const boxes = nodes.map((n) => ({ ...n.position, ...size(n) }));
    for (let i = 0; i < boxes.length; i++) {
        for (let j = i + 1; j < boxes.length; j++) {
            const a = boxes[i]!, b = boxes[j]!;
            if (a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height) {
                return true;
            }
        }
    }
    return false;
}

export const layoutNodes = (
    nodes: FlowNode[],
    edges: FlowEdge[],
    _rankdir: 'TB' | 'LR',
    rfInstance: React.RefObject<ReactFlowInstance<FlowNode, FlowEdge> | null>
) => {
    const arranged = arrangeNodes(nodes, edges);
    setTimeout(() => {
        rfInstance.current?.fitView({ padding: 0.15, duration: 200 });
    }, 0);
    return arranged;
};
