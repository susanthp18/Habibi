// -----------------------------------------------------------------------------
// Per-turn trace — tool calls, retrievals and latency for one interaction.
//
// Backs the Inspector's Trace tab. Every other Inspector tab reads ephemeral
// RTVI events that vanish when the pane closes; this is the first one backed by
// server state, so a call can be examined after it ends.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import { apiGet, USE_MOCK } from "./config";

export type TraceToolCall = {
  tool: string;
  ok: boolean;
  error: string | null;
  latencyMs: number | null;
  channel: string | null;
  args: Record<string, unknown> | null;
  resultPreview: string | null;
  at: string | null;
  /** Null until Agent Cards / skills / connectors write these (Phase 1+). */
  agentId?: string | null;
  skillId?: string | null;
  connectorId?: string | null;
};

export type TraceRetrieval = {
  query: string;
  hits: number;
  topScore: number | null;
  latencyMs: number | null;
  source: string | null;
  at: string | null;
};

export type TraceLatency = {
  ttfbMs?: number | null;
  ttfaMs?: number | null;
  tokens?: number | null;
  sttTtfbMs?: number | null;
  llmTtfbMs?: number | null;
  ttsTtfbMs?: number | null;
  userTurnMs?: number | null;
  toolMs?: number | null;
  aggregationMs?: number | null;
};

export type TraceTurn = {
  /** null on the synthetic entry holding events that could not be attributed. */
  turnId: string | null;
  turnIndex: number | null;
  speaker: string;
  atSec: number | null;
  text: string | null;
  intent: string | null;
  intentScore: number | null;
  sentimentDelta: number | null;
  latency: TraceLatency;
  toolCalls: TraceToolCall[];
  retrievals: TraceRetrieval[];
};

export function fetchTurnTrace(interactionId: string): Promise<TraceTurn[]> {
  return apiGet<TraceTurn[]>(`/interactions/${encodeURIComponent(interactionId)}/trace`);
}

/**
 * Disabled without an interaction id, and in mock mode — there is no seeded
 * trace to serve, and the tab falls back to its client-derived view.
 */
export function useTurnTrace(interactionId: string | null | undefined) {
  return useQuery({
    queryKey: ["turn-trace", interactionId],
    queryFn: () => fetchTurnTrace(interactionId as string),
    enabled: Boolean(interactionId) && !USE_MOCK,
    staleTime: 5_000,
  });
}
