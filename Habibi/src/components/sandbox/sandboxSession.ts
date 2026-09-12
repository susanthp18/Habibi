/**
 * One rehearsal's state: the transcript, where the script is, the run on the
 * server, whether a guardrail halted it, the step the authored graph is on,
 * and what the tools did.
 *
 * Six call sites used to reset overlapping subsets of seven `useState`s --
 * switching card, version, scenario or KB each forgot a different one -- so a
 * flow cursor or a tool log outlived the run it belonged to. Every transition
 * is a named action here, and `start` is the one way a session begins.
 */
import type { LiveToolCall } from "@/components/sandbox/voice/liveEvents";
import type { TurnMetric } from "@/components/sandbox/inspector/MetricsTab";
import type { SandboxRun } from "@/api/sandbox";
import type { SandboxTurn } from "@/api/types/sandbox";

export interface SandboxSession {
  turns: SandboxTurn[];
  /** Index of the next scripted customer line. */
  scriptIndex: number;
  run: SandboxRun | null;
  halted: boolean;
  /** The step the server walked to; posted back so the next turn continues there. */
  flowNode: string | null;
  textToolCalls: LiveToolCall[];
  liveMetrics: TurnMetric[];
}

export const EMPTY_SESSION: SandboxSession = {
  turns: [],
  scriptIndex: 0,
  run: null,
  halted: false,
  flowNode: null,
  textToolCalls: [],
  liveMetrics: [],
};

type Updater<T> = T | ((prev: T) => T);

export type SandboxSessionAction =
  /** A fresh rehearsal on this opening; the live metrics survive unless asked to go. */
  | { type: "start"; turns: SandboxTurn[]; clearMetrics?: boolean }
  /** The card, version or KB changed: the run no longer applies. */
  | { type: "invalidateRun"; clearTools?: boolean }
  | { type: "run"; run: SandboxRun | null }
  /** The server supplied its own opening line for the run just created. */
  | { type: "opening"; turns: SandboxTurn[] }
  | {
      type: "exchange";
      turns: SandboxTurn[];
      toolCalls: LiveToolCall[];
      nodeKey: string | null | undefined;
      halted: boolean;
      fromScript: boolean;
    }
  | { type: "turns"; value: Updater<SandboxTurn[]> }
  | { type: "metrics"; value: Updater<TurnMetric[]> }
  /** The flow cursor belongs to the graph it was walked in. */
  | { type: "clearFlowNode" };

function resolve<T>(value: Updater<T>, prev: T): T {
  return typeof value === "function" ? (value as (p: T) => T)(prev) : value;
}

export function sandboxSessionReducer(
  state: SandboxSession,
  action: SandboxSessionAction,
): SandboxSession {
  switch (action.type) {
    case "start":
      return {
        ...EMPTY_SESSION,
        turns: action.turns,
        liveMetrics: action.clearMetrics ? [] : state.liveMetrics,
      };
    case "invalidateRun":
      return { ...state, run: null, textToolCalls: action.clearTools ? [] : state.textToolCalls };
    case "run":
      return { ...state, run: action.run };
    case "opening":
      return { ...state, turns: action.turns };
    case "exchange":
      return {
        ...state,
        turns: [...state.turns, ...action.turns],
        textToolCalls: action.toolCalls.length
          ? [...state.textToolCalls, ...action.toolCalls]
          : state.textToolCalls,
        // null when the card authors no flow: the cursor stays where it was
        flowNode: action.nodeKey ?? state.flowNode,
        halted: state.halted || action.halted,
        run: action.halted && state.run ? { ...state.run, status: "completed" } : state.run,
        scriptIndex: action.fromScript ? state.scriptIndex + 1 : state.scriptIndex,
      };
    case "turns":
      return { ...state, turns: resolve(action.value, state.turns) };
    case "metrics":
      return { ...state, liveMetrics: resolve(action.value, state.liveMetrics) };
    case "clearFlowNode":
      return { ...state, flowNode: null };
  }
}
