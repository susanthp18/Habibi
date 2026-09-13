import { useCallback, useEffect, useState } from "react";
import {
  VALIDATOR_UNREACHABLE,
  isEmptyGraph,
  validateFlow,
  type FlowGraph,
  type FlowIssue,
  type FlowValidation,
} from "@/api/flow";

/**
 * The publish gate's view of the flow. Runs the same validator publish uses,
 * even when the Flow tab has never been opened, so a stored invalid graph
 * cannot ship by staying on the Prompt tab. While the canvas is mounted it
 * owns the result (it runs the same request), and reports through
 * `onValidation`.
 */
export function useFlowValidation(flow: FlowGraph | null, canvasMounted: boolean) {
  const [valid, setValid] = useState(true);
  const [issues, setIssues] = useState<FlowIssue[]>([]);

  useEffect(() => {
    if (isEmptyGraph(flow)) {
      setValid(true);
      setIssues([]);
      return;
    }
    if (canvasMounted) return;
    const timer = window.setTimeout(() => {
      void validateFlow(flow as FlowGraph)
        .then((result) => {
          setValid(result.ok);
          setIssues(result.issues);
        })
        .catch(() => {
          // An unchecked graph is not a publishable one, and the last verdict
          // does not describe this graph.
          setValid(false);
          setIssues([VALIDATOR_UNREACHABLE]);
        });
    }, 400);
    return () => window.clearTimeout(timer);
  }, [flow, canvasMounted]);

  // Stable, and a no-op when nothing actually changed: the canvas depends on
  // this identity to schedule the next validation, and a fresh callback per
  // render had the two feeding each other twice a second.
  const onValidation = useCallback((r: FlowValidation) => {
    setValid(r.ok);
    setIssues((prev) =>
      prev.length === r.issues.length &&
      prev.every((issue, i) => {
        const next = r.issues[i];
        return (
          issue.code === next.code &&
          issue.severity === next.severity &&
          issue.nodeId === next.nodeId &&
          issue.edgeId === next.edgeId &&
          issue.message === next.message
        );
      })
        ? prev
        : r.issues,
    );
  }, []);

  return {
    valid,
    issues,
    /** The validator did not answer: blocked, and said as such. */
    unchecked: issues.some((i) => i.code === "validator_unreachable"),
    errorCount: issues.filter((i) => i.severity === "error").length,
    onValidation,
  };
}
