/** Ids, keys and the auto-layout: the canvas's arithmetic, with no React in it. */

import { at } from "@/lib/arrays";

/** Card width in FlowNodes (`w-72`), which the layout has to reserve room for. */
export const NODE_W = 288;

let idCounter = 0;
/**
 * Date.now() alone collides for two nodes added in the same millisecond, which
 * produces a graph with duplicate ids that only fails at save.
 */
export function uniqueId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${Date.now().toString(36)}-${idCounter}`;
}

export function keyFromName(name: string, taken: Set<string>): string {
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

export const IMPLICIT_PREFIX = "implicit:";

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
export function layeredLayout(
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

  const start = nodes.find((n) => n.data.isStart) ?? at(nodes, 0);

  // Iterative three-colour DFS. Iterative rather than recursive so a wide graph
  // cannot overflow the stack inside a render.
  const back = new Set<string>();
  const colour = new Map<string, 0 | 1 | 2>();
  for (const root of [start.id, ...nodes.map((n) => n.id)]) {
    if ((colour.get(root) ?? 0) !== 0) continue;
    colour.set(root, 1);
    const stack: { id: string; i: number }[] = [{ id: root, i: 0 }];
    for (let top = stack.at(-1); top !== undefined; top = stack.at(-1)) {
      const kids = outgoing.get(top.id) ?? [];
      if (top.i >= kids.length) {
        colour.set(top.id, 2);
        stack.pop();
        continue;
      }
      const next = at(kids, top.i);
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
