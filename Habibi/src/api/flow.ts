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
export const UNARY_OPERATORS: ReadonlySet<FlowOperator> = new Set([
  "exists",
  "not_exists",
]);

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
  /** False makes the bot listen first instead of speaking. */
  respondImmediately: boolean;
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
};

export function isEmptyGraph(graph: FlowGraph | null | undefined): boolean {
  return !graph || !graph.nodes || graph.nodes.length === 0;
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
    clauses:
      type === "expression"
        ? [{ variable: "", operator: "equals", value: "" }]
        : [],
  };
}

export function fetchFlowTools(): Promise<FlowTool[]> {
  return apiGet<FlowTool[]>("/flow/tools");
}

export function fetchReservedKeys(): Promise<Record<string, string>> {
  return apiGet<Record<string, string>>("/flow/reserved-keys");
}

export function validateFlow(graph: FlowGraph): Promise<FlowValidation> {
  return apiPost<FlowValidation>("/flow/validate", graph);
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
