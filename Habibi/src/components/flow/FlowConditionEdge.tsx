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
      {condition && (
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

export const flowEdgeTypes = { default: FlowConditionEdge };
