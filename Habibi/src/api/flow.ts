// -----------------------------------------------------------------------------
// Authored conversation flow — the graph the voice runtime executes.
//
// Mirrors backend/flow_graph.py. The graph is stored on the prompt version
// (prompt_versions.flow), so it saves, publishes, diffs and rolls back through
// the machinery Prompt Studio already has — there is no separate flow lifecycle.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import { apiGet, apiPost } from "./config";

export type FlowInstructionType = "prompt" | "say";
export type FlowVariableType = "string" | "number" | "boolean";
export type FlowConditionType = "prompt" | "expression" | "always";
export type FlowMatch = "all" | "any";

export type FlowOperator =
  | "equals"
  | "not_equals"
  | "contains"
  | "not_contains"
  | "greater_than"
  | "greater_or_equal"
  | "less_than"
  | "less_or_equal"
  | "exists"
  | "not_exists";

/** Operators that ignore the right-hand side. Mirrors UNARY_OPERATORS. */
export const UNARY_OPERATORS: ReadonlySet<FlowOperator> = new Set(["exists", "not_exists"]);

export const OPERATOR_LABELS: Record<FlowOperator, string> = {
  equals: "is",
  not_equals: "is not",
  contains: "contains",
  not_contains: "does not contain",
  greater_than: ">",
  greater_or_equal: "≥",
  less_than: "<",
  less_or_equal: "≤",
  exists: "is set",
  not_exists: "is not set",
};

export type FlowVariable = {
  key: string;
  description: string;
  type: FlowVariableType;
};

export type FlowNodeData = {
  name: string;
  instructionType: FlowInstructionType;
  instructions: string;
  isStart: boolean;
  /**
   * Outbound missions that *begin* at this step. Mirrors
   * `flow_graph.FlowNodeData.entryFor`, which this type had simply omitted —
   * and an omitted field is not a neutral one here. The Outbound tab reads the
   * graph's entries back and renders "card says dpd_reminder · flow says
   * nothing" in red when they disagree, so the studio could state the problem
   * precisely and offer nowhere to fix it: `entryFor` is set on the node, and
   * the Flow tab is the only place a node is edited.
   *
   * Deliberately additive to `isStart` rather than a replacement. `isStart` is
   * where an *inbound* caller lands and a graph has exactly one; an outbound
   * mission is not the inbound script with a different greeting — we chose the
   * borrower, the moment and the reason, so asking them why they called is
   * absurd. Each mission therefore gets its own door into a shared spine.
   *
   * Optional because versions authored before this field exists have no such
   * key, and `??`-ing it to `[]` on read must not be mistaken for the author
   * having cleared it.
   */
  entryFor?: string[];
  /** False makes the bot listen first instead of speaking. */
  respondImmediately: boolean;
  /**
   * Fixed line spoken the moment this step is entered, before anything else.
   * This is what makes "listen first" safe on a step the caller is moved into
   * after answering: without it the line is simply silent until someone
   * speaks.
   */
  entryLine: string;
  /** Tool keys from /flow/tools. */
  tools: string[];
  extractVariables: FlowVariable[];
  endConversation: boolean;
};

export type FlowNode = {
  id: string;
  /**
   * Stable machine name the runtime transitions by. Separate from `data.name`
   * on purpose: deriving tool names from a display label means renaming a node
   * silently renames its transition, and two nodes sharing a label collide.
   */
  key: string;
  type: "conversation" | "end";
  position: { x: number; y: number };
  data: FlowNodeData;
};

export type FlowExpressionClause = {
  variable: string;
  operator: FlowOperator;
  value: string | null;
};

export type FlowCondition = {
  type: FlowConditionType;
  prompt: string;
  match: FlowMatch;
  clauses: FlowExpressionClause[];
};

export type FlowEdge = {
  id: string;
  source: string;
  target: string;
  data: { condition: FlowCondition };
};

export type FlowGraph = {
  version: number;
  globalTools: string[];
  nodes: FlowNode[];
  edges: FlowEdge[];
};

export type FlowIssue = {
  severity: "error" | "warning";
  code: string;
  message: string;
  nodeId: string | null;
  edgeId: string | null;
};

export type FlowValidation = { ok: boolean; issues: FlowIssue[] };

export type FlowTool = {
  key: string;
  description: string;
  /** Moves the conversation itself — see the warning in ToolPicker. */
  transitions: boolean;
  /** Locked policy engine — visible and disabled in the Tools tab. */
  locked?: boolean;
};

/**
 * True only for the built-in-script sentinel: no nodes AND no edges.
 *
 * Mirrors `flow_graph.is_unauthored`, and the "and no edges" half is the whole
 * point. This used to key on nodes alone, so a stored graph with edges and no
 * nodes — a corrupted row, not an unauthored card — was classified "empty"
 * everywhere it was asked about: the canvas skipped validation on it, the
 * studio forced `flowValid = true`, and the tab rendered "No authored flow"
 * over a graph whose validator, when finally run against it by hand, reported
 * `dangling_target` on every edge.
 *
 * A card that genuinely has no flow stores `{nodes: [], edges: []}`, and that
 * still answers true here. The two rows were indistinguishable to the old test
 * and are not to this one.
 */
export function isEmptyGraph(graph: FlowGraph | null | undefined): boolean {
  if (!graph) return true;
  return (graph.nodes?.length ?? 0) === 0 && (graph.edges?.length ?? 0) === 0;
}

/** Matches flow_graph.empty_graph() so a new draft starts identically. */
export function emptyGraph(): FlowGraph {
  return {
    version: 1,
    globalTools: ["search_knowledge_base", "escalate_to_human", "end_call"],
    nodes: [
      {
        id: "n-start",
        key: "greet",
        type: "conversation",
        position: { x: 0, y: 0 },
        data: {
          name: "Greeting",
          instructionType: "prompt",
          instructions:
            "Speak first — one short greeting that also says the call is recorded for quality and compliance.",
          isStart: true,
          respondImmediately: true,
          entryLine: "",
          tools: ["disclose_recording"],
          extractVariables: [],
          endConversation: false,
        },
      },
      {
        id: "n-end",
        key: "call_ended",
        type: "end",
        position: { x: 0, y: 240 },
        data: {
          name: "End call",
          instructionType: "prompt",
          instructions: "",
          isStart: false,
          respondImmediately: true,
          entryLine: "",
          tools: [],
          extractVariables: [],
          endConversation: true,
        },
      },
    ],
    edges: [
      {
        id: "e-start-end",
        source: "n-start",
        target: "n-end",
        data: {
          condition: {
            type: "prompt",
            prompt: "The conversation is complete",
            match: "all",
            clauses: [],
          },
        },
      },
    ],
  };
}

export function newNodeData(name: string): FlowNodeData {
  return {
    name,
    instructionType: "prompt",
    instructions: "",
    isStart: false,
    respondImmediately: true,
    entryLine: "",
    tools: [],
    extractVariables: [],
    endConversation: false,
  };
}

export function defaultCondition(type: FlowConditionType): FlowCondition {
  return {
    type,
    prompt: type === "prompt" ? "Describe when this transition fires" : "",
    match: "all",
    clauses: type === "expression" ? [{ variable: "", operator: "equals", value: "" }] : [],
  };
}

export function fetchFlowTools(): Promise<FlowTool[]> {
  return apiGet<FlowTool[]>("/flow/tools");
}

export function fetchReservedKeys(): Promise<Record<string, string>> {
  return apiGet<Record<string, string>>("/flow/reserved-keys");
}

/**
 * The built-in collections script as an authored graph. Derived server-side
 * from the Python the runtime actually executes, so starting from it is not a
 * template — it is what the agent does today.
 */
export function fetchBuiltInFlow(): Promise<FlowGraph> {
  return apiGet<FlowGraph>("/flow/built-in");
}

export function validateFlow(graph: FlowGraph): Promise<FlowValidation> {
  return apiPost<FlowValidation>("/flow/validate", graph);
}

/**
 * tool key -> node keys that tool transitions to.
 *
 * The built-in tools move the conversation by node key, so a graph using
 * reserved keys has real transitions and no authored edges. The canvas draws
 * these as ghost edges rather than inventing edges the runtime would ignore.
 */
export function fetchFlowTransitions(): Promise<Record<string, string[]>> {
  return apiGet<Record<string, string[]>>("/flow/transitions");
}

export function useFlowTransitions() {
  return useQuery({
    queryKey: ["flow-transitions"],
    queryFn: fetchFlowTransitions,
    // Derived from source at import time; only changes on deploy.
    staleTime: 5 * 60_000,
  });
}

export function useFlowTools() {
  return useQuery({
    queryKey: ["flow-tools"],
    queryFn: fetchFlowTools,
    // The registry only changes on deploy.
    staleTime: 5 * 60_000,
  });
}

export function useReservedKeys() {
  return useQuery({
    queryKey: ["flow-reserved-keys"],
    queryFn: fetchReservedKeys,
    staleTime: 5 * 60_000,
  });
}
