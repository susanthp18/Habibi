// Floor Command Center — exception + workforce snapshot.
// Mock: seed data. Live: GET /floor; supervisor actions POST /supervisor-actions.

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { ActiveCall, FloorAgent, FloorAlert } from "@/api/types/floor";
import { apiGet, apiPost } from "./config";

export type FloorStats = {
  callsInProgress: number;
  avgSentiment: number;
  criticalAlerts: number;
  queueDepth: number;
  agentsAvailable: number;
  agentsOnCall: number;
  botAtRisk: number;
  longestWaitSec: number;
};

export type FloorSnapshot = {
  calls: ActiveCall[];
  alerts: FloorAlert[];
  stats: FloorStats;
  agents: FloorAgent[];
};

export const FLOOR_LIVE_HINT =
  "Live floor · Listen plays the call with its live transcript. Whisper instructs the agent from its next reply. Take over puts you on the call; hand it back when you are done.";

export type SupervisorAction = "listen_in" | "whisper" | "barge" | "force_handoff";

function hydrateCall(c: ActiveCall): ActiveCall {
  return {
    ...c,
    flags: c.flags ?? [],
    pendingHandoff: Boolean(c.pendingHandoff),
    outstanding: c.outstanding ?? 0,
    customerRisk: c.customerRisk ?? c.risk,
    dnd: Boolean(c.dnd),
    recentTurns: c.recentTurns ?? [],
    recommendedAction: c.recommendedAction ?? "listen",
    offerPolicy: c.offerPolicy ?? null,
    authorityPolicy: c.authorityPolicy ?? null,
    liveQa: c.liveQa ?? null,
  };
}

export async function fetchFloor(): Promise<FloorSnapshot> {
  const raw = await apiGet<FloorSnapshot>("/floor");
  return {
    calls: (raw.calls ?? []).map(hydrateCall),
    alerts: (raw.alerts ?? []).map((a) => ({
      ...a,
      recommendedAction: a.recommendedAction ?? "listen",
    })),
    stats: raw.stats,
    agents: raw.agents ?? [],
  };
}

export function useFloor(refetchIntervalMs = 3_000) {
  return useQuery({
    queryKey: ["floor"],
    queryFn: fetchFloor,
    refetchInterval: refetchIntervalMs,
    staleTime: 2_000,
  });
}

function tickMockCalls(prev: ActiveCall[]): ActiveCall[] {
  return prev.map((c) => {
    const baseDrift = c.handler.kind === "bot" ? 0 : c.sentiment < 0 ? -0.01 : 0.005;
    const noise = (Math.random() - 0.5) * 0.03;
    const next = Math.max(-1, Math.min(1, c.sentiment + baseDrift + noise));
    return {
      ...c,
      durationSec: c.durationSec + 1,
      sentiment: next,
      sentimentTrend: next - c.sentiment,
    };
  });
}

/**
 * Floor board state: live mirrors GET /floor; mock ticks a local simulation
 * and does not resync from the query (the seed snapshot is static).
 */
export function useFloorBoard(initial: FloorSnapshot) {
  const { data, isError, error } = useFloor();
  const snapshot = data ?? initial;
  const [calls, setCalls] = useState<ActiveCall[]>(snapshot.calls);
  const [alerts, setAlerts] = useState<FloorAlert[]>(snapshot.alerts);

  useEffect(() => {
    setCalls(snapshot.calls);
    setAlerts(snapshot.alerts);
  }, [snapshot.calls, snapshot.alerts]);

  useEffect(() => {
    return;
    const iv = window.setInterval(() => setCalls(tickMockCalls), 1000);
    return () => window.clearInterval(iv);
  }, []);

  const applyMockBarge = (id: string) => {
    return;
    setCalls((prev) =>
      prev.map((c) =>
        c.id === id
          ? {
              ...c,
              handler: { kind: "human", name: "You (supervisor)", initials: "SU" },
              lastLine: "[system] Supervisor took over the call.",
              pendingHandoff: false,
            }
          : c,
      ),
    );
  };

  const applyMockAck = (alertId: string) => {
    return;
    setAlerts((prev) => prev.filter((a) => a.id !== alertId));
  };

  return {
    snapshot,
    calls,
    alerts,
    isError,
    error,
    liveHint: FLOOR_LIVE_HINT,
    applyMockBarge,
    applyMockAck,
  };
}

export async function postSupervisorAction(
  interactionId: string,
  action: SupervisorAction,
  note?: string,
): Promise<{ audioJoined?: boolean } | void> {
  return apiPost("/supervisor-actions", { interactionId, action, note });
}

export async function ackFloorAlert(alertId: string): Promise<void> {
  await apiPost(`/floor/alerts/${alertId}/ack`, {});
}

export function useSupervisorAction() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: (input: { interactionId: string; action: SupervisorAction; note?: string }) =>
      postSupervisorAction(input.interactionId, input.action, input.note),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["floor"] });
    },
  });
}

export function useAckFloorAlert(alsoInvalidate: readonly (readonly unknown[])[] = []) {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (alertId: string) => ackFloorAlert(alertId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["floor"] });
      for (const key of alsoInvalidate) void qc.invalidateQueries({ queryKey: [...key] });
    },
  });
}

/** The wire's WorkRuntimeJobResponse: the optional fields are optional here too. */
export type FloorApproval = {
  id: string;
  workflowType: string;
  status: string;
  customerId?: string | null;
  inputRequiredReason?: string | null;
  payload?: { action?: string; triggerRef?: string };
};

export type FloorCopilot = {
  interactionId: string;
  customerId: string | null;
  whisperDraft: string;
  engineDraft: string;
  vetoes: string[];
  engines: {
    authority?: { status?: string; talkTrack?: string | null; reasonLabel?: string | null };
    treatment?: { action?: string | null; rationale?: string | null; enactedBy?: string | null };
    liveQa?: { recommendedAction?: string | null };
  };
  card?: { botId?: string | null; displayName?: string | null; skills?: string[] };
  approvals?: FloorApproval[];
  streaming?: boolean;
};

export async function fetchFloorCopilot(interactionId: string): Promise<FloorCopilot | null> {
  return apiGet<FloorCopilot>(`/floor/copilot/${interactionId}`);
}

export function useFloorCopilot(interactionId: string | null) {
  return useQuery({
    queryKey: ["floor-copilot", interactionId],
    queryFn: () => fetchFloorCopilot(interactionId!),
    enabled: Boolean(interactionId),
    staleTime: 8_000,
  });
}

export async function fetchFloorApprovals(): Promise<FloorApproval[]> {
  return apiGet<FloorApproval[]>("/floor/approvals");
}

export function useFloorApprovals() {
  return useQuery({
    queryKey: ["floor-approvals"],
    queryFn: fetchFloorApprovals,
    refetchInterval: 5_000,
  });
}

export async function signalFloorApproval(
  jobId: string,
  name: "approve" | "reject",
): Promise<FloorApproval> {
  return apiPost<FloorApproval>(`/floor/approvals/${jobId}/signal`, { name });
}
