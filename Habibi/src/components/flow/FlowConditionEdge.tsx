import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  type EdgeProps,
} from "@xyflow/react";

import {
  OPERATOR_LABELS,
  UNARY_OPERATORS,
  type FlowCondition,
} from "@/api/flow";
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
  });
  const d = data as unknown as ConditionEdgeData | undefined;
  const condition = d?.condition;
  const showLabel = useLabelsVisible();
  // Deterministic edges are evaluated by the runtime, never offered to the
  // model — drawn dashed so the two kinds are distinguishable at a glance.
  const deterministic = condition && condition.type !== "prompt";

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        style={{
          strokeWidth: selected ? 2 : 1.4,
          strokeDasharray: deterministic ? "5 4" : undefined,
          // --danger is undefined project-wide; --border-danger is real.
          stroke: d?.hasError
            ? "var(--border-danger)"
            : selected
              ? "var(--border-brand)"
              : undefined,
        }}
      />
      {condition && showLabel && (
        <EdgeLabelRenderer>
          <div
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            }}
            className={cn(
              "pointer-events-none absolute max-w-[13rem] truncate rounded-small border bg-surface px-075 py-025 text-[0.65rem]",
              d?.hasError
                ? "border-border-danger text-text-danger"
                : "border-border text-text-subtle",
            )}
          >
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
  });
  const tool = (data as { tool?: string } | undefined)?.tool;
  const showLabel = useLabelsVisible();

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        style={{
          strokeWidth: 1.2,
          strokeDasharray: "4 4",
          stroke: "var(--text-subtlest)",
          opacity: 0.5,
        }}
      />
      {tool && showLabel && (
        <EdgeLabelRenderer>
          <div
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            }}
            className="pointer-events-none absolute max-w-[11rem] truncate rounded-small border border-dashed border-border bg-surface px-050 py-025 font-mono text-[0.6rem] text-text-subtlest"
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
