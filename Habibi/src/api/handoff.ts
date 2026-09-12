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
import { z } from "zod";

import type {
  ComplianceItem as SeedComplianceItem,
  Suggestion,
  TranscriptTurn,
} from "@/api/types/handoff";
import { apiGet, apiPost } from "./config";
import { disputeSchema, ptpPromiseSchema } from "./customers";
import { offerPolicySchema, type OfferPolicy } from "@/lib/offer-policy";
import { authorityPolicySchema, type AuthorityPolicy } from "@/lib/authority-policy";

// -----------------------------------------------------------------------------
// Wire schemas — field-for-field with backend/schemas.py. The handoff routes
// set no exclude_unset, so `| None = None` is `.nullable()`; the wrap-up route
// does, so its spawned children are `.nullable().optional()`.
// -----------------------------------------------------------------------------

const handoffStatusSchema = z.enum(["pending_claim", "active", "completed"]);

/** HandoffSessionResponse — GET /handoff/active, GET /handoff/:id, and the three POSTs. */
const handoffSessionSchema = z.object({
  interactionId: z.string(),
  handoffId: z.string(),
  customerId: z.string(),
  conversationId: z.string().nullable(),
  status: handoffStatusSchema,
  claimed: z.boolean(),
  monitor: z.boolean(),
  activeCall: z.object({
    interactionId: z.string(),
    handoffId: z.string(),
    customerId: z.string(),
    conversationId: z.string().nullable(),
    customerName: z.string(),
    accountId: z.string(),
    phone: z.string(),
    channel: z.string(),
    agentName: z.string(),
    transferredFrom: z.string(),
    escalationReason: z.string(),
    startedAt: z.number(),
    status: handoffStatusSchema,
    claimed: z.boolean(),
    risk: z.string(),
    handlerUserId: z.string().nullable(),
  }),
  // HandoffCustomerContext has no `liveQa`; pydantic drops it before the wire.
  customerContext: z.object({
    risk: z.string(),
    outstanding: z.number(),
    currency: z.string(),
    lastPromise: z.object({ amount: z.number(), date: z.string(), status: z.string() }).nullable(),
    nextEmi: z
      .object({ amount: z.number(), dueDate: z.string(), daysOverdue: z.number() })
      .nullable(),
    openDisputes: z.number(),
    dnd: z.object({ allowed: z.boolean(), window: z.string(), channels: z.array(z.string()) }),
    tenureMonths: z.number(),
    product: z.string(),
    offerPolicy: offerPolicySchema.nullable(),
    authorityPolicy: authorityPolicySchema.nullable(),
  }),
  transcriptScript: z.array(
    z.object({
      id: z.string(),
      speaker: z.string(),
      text: z.string(),
      at: z.number(),
      sentimentDelta: z.number().nullable(),
    }),
  ),
  sentimentSeries: z.array(z.number()),
  suggestions: z.array(
    z.object({
      id: z.string(),
      title: z.string(),
      body: z.string(),
      source: z.string(),
      showAfter: z.number(),
      accepted: z.boolean(),
    }),
  ),
  complianceItems: z.array(
    z.object({
      id: z.string(),
      label: z.string(),
      required: z.boolean(),
      checked: z.boolean(),
      locked: z.boolean(),
      ruleId: z.string().nullable(),
    }),
  ),
  alerts: z.array(
    z.object({
      id: z.string(),
      kind: z.string(),
      severity: z.string(),
      reason: z.string().nullable(),
    }),
  ),
  dispositions: z.array(z.string()),
  speakers: z.record(z.string()),
});

/** HandoffQueueResponse — GET /handoff/queue. */
const handoffQueueSchema = z.object({
  items: z.array(
    z.object({
      interactionId: z.string(),
      handoffId: z.string(),
      customerId: z.string(),
      customerName: z.string(),
      accountId: z.string(),
      reason: z.string(),
      queue: z.string().nullable(),
      risk: z.string(),
      waitSec: z.number(),
      requestedAt: z.string().nullable(),
    }),
  ),
  activeInteractionId: z.string().nullable(),
});

/** WrapUpResponse — POST /interactions/:id/wrap-up, response_model_exclude_unset. */
const wrapUpSchema = z.object({
  id: z.string(),
  spawned: z.object({
    promise: ptpPromiseSchema.nullable().optional(),
    dispute: disputeSchema.nullable().optional(),
    callback: z.object({ id: z.string(), status: z.string().nullable() }).nullable().optional(),
  }),
});

export type WrapUpResult = z.infer<typeof wrapUpSchema>;

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
  /** Seed replay: transcript ticks locally and wrap-up does not POST. */
  scriptedReplay?: boolean;
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
  scriptedReplay?: boolean;
};

export async function fetchHandoffQueue(customerId?: string): Promise<HandoffQueue> {
  const q = customerId ? `?customerId=${encodeURIComponent(customerId)}` : "";
  return apiGet<HandoffQueue>(`/handoff/queue${q}`, { schema: handoffQueueSchema });
}

export function useHandoffQueue(customerId?: string) {
  return useQuery({
    queryKey: ["handoff", "queue", customerId ?? ""],
    queryFn: () => fetchHandoffQueue(customerId),
    staleTime: 2_000,
    refetchInterval: 5_000,
  });
}

export async function fetchHandoffActive(): Promise<HandoffSession | null> {
  const session = await apiGet<HandoffSession | undefined>("/handoff/active", {
    schema: handoffSessionSchema,
  });
  return session ?? null;
}

export async function fetchHandoffSession(interactionId: string): Promise<HandoffSession> {
  return apiGet<HandoffSession>(`/handoff/${encodeURIComponent(interactionId)}`, {
    schema: handoffSessionSchema,
  });
}

export function useHandoffActive() {
  return useQuery({
    queryKey: ["handoff", "active"],
    queryFn: fetchHandoffActive,
    staleTime: 2_000,
    refetchInterval: 5_000,
  });
}

export function useHandoffSession(interactionId: string | undefined, opts?: { poll?: boolean }) {
  const poll = Boolean(opts?.poll);
  return useQuery({
    queryKey: ["handoff", "session", interactionId ?? ""],
    queryFn: () => fetchHandoffSession(interactionId!),
    enabled: Boolean(interactionId),
    staleTime: 1_000,
    refetchInterval: (q) => {
      if (!poll) return false;
      const s = q.state.data;
      if (!s || !s.claimed || s.status !== "active") return false;
      return 2_000;
    },
  });
}

export async function claimHandoff(interactionId: string): Promise<HandoffSession> {
  return apiPost<HandoffSession>(
    `/handoff/${encodeURIComponent(interactionId)}/claim`,
    {},
    { schema: handoffSessionSchema },
  );
}

export function useClaimHandoff() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
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
  return apiPost<HandoffSession>(
    `/handoff/${encodeURIComponent(interactionId)}/disclosures`,
    payload,
    { schema: handoffSessionSchema },
  );
}

export async function acceptHandoffSuggestion(
  interactionId: string,
  suggestionId: string,
): Promise<HandoffSession> {
  return apiPost<HandoffSession>(
    `/handoff/${encodeURIComponent(interactionId)}/suggestions/${encodeURIComponent(suggestionId)}/accept`,
    {},
    { schema: handoffSessionSchema },
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
): Promise<WrapUpResult> {
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
  // One key per interaction: a retry of the same wrap-up must carry the same
  // key, or the server sees two requests and files two wrap-ups. `Date.now()`
  // in the key made every retry a first attempt.
  return apiPost(`/interactions/${encodeURIComponent(interactionId)}/wrap-up`, body, {
    headers: { "Idempotency-Key": `wrap-${interactionId}` },
    schema: wrapUpSchema,
  });
}

export function useWrapUpHandoff() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: (input: { interactionId: string; customerId: string } & WrapUpPayload) =>
      wrapUpHandoff(input.interactionId, input.customerId, input),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: ["handoff"] });
      void qc.invalidateQueries({ queryKey: ["handoff", "session", vars.interactionId] });
    },
  });
}
