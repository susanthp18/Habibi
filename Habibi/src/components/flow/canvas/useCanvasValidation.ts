import { useEffect, useMemo, useRef, useState } from "react";
import {
  VALIDATOR_UNREACHABLE,
  isEmptyGraph,
  validateFlow,
  type FlowGraph,
  type FlowIssue,
  type FlowValidation,
} from "@/api/flow";

/**
 * Server-side validation of the graph on screen, debounced. The same
 * validator gates publish, so the canvas can never show "fine" for something
 * the backend will reject. What comes back is indexed by node and by edge for
 * the cards and the inspector, and summarised for the pill.
 */
export function useCanvasValidation(
  graph: FlowGraph,
  onValidation: ((result: FlowValidation) => void) | undefined,
) {
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
          // On the canvas too, not only in the header: the last verdict's
          // issues stayed painted beside a graph nobody had checked.
          setIssues([VALIDATOR_UNREACHABLE]);
          onValidationRef.current?.({ ok: false, issues: [VALIDATOR_UNREACHABLE] });
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

  const errorCount = issues.filter((i) => i.severity === "error").length;
  const warningCount = issues.length - errorCount;
  // `issues` describes `validatedGraph`, which is only `graph` once a response
  // for this exact object has landed.
  const stale = validatedGraph !== graph;
  const neverChecked = validatedGraph === null;

  return {
    issues,
    issuesByNode,
    issuesByEdge,
    errorCount,
    warningCount,
    stale,
    neverChecked,
  };
}
