import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type EdgeProps } from "@xyflow/react";

import { OPERATOR_LABELS, UNARY_OPERATORS, type FlowCondition } from "@/api/flow";
import { cn } from "@/lib/utils";
import { useLabelsVisible } from "./zoom";

/** One-line summary of when this edge fires, for the canvas label. */
export function describeCondition(condition: FlowCondition): string {
  if (condition.type === "always") return "always";
  if (condition.type === "prompt") {
    return condition.prompt?.trim() || "(no condition)";
  }
  const clauses = condition.clauses ?? [];
  if (clauses.length === 0) return "(no clauses)";
  const join = condition.match === "all" ? " and " : " or ";
  return clauses
    .map((c) => {
      const op = OPERATOR_LABELS[c.operator] ?? c.operator;
      const variable = c.variable || "?";
      return UNARY_OPERATORS.has(c.operator)
        ? `${variable} ${op}`
        : `${variable} ${op} ${c.value ?? ""}`.trim();
    })
    .join(join);
}

export type ConditionEdgeData = {
  condition: FlowCondition;
  hasError: boolean;
};

/**
 * Marker ids for the arrowheads.
 *
 * xyflow only emits a `<marker>` into its defs for markers it can see on an
 * edge's `markerEnd`, and it keys them by the serialised marker object — so the
 * three variants below become three defs and are reused across every edge that
 * asks for one. Colours are resolved from the tokens at render time rather than
 * hardcoded, so the arrowheads follow the theme like everything else.
 */
const EDGE_MARKER = {
  normal: "flow-arrow",
  error: "flow-arrow-error",
  implicit: "flow-arrow-implicit",
  selected: "flow-arrow-selected",
} as const;

/**
 * The arrowhead defs.
 *
 * Rendered once, into the canvas, rather than through xyflow's `markerEnd`
 * object form. The object form re-serialises on every render and cannot read a
 * CSS custom property, so a themed arrow had to be either hardcoded per theme
 * or recomputed in JS on every dark-mode flip. A plain `<defs>` referenced by
 * id is both cheaper and correct in both themes for free.
 */
export function FlowEdgeMarkers() {
  const heads: Array<{ id: string; color: string; opacity?: number }> = [
    { id: EDGE_MARKER.normal, color: "var(--border-bold)" },
    { id: EDGE_MARKER.selected, color: "var(--border-brand)" },
    { id: EDGE_MARKER.error, color: "var(--border-danger)" },
    { id: EDGE_MARKER.implicit, color: "var(--text-subtlest)", opacity: 0.5 },
  ];
  return (
    <svg className="pointer-events-none absolute h-0 w-0" aria-hidden>
      <defs>
        {heads.map((head) => (
          <marker
            key={head.id}
            id={head.id}
            viewBox="0 0 12 12"
            markerWidth={9}
            markerHeight={9}
            refX={10}
            refY={6}
            orient="auto-start-reverse"
            markerUnits="userSpaceOnUse"
          >
            <path d="M 1 1 L 10 6 L 1 11 z" fill={head.color} opacity={head.opacity} />
          </marker>
        ))}
      </defs>
    </svg>
  );
}

export function FlowConditionEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
}: EdgeProps) {
  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 12,
  });
  const d = data as unknown as ConditionEdgeData | undefined;
  const condition = d?.condition;
  const showLabel = useLabelsVisible();
  // Deterministic edges are evaluated by the runtime, never offered to the
  // model — drawn dashed so the two kinds are distinguishable at a glance. The
  // dash is a long one; the tool-performed ghosts below use a fine dot, because
  // two similar dashes read as the same thing on a busy canvas.
  const deterministic = condition && condition.type !== "prompt";
  const marker = d?.hasError
    ? EDGE_MARKER.error
    : selected
      ? EDGE_MARKER.selected
      : EDGE_MARKER.normal;

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={`url(#${marker})`}
        style={{
          strokeWidth: selected ? 2.4 : 1.6,
          strokeDasharray: deterministic ? "7 4" : undefined,
          // --danger is undefined project-wide; --border-danger is real.
          stroke: d?.hasError
            ? "var(--border-danger)"
            : selected
              ? "var(--border-brand)"
              : "var(--border-bold)",
        }}
      />
      {condition && showLabel && (
        <EdgeLabelRenderer>
          <div
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            }}
            className={cn(
              // Stays click-through: the label sits over the middle of the
              // edge, and BaseEdge's own invisible interaction path underneath
              // is what makes a 1.6px line clickable at all.
              "pointer-events-none absolute max-w-[13rem] truncate rounded-small border px-075 py-025 text-body-micro shadow-sm",
              d?.hasError
                ? "border-border-danger bg-background-danger text-text-danger"
                : selected
                  ? "border-border-brand bg-surface text-text-brand"
                  : "border-border bg-surface text-text-subtle",
            )}
            title={describeCondition(condition)}
          >
            {deterministic && (
              <span className="mr-050 text-text-subtlest">
                {condition.type === "always" ? "⇥" : "ƒ"}
              </span>
            )}
            {describeCondition(condition)}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

/**
 * A transition a built-in tool performs, which no author drew.
 *
 * This needs its own component rather than the `style` and `label` props xyflow
 * passes to an untyped edge: `flowEdgeTypes` maps `default` to
 * FlowConditionEdge, which renders BaseEdge with a style of its own and never
 * looks at `label`. So every ghost edge arrived on the canvas solid, opaque and
 * unlabelled — indistinguishable from the graph you own, and silent about which
 * tool performs the hop.
 */
export function FlowImplicitEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps) {
  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 12,
  });
  const tool = (data as { tool?: string } | undefined)?.tool;
  const showLabel = useLabelsVisible();

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={`url(#${EDGE_MARKER.implicit})`}
        style={{
          strokeWidth: 1.2,
          // A fine dot, not the "4 4" it used to share with the deterministic
          // dash above — at working zoom those two were the same picture.
          strokeDasharray: "1 4",
          strokeLinecap: "round",
          stroke: "var(--text-subtlest)",
          opacity: 0.6,
        }}
      />
      {tool && showLabel && (
        <EdgeLabelRenderer>
          <div
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            }}
            className="pointer-events-none absolute max-w-[11rem] truncate rounded-small border border-dashed border-border bg-surface px-050 py-025 font-mono text-body-micro text-text-subtlest"
            title={`${tool} moves the call here — performed by the tool, not authored in this graph`}
          >
            {tool}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export const flowEdgeTypes = {
  default: FlowConditionEdge,
  implicit: FlowImplicitEdge,
};
