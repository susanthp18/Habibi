// -----------------------------------------------------------------------------
// Handoff Hub — the follow-up desk for calls a Voice Studio agent handed to a
// person. The engine bridges the caller to the callback line and its own leg
// ends, so a handoff is a case worked after (or beside) the call, not a live
// call in this page.
//   GET  /handoff/queue                       open cases the actor may claim
//   GET  /handoff/{interactionId}             the case
//   GET  /handoff/{interactionId}/copilot/stream
//   POST /handoff/{id}/claim
//   POST /handoff/{id}/disclosures
//   POST /handoff/{id}/suggestions/{sid}/accept
//   POST /interactions/{id}/wrap-up
// -----------------------------------------------------------------------------

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import type { DisputeType } from "@/api/types/disputes";
import type { CbReason } from "@/api/types/callbacks";
import type { FloorApproval, FloorCopilot } from "@/api/floor";
import { apiEventStream, apiGet, apiPost } from "./config";
import { FloorCopilotResponse } from "./wire/generated";
import { disputeSchema, ptpPromiseSchema } from "./customers";
import { offerPolicySchema } from "@/lib/offer-policy";
import { authorityPolicySchema } from "@/lib/authority-policy";

// -----------------------------------------------------------------------------
// Wire schemas — field-for-field with backend/schemas/common.py. The handoff
// routes set no exclude_unset, so `| None = None` is `.nullable()`; the wrap-up
// route does, so its spawned children are `.nullable().optional()`.
// -----------------------------------------------------------------------------

const caseStatusSchema = z.enum(["pending_claim", "active", "completed"]);
const transferOutcomeSchema = z.enum(["callback_line", "no_one_available"]).nullable();

/** HandoffSessionResponse — GET /handoff/:id and the three POSTs. */
const handoffSessionSchema = z.object({
  interactionId: z.string(),
  handoffId: z.string(),
  customerId: z.string(),
  conversationId: z.string().nullable(),
  status: caseStatusSchema,
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
    status: caseStatusSchema,
    claimed: z.boolean(),
    risk: z.string(),
    handlerUserId: z.string().nullable(),
    requestedAt: z.string().nullable(),
    callState: z.enum(["live", "ended"]),
    callEndedAt: z.string().nullable(),
    transferOutcome: transferOutcomeSchema,
  }),
  customerContext: z.object({
    risk: z.string(),
    outstanding: z.number().nullable(),
    currency: z.string(),
    lastPromise: z.object({ amount: z.number(), date: z.string(), status: z.string() }).nullable(),
    nextEmi: z
      .object({ amount: z.number(), dueDate: z.string(), daysOverdue: z.number() })
      .nullable(),
    openDisputes: z.number(),
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
      accepted: z.boolean(),
      stale: z.boolean(),
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
  outcomes: z.array(
    z.object({ label: z.string(), needs: z.enum(["promise", "callback", "dispute", "notes"]) }),
  ),
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
      transferOutcome: transferOutcomeSchema,
    }),
  ),
  total: z.number(),
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
export type HandoffSession = z.infer<typeof handoffSessionSchema>;
export type ActiveCall = HandoffSession["activeCall"];
export type CustomerContext = HandoffSession["customerContext"];
export type ComplianceItem = HandoffSession["complianceItems"][number];
export type HandoffAlert = HandoffSession["alerts"][number];
export type HandoffSuggestion = HandoffSession["suggestions"][number];
export type TranscriptTurn = HandoffSession["transcriptScript"][number];
export type HandoffQueue = z.infer<typeof handoffQueueSchema>;
export type HandoffQueueItem = HandoffQueue["items"][number];
export type TransferOutcome = NonNullable<ActiveCall["transferOutcome"]>;
export type WrapUpOutcome = HandoffSession["outcomes"][number];

const sessionKey = (interactionId: string) => ["handoff", "session", interactionId] as const;

export async function fetchHandoffQueue(customerId?: string): Promise<HandoffQueue> {
  const q = customerId ? `?customerId=${encodeURIComponent(customerId)}` : "";
  return apiGet<HandoffQueue>(`/handoff/queue${q}`, { schema: handoffQueueSchema });
}

/** Polled only while the queue is on screen. `activeInteractionId` is the
 * actor's own open case, offered to resume. */
export function useHandoffQueue(customerId?: string, opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ["handoff", "queue", customerId ?? ""],
    queryFn: () => fetchHandoffQueue(customerId),
    enabled: opts?.enabled ?? true,
    staleTime: 2_000,
    refetchInterval: 5_000,
  });
}

export async function fetchHandoffSession(interactionId: string): Promise<HandoffSession> {
  return apiGet<HandoffSession>(`/handoff/${encodeURIComponent(interactionId)}`, {
    schema: handoffSessionSchema,
  });
}

/**
 * The case, kept fresh while it is open: someone else may claim it, the bot
 * call may end, the transcript is filed when it does. A refresh that fails
 * keeps the last snapshot (`isRefetchError`); the page says how old it is.
 */
export function useHandoffSession(interactionId: string | undefined) {
  return useQuery({
    queryKey: sessionKey(interactionId ?? ""),
    queryFn: () => fetchHandoffSession(interactionId!),
    enabled: Boolean(interactionId),
    staleTime: 1_000,
    refetchInterval: (q) => (q.state.data?.status === "completed" ? false : 5_000),
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
      qc.setQueryData(sessionKey(session.interactionId), session);
    },
    // Taken by someone else, or gone: the queue must stop offering it.
    onSettled: () => void qc.invalidateQueries({ queryKey: ["handoff", "queue"] }),
  });
}

/** Writes return the whole case; it replaces the cached one, so the page shows
 * what the server recorded and never a tick it refused. */
function useCaseWrite<V>(interactionId: string, write: (v: V) => Promise<HandoffSession>) {
  const qc = useQueryClient();
  return useMutation({
    // The page says why a write failed, beside what it was writing.
    meta: { errors: "caller" },
    mutationFn: write,
    onSuccess: (session) => qc.setQueryData(sessionKey(interactionId), session),
  });
}

export function useRecordDisclosure(interactionId: string) {
  return useCaseWrite(
    interactionId,
    (payload: { itemId: string; ruleId?: string | null; label?: string; read: boolean }) =>
      apiPost<HandoffSession>(
        `/handoff/${encodeURIComponent(interactionId)}/disclosures`,
        payload,
        { schema: handoffSessionSchema },
      ),
  );
}

export function useAcceptSuggestion(interactionId: string) {
  return useCaseWrite(interactionId, (suggestionId: string) =>
    apiPost<HandoffSession>(
      `/handoff/${encodeURIComponent(interactionId)}/suggestions/${encodeURIComponent(suggestionId)}/accept`,
      {},
      { schema: handoffSessionSchema },
    ),
  );
}

/** What the wrap-up form collects. The outcome decides which record is required. */
export type WrapUpPayload = {
  disposition: string;
  notes: string;
  promise?: { amount: number; promisedDate: string };
  callback?: { scheduledAt: string; reason: CbReason; assigneeUserId?: string };
  dispute?: { type: DisputeType; amount?: number };
};

export async function wrapUpHandoff(
  interactionId: string,
  customerId: string,
  payload: WrapUpPayload,
): Promise<WrapUpResult> {
  // The server fills each record's account, interaction and channel from the
  // interaction itself.
  const record = { customerId, interactionId };
  const body: Record<string, unknown> = {
    disposition: payload.disposition,
    notes: payload.notes.trim() || null,
  };
  if (payload.promise) body.promise = { ...record, ...payload.promise };
  if (payload.callback) body.callback = { ...record, ...payload.callback };
  if (payload.dispute) body.dispute = { ...record, ...payload.dispute };
  // One key per interaction: a retry of the same wrap-up must carry the same
  // key, or the server sees two requests and files two wrap-ups. A refused
  // wrap-up stores nothing under it, so a corrected retry still goes through.
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
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["handoff"] }),
  });
}

// -----------------------------------------------------------------------------
// Copilot — the engines' draft for this case, streamed: the pack, then the
// whisper as tokens. One finite stream per open; `refresh()` reopens it (after
// an approval is signalled, or when the agent asks).
// -----------------------------------------------------------------------------

export type CopilotStreamState = {
  whisper: string;
  vetoes: string[];
  /** Engines that could not be read: their silence is not "no decision". */
  unavailable: string[];
  card: FloorCopilot["card"];
  approvals: FloorApproval[];
  streaming: boolean;
  done: boolean;
  error: string | null;
};

const EMPTY_STREAM: CopilotStreamState = {
  whisper: "",
  vetoes: [],
  unavailable: [],
  card: undefined,
  approvals: [],
  streaming: false,
  done: false,
  error: null,
};

export function useCopilotStream(interactionId: string) {
  const [state, setState] = useState<CopilotStreamState>(EMPTY_STREAM);
  const [opened, setOpened] = useState(0);

  useEffect(() => {
    const ac = new AbortController();
    setState({ ...EMPTY_STREAM, streaming: true });
    const str = (v: unknown): string | undefined => (typeof v === "string" ? v : undefined);

    void apiEventStream(
      `/handoff/${encodeURIComponent(interactionId)}/copilot/stream`,
      (event, data) => {
        const payload = (data ?? {}) as Record<string, unknown>;
        if (event === "pack") {
          const pack = FloorCopilotResponse.parse(payload);
          setState({
            ...EMPTY_STREAM,
            whisper: "",
            vetoes: pack.vetoes ?? [],
            unavailable: pack.engines.unavailable ?? [],
            card: pack.card,
            approvals: pack.approvals ?? [],
            streaming: true,
          });
          return;
        }
        if (event === "token") {
          const chunk = str(payload.text) ?? "";
          setState((prev) => ({ ...prev, whisper: prev.whisper + chunk }));
          return;
        }
        if (event === "done") {
          setState((prev) => ({
            ...prev,
            whisper: str(payload.whisperDraft) ?? prev.whisper,
            vetoes: Array.isArray(payload.vetoes) ? (payload.vetoes as string[]) : prev.vetoes,
            streaming: false,
            done: true,
          }));
          return;
        }
        if (event === "error") {
          setState((prev) => ({
            ...prev,
            streaming: false,
            done: true,
            error: str(payload.detail) ?? "copilot_failed",
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
  }, [interactionId, opened]);

  return { ...state, refresh: () => setOpened((n) => n + 1) };
}
