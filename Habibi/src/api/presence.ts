// Agent presence — GET/PATCH /me/presence → agent_presence table.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPatch } from "./config";

export type PresenceStatus = "available" | "on_break" | "wrap_up" | "offline";

export type AgentPresence = {
  status: PresenceStatus;
  sinceAt: string;
};

export async function fetchPresence(): Promise<AgentPresence> {
  return apiGet<AgentPresence>("/me/presence");
}

export async function patchPresence(status: PresenceStatus): Promise<AgentPresence> {
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
    meta: { errors: "caller" },
    mutationFn: patchPresence,
    onSuccess: (data) => {
      qc.setQueryData(["me-presence"], data);
    },
  });
}

/** UI toggle keys ↔ API status. */
export type AvailabilityUi = "available" | "break" | "wrap" | "offline";

export function uiToPresence(ui: AvailabilityUi): PresenceStatus {
  if (ui === "break") return "on_break";
  if (ui === "wrap") return "wrap_up";
  if (ui === "offline") return "offline";
  return "available";
}

export function presenceToUi(status: PresenceStatus | undefined | null): AvailabilityUi {
  if (status === "on_break") return "break";
  if (status === "wrap_up") return "wrap";
  if (status === "offline") return "offline";
  return "available";
}
