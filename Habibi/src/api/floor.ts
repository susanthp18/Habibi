// Floor Command Center — live grid of active interactions + alerts.
// Mock: seed data. Live: GET /floor; supervisor actions POST /supervisor-actions.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  activeCalls as seedCalls,
  baselineStats,
  initialAlerts,
  type ActiveCall,
  type FloorAlert,
} from "@/data/floor-seed";
import { apiGet, apiPost, mockDelay, USE_MOCK } from "./config";

export type FloorStats = {
  callsInProgress: number;
  avgSentiment: number;
  escalationRate: number;
  queueDepth: number;
  botContainment: number;
  longestWaitSec: number;
};

export type FloorSnapshot = {
  calls: ActiveCall[];
  alerts: FloorAlert[];
  stats: FloorStats;
};

export type SupervisorAction = "listen_in" | "whisper" | "barge" | "force_handoff";

export async function fetchFloor(): Promise<FloorSnapshot> {
  if (USE_MOCK) {
    return mockDelay({
      calls: seedCalls,
      alerts: initialAlerts,
      stats: baselineStats,
    });
  }
  return apiGet<FloorSnapshot>("/floor");
}

export function useFloor(refetchIntervalMs = 3_000) {
  return useQuery({
    queryKey: ["floor"],
    queryFn: fetchFloor,
    refetchInterval: USE_MOCK ? false : refetchIntervalMs,
    staleTime: USE_MOCK ? Infinity : 2_000,
  });
}

export async function postSupervisorAction(
  interactionId: string,
  action: SupervisorAction,
  note?: string,
): Promise<void> {
  if (USE_MOCK) {
    await mockDelay(undefined);
    return;
  }
  await apiPost("/supervisor-actions", { interactionId, action, note });
}

export async function ackFloorAlert(alertId: string): Promise<void> {
  if (USE_MOCK) {
    await mockDelay(undefined);
    return;
  }
  await apiPost(`/floor/alerts/${alertId}/ack`, {});
}

export function useSupervisorAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { interactionId: string; action: SupervisorAction; note?: string }) =>
      postSupervisorAction(input.interactionId, input.action, input.note),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["floor"] });
    },
  });
}
