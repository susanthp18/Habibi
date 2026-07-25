// Agent presence — GET/PATCH /me/presence → agent_presence table.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPatch, mockDelay, USE_MOCK } from "./config";

export type PresenceStatus = "available" | "on_break" | "wrap_up" | "offline";

export type AgentPresence = {
  status: PresenceStatus;
  sinceAt: string;
};

const STORAGE_KEY = "habibi.agentPresence";

function readMockPresence(): AgentPresence {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as AgentPresence;
      if (parsed?.status) return parsed;
    }
  } catch {
    /* ignore */
  }
  return { status: "available", sinceAt: new Date().toISOString() };
}

function writeMockPresence(p: AgentPresence) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
  } catch {
    /* ignore */
  }
}

export async function fetchPresence(): Promise<AgentPresence> {
  if (USE_MOCK) return mockDelay(readMockPresence());
  return apiGet<AgentPresence>("/me/presence");
}

export async function patchPresence(status: PresenceStatus): Promise<AgentPresence> {
  if (USE_MOCK) {
    const next = { status, sinceAt: new Date().toISOString() };
    writeMockPresence(next);
    return mockDelay(next);
  }
  return apiPatch<AgentPresence>("/me/presence", { status });
}

export function usePresence() {
  return useQuery({
    queryKey: ["me-presence"],
    queryFn: fetchPresence,
    staleTime: 30_000,
  });
}

export function usePatchPresence() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: patchPresence,
    onSuccess: (data) => {
      qc.setQueryData(["me-presence"], data);
    },
  });
}

/** UI toggle keys ↔ API status. */
export type AvailabilityUi = "available" | "break" | "wrap";

export function uiToPresence(ui: AvailabilityUi): PresenceStatus {
  if (ui === "break") return "on_break";
  if (ui === "wrap") return "wrap_up";
  return "available";
}

export function presenceToUi(status: PresenceStatus | undefined | null): AvailabilityUi {
  if (status === "on_break") return "break";
  if (status === "wrap_up") return "wrap";
  return "available";
}
