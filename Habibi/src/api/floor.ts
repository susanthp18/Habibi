// Floor Command Center — exception + workforce snapshot.
// Mock: seed data. Live: GET /floor; supervisor actions POST /supervisor-actions.

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  activeCalls as seedCalls,
  baselineStats,
  initialAlerts,
  seedAgents,
  type ActiveCall,
  type FloorAgent,
  type FloorAlert,
} from "@/data/floor-seed";
import { apiEventStream, apiGet, apiPost, mockDelay, USE_MOCK } from "./config";

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
  if (USE_MOCK) {
    return mockDelay({
      calls: seedCalls,
      alerts: initialAlerts,
      stats: baselineStats,
      agents: seedAgents,
    });
  }
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
    refetchInterval: USE_MOCK ? false : refetchIntervalMs,
    staleTime: USE_MOCK ? Infinity : 2_000,
  });
}

export async function postSupervisorAction(
  interactionId: string,
  action: SupervisorAction,
  note?: string,
): Promise<{ audioJoined?: boolean } | void> {
  if (USE_MOCK) {
    await mockDelay(undefined);
    return { audioJoined: false };
  }
  return apiPost("/supervisor-actions", { interactionId, action, note });
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

export function useAckFloorAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (alertId: string) => ackFloorAlert(alertId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["floor"] });
    },
  });
}

export type FloorApproval = {
  id: string;
  workflowType: string;
  status: string;
  customerId: string | null;
  inputRequiredReason: string | null;
  payload: { action?: string; triggerRef?: string };
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
  if (USE_MOCK) {
    return mockDelay({
      interactionId,
      customerId: null,
      whisperDraft: "Stay with the current script. No engine veto is in force.",
      engineDraft: "Stay with the current script. No engine veto is in force.",
      vetoes: [],
      engines: {},
    });
  }
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

export type CopilotStreamState = {
  whisper: string;
  engineDraft: string;
  vetoes: string[];
  card: FloorCopilot["card"];
  approvals: FloorApproval[];
  streaming: boolean;
  done: boolean;
  error: string | null;
};

const EMPTY_STREAM: CopilotStreamState = {
  whisper: "",
  engineDraft: "",
  vetoes: [],
  card: undefined,
  approvals: [],
  streaming: false,
  done: false,
  error: null,
};

export function useCopilotStream(interactionId: string | null) {
  const [state, setState] = useState<CopilotStreamState>(EMPTY_STREAM);

  useEffect(() => {
    if (!interactionId) {
      setState(EMPTY_STREAM);
      return;
    }
    const ac = new AbortController();
    setState({ ...EMPTY_STREAM, streaming: true });

    if (USE_MOCK) {
      const seed =
        "Stay with the current script. No engine veto is in force.";
      const words = seed.match(/\S+\s*/g) ?? [seed];
      let i = 0;
      const tick = window.setInterval(() => {
        i += 1;
        setState({
          whisper: words.slice(0, i).join(""),
          engineDraft: seed,
          vetoes: [],
          card: undefined,
          approvals: [],
          streaming: i < words.length,
          done: i >= words.length,
          error: null,
        });
        if (i >= words.length) window.clearInterval(tick);
      }, 40);
      return () => {
        ac.abort();
        window.clearInterval(tick);
      };
    }

    void apiEventStream(
      `/floor/copilot/${interactionId}/stream`,
      (event, data) => {
        const payload = (data ?? {}) as Record<string, unknown>;
        if (event === "pack") {
          const pack = payload as unknown as FloorCopilot;
          setState({
            whisper: "",
            engineDraft: pack.engineDraft || "",
            vetoes: pack.vetoes ?? [],
            card: pack.card,
            approvals: pack.approvals ?? [],
            streaming: true,
            done: false,
            error: null,
          });
          return;
        }
        if (event === "token") {
          const chunk = String(payload.text ?? "");
          setState((prev) => ({
            ...prev,
            whisper: prev.whisper + chunk,
            streaming: true,
          }));
          return;
        }
        if (event === "done") {
          setState((prev) => ({
            ...prev,
            whisper: String(payload.whisperDraft ?? prev.whisper),
            engineDraft: String(payload.engineDraft ?? prev.engineDraft),
            vetoes: Array.isArray(payload.vetoes) ? (payload.vetoes as string[]) : prev.vetoes,
            streaming: false,
            done: true,
          }));
        }
      },
      { signal: ac.signal },
    ).catch((err: unknown) => {
      if (ac.signal.aborted) return;
      setState((prev) => ({
        ...prev,
        streaming: false,
        error: err instanceof Error ? err.message : "Copilot stream failed",
      }));
    });

    return () => ac.abort();
  }, [interactionId]);

  return state;
}

export async function fetchFloorApprovals(): Promise<FloorApproval[]> {
  if (USE_MOCK) return mockDelay([]);
  return apiGet<FloorApproval[]>("/floor/approvals");
}

export function useFloorApprovals() {
  return useQuery({
    queryKey: ["floor-approvals"],
    queryFn: fetchFloorApprovals,
    refetchInterval: USE_MOCK ? false : 5_000,
  });
}

export async function signalFloorApproval(jobId: string, name: "approve" | "reject"): Promise<FloorApproval> {
  return apiPost<FloorApproval>(`/floor/approvals/${jobId}/signal`, { name });
}
