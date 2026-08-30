// -----------------------------------------------------------------------------
// Handoff Hub — assigned-session cockpit.
//   GET  /handoff/queue                  pending team claims
//   GET  /handoff/active                 my accepted live session (204 if none)
//   GET  /handoff/{interactionId}        full snapshot
//   POST /handoff/{id}/claim
//   POST /handoff/{id}/disclosures
//   POST /handoff/{id}/suggestions/{sid}/accept
//   POST /interactions/{id}/wrap-up
//
// Mock: scripted seed replay. Live: Postgres snapshot + 2s poll while active.
// -----------------------------------------------------------------------------

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  activeCall as seedCall,
  complianceItems as seedCompliance,
  customerContext as seedContext,
  dispositions as seedDispositions,
  suggestions as seedSuggestions,
  transcriptScript as seedTranscript,
  type ComplianceItem as SeedComplianceItem,
  type Suggestion,
  type TranscriptTurn,
} from "@/data/handoff-seed";
import { apiGet, apiPost, mockDelay, USE_MOCK } from "./config";
import type { OfferPolicy } from "@/lib/offer-policy";
import type { AuthorityPolicy } from "@/lib/authority-policy";

export type Speaker = "customer" | "agent" | "bot" | "system";

export type ActiveCall = {
  interactionId: string;
  handoffId: string;
  customerId: string;
  conversationId?: string | null;
  customerName: string;
  accountId: string;
  phone: string;
  channel: string;
  agentName: string;
  transferredFrom: string;
  escalationReason: string;
  startedAt: number;
  status: "pending_claim" | "active" | "completed";
  claimed: boolean;
  risk: string;
  handlerUserId?: string | null;
};

export type CustomerContext = {
  risk: string;
  outstanding: number;
  currency: string;
  lastPromise: { amount: number; date: string; status: string } | null;
  nextEmi: { amount: number; dueDate: string; daysOverdue: number } | null;
  openDisputes: number;
  dnd: { allowed: boolean; window: string; channels: string[] };
  tenureMonths: number;
  product: string;
  offerPolicy?: OfferPolicy | null;
  authorityPolicy?: AuthorityPolicy | null;
  liveQa?: {
    status?: string;
    reason?: string | null;
    recommendedAction?: string;
    audioCapable?: boolean;
  } | null;
};

export type ComplianceItem = SeedComplianceItem & {
  checked?: boolean;
  locked?: boolean;
  ruleId?: string | null;
};

export type HandoffAlert = {
  id: string;
  kind: string;
  severity: string;
  reason?: string | null;
};

export type HandoffSession = {
  interactionId: string;
  handoffId: string;
  customerId: string;
  conversationId?: string | null;
  status: "pending_claim" | "active" | "completed";
  claimed: boolean;
  monitor?: boolean;
  activeCall: ActiveCall;
  customerContext: CustomerContext;
  transcriptScript: TranscriptTurn[];
  sentimentSeries: number[];
  suggestions: Suggestion[];
  complianceItems: ComplianceItem[];
  alerts: HandoffAlert[];
  dispositions: string[];
  speakers: Record<string, string>;
};

export type HandoffQueueItem = {
  interactionId: string;
  handoffId: string;
  customerId: string;
  customerName: string;
  accountId: string;
  reason: string;
  queue: string | null;
  risk: string;
  waitSec: number;
  requestedAt: string | null;
};

export type HandoffQueue = {
  items: HandoffQueueItem[];
  activeInteractionId: string | null;
};

const MOCK_SESSION: HandoffSession = {
  interactionId: "mock-handoff",
  handoffId: "mock-ho",
  customerId: "mock-cust",
  conversationId: null,
  status: "active",
  claimed: true,
  activeCall: {
    ...seedCall,
    interactionId: "mock-handoff",
    handoffId: "mock-ho",
    customerId: "mock-cust",
    status: "active",
    claimed: true,
    risk: "high",
  },
  customerContext: {
    ...seedContext,
    lastPromise: seedContext.lastPromise,
    nextEmi: seedContext.nextEmi,
  },
  transcriptScript: seedTranscript,
  sentimentSeries: [],
  suggestions: seedSuggestions,
  complianceItems: seedCompliance.map((c) => ({ ...c, checked: false, locked: false })),
  alerts: [],
  dispositions: seedDispositions,
  speakers: {
    customer: seedCall.customerName,
    agent: "You",
    bot: "Bot · BigBound",
    system: "System",
  },
};

export async function fetchHandoffQueue(customerId?: string): Promise<HandoffQueue> {
  if (USE_MOCK) {
    return mockDelay({ items: [], activeInteractionId: "mock-handoff" });
  }
  const q = customerId ? `?customerId=${encodeURIComponent(customerId)}` : "";
  return apiGet<HandoffQueue>(`/handoff/queue${q}`);
}

export function useHandoffQueue(customerId?: string) {
  return useQuery({
    queryKey: ["handoff", "queue", customerId ?? ""],
    queryFn: () => fetchHandoffQueue(customerId),
    staleTime: USE_MOCK ? Infinity : 2_000,
    refetchInterval: USE_MOCK ? false : 5_000,
  });
}

export async function fetchHandoffActive(): Promise<HandoffSession | null> {
  if (USE_MOCK) return mockDelay(MOCK_SESSION);
  const session = await apiGet<HandoffSession | undefined>("/handoff/active");
  return session ?? null;
}

export async function fetchHandoffSession(interactionId: string): Promise<HandoffSession> {
  if (USE_MOCK) return mockDelay(MOCK_SESSION);
  return apiGet<HandoffSession>(`/handoff/${encodeURIComponent(interactionId)}`);
}

export function useHandoffActive() {
  return useQuery({
    queryKey: ["handoff", "active"],
    queryFn: fetchHandoffActive,
    staleTime: USE_MOCK ? Infinity : 2_000,
    refetchInterval: USE_MOCK ? false : 5_000,
  });
}

export function useHandoffSession(interactionId: string | undefined, opts?: { poll?: boolean }) {
  const poll = Boolean(opts?.poll) && !USE_MOCK;
  return useQuery({
    queryKey: ["handoff", "session", interactionId ?? ""],
    queryFn: () => fetchHandoffSession(interactionId!),
    enabled: Boolean(interactionId),
    staleTime: USE_MOCK ? Infinity : 1_000,
    refetchInterval: (q) => {
      if (!poll) return false;
      const s = q.state.data;
      if (!s || !s.claimed || s.status !== "active") return false;
      return 2_000;
    },
  });
}

export async function claimHandoff(interactionId: string): Promise<HandoffSession> {
  if (USE_MOCK) return mockDelay({ ...MOCK_SESSION, claimed: true, status: "active" });
  return apiPost<HandoffSession>(`/handoff/${encodeURIComponent(interactionId)}/claim`, {});
}

export function useClaimHandoff() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: claimHandoff,
    onSuccess: (session) => {
      qc.setQueryData(["handoff", "session", session.interactionId], session);
      void qc.invalidateQueries({ queryKey: ["handoff", "queue"] });
      void qc.invalidateQueries({ queryKey: ["handoff", "active"] });
    },
  });
}

export async function postHandoffDisclosure(
  interactionId: string,
  payload: { itemId: string; ruleId?: string | null; label?: string; read?: boolean },
): Promise<HandoffSession> {
  if (USE_MOCK) return mockDelay(MOCK_SESSION);
  return apiPost<HandoffSession>(
    `/handoff/${encodeURIComponent(interactionId)}/disclosures`,
    payload,
  );
}

export async function acceptHandoffSuggestion(
  interactionId: string,
  suggestionId: string,
): Promise<HandoffSession> {
  if (USE_MOCK) return mockDelay(MOCK_SESSION);
  return apiPost<HandoffSession>(
    `/handoff/${encodeURIComponent(interactionId)}/suggestions/${encodeURIComponent(suggestionId)}/accept`,
    {},
  );
}

export type WrapUpPayload = {
  disposition: string;
  notes: string;
  ptp: boolean;
  ptpAmount?: number;
  ptpDate?: string;
};

export async function wrapUpHandoff(
  interactionId: string,
  customerId: string,
  payload: WrapUpPayload,
): Promise<unknown> {
  if (USE_MOCK) return mockDelay({ id: interactionId, spawned: {} });
  const body: Record<string, unknown> = {
    disposition: payload.disposition,
    notes: payload.notes || null,
  };
  if (payload.ptp && payload.ptpAmount && payload.ptpDate) {
    body.promise = {
      customerId,
      interactionId,
      amount: payload.ptpAmount,
      promisedDate: payload.ptpDate,
      channel: "voice",
    };
  }
  return apiPost(`/interactions/${encodeURIComponent(interactionId)}/wrap-up`, body, {
    headers: { "Idempotency-Key": `wrap-${interactionId}-${Date.now()}` },
  });
}

export function useWrapUpHandoff() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { interactionId: string; customerId: string } & WrapUpPayload) =>
      wrapUpHandoff(input.interactionId, input.customerId, input),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: ["handoff"] });
      void qc.invalidateQueries({ queryKey: ["handoff", "session", vars.interactionId] });
    },
  });
}
