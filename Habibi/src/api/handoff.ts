// -----------------------------------------------------------------------------
// Handoff Hub — the follow-up desk for calls a Voice Studio agent handed to a
// person. The engine bridges the caller to the callback line and its own leg
// ends, so a handoff is a case worked after (or beside) the call, not a live
// call in this page.
//   GET  /handoff/queue                       open cases to claim, and the actor's own
//   GET  /handoff/{interactionId}             the case
//   GET  /handoff/{interactionId}/copilot/stream
//   POST /handoff/{id}/claim                  claim, or take over (expectedAssigneeId)
//   POST /handoff/{id}/disclosures
//   POST /handoff/{id}/suggestions/{sid}/accept
//   POST /interactions/{id}/wrap-up
// -----------------------------------------------------------------------------

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { z } from "zod";

import type { DisputeType } from "@/api/types/disputes";
import type { CbReason } from "@/api/types/callbacks";
import type { FloorApproval, FloorCopilot } from "@/api/floor";
import { invalidateCustomer } from "./customers";
import { invalidateDisputeReads } from "./disputes";
import { invalidatePromiseReads } from "./promises";
import { ApiError, apiEventStream, apiGet, apiPost } from "./config";
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
const transferOutcomeSchema = z
  .enum(["ringing", "connected", "not_connected", "no_line"])
  .nullable();

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
      /** The bot's evidence from the call, or a person's attestation here. */
      source: z.enum(["bot", "human"]).nullable(),
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
  wrapUp: z
    .object({
      outcome: z.string().nullable(),
      notes: z.string().nullable(),
      at: z.string().nullable(),
      byUserId: z.string().nullable(),
    })
    .nullable(),
  filed: z.array(z.object({ kind: z.enum(["promise", "dispute", "callback"]), id: z.string() })),
  copilotEvidence: z.string(),
});

const queueItemSchema = z.object({
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
});

/** HandoffQueueResponse — GET /handoff/queue. */
const handoffQueueSchema = z.object({
  items: z.array(queueItemSchema),
  total: z.number(),
  mine: z.array(queueItemSchema),
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
export type FiledRecord = HandoffSession["filed"][number];

const sessionKey = (interactionId: string) => ["handoff", "session", interactionId] as const;

export type QueueParams = { customerId?: string; search?: string; limit?: number };

export async function fetchHandoffQueue(params: QueueParams = {}): Promise<HandoffQueue> {
  const q = new URLSearchParams();
  if (params.customerId) q.set("customerId", params.customerId);
  if (params.search?.trim()) q.set("q", params.search.trim());
  if (params.limit) q.set("limit", String(params.limit));
  const qs = q.toString();
  return apiGet<HandoffQueue>(`/handoff/queue${qs ? `?${qs}` : ""}`, {
    schema: handoffQueueSchema,
  });
}

/** Polled only while the queue is on screen. `mine` is the actor's caseload. */
export function useHandoffQueue(params: QueueParams = {}) {
  return useQuery({
    queryKey: [
      "handoff",
      "queue",
      params.customerId ?? "",
      params.search?.trim() ?? "",
      params.limit ?? 0,
    ],
    queryFn: () => fetchHandoffQueue(params),
    staleTime: 2_000,
    refetchInterval: 5_000,
    // A new search or a longer page keeps the last list up while it loads.
    placeholderData: (prev) => prev,
  });
}

export async function fetchHandoffSession(interactionId: string): Promise<HandoffSession> {
  return apiGet<HandoffSession>(`/handoff/${encodeURIComponent(interactionId)}`, {
    schema: handoffSessionSchema,
  });
}

/**
 * The case, kept fresh while it is open or its call is live: someone else may
 * claim it, the bot call may end, the transcript is filed when it does -- a
 * case wrapped up mid-call still has a call to finish. A refresh that fails
 * keeps the last snapshot (`isRefetchError`); the page says how old it is.
 */
export function useHandoffSession(interactionId: string | undefined) {
  return useQuery({
    queryKey: sessionKey(interactionId ?? ""),
    queryFn: () => fetchHandoffSession(interactionId!),
    enabled: Boolean(interactionId),
    staleTime: 1_000,
    refetchInterval: (q) => pollCase(q.state.data, q.state.error),
  });
}

/** How often to read the case again: not once it is closed with its call
 * over, nor once it is no longer the reader's to see (403/404). */
export function pollCase(data: HandoffSession | undefined, error: unknown): number | false {
  const lost = error instanceof ApiError && [403, 404].includes(error.status);
  const settled = data?.status === "completed" && data.activeCall.callState !== "live";
  return settled || lost ? false : 5_000;
}

/** Claim a waiting case or -- a supervisor, with `expectedAssigneeId` --
 * take over a colleague's; refused if the holder changed meanwhile. */
export async function claimHandoff(input: {
  interactionId: string;
  expectedAssigneeId?: string | null;
}): Promise<HandoffSession> {
  const body =
    input.expectedAssigneeId === undefined ? {} : { expectedAssigneeId: input.expectedAssigneeId };
  return apiPost<HandoffSession>(
    `/handoff/${encodeURIComponent(input.interactionId)}/claim`,
    body,
    { schema: handoffSessionSchema },
  );
}

/** A claim, a takeover or a wrap-up moves the case's text thread and its
 * handler: the Inbox and the Floor read both. (My Workspace refreshes after
 * every write: router.tsx.) */
function invalidateCaseReaders(qc: QueryClient) {
  for (const key of ["conversations", "conversation-counts", "conversation", "floor"]) {
    void qc.invalidateQueries({ queryKey: [key] });
  }
}

export function useClaimHandoff() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: claimHandoff,
    onSuccess: (session) => {
      qc.setQueryData(sessionKey(session.interactionId), session);
      invalidateCaseReaders(qc);
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
  handoffId: string,
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
  // One key per case: a retry of the same wrap-up carries the same key and
  // gets the first answer back. A refused wrap-up stores nothing under it, so
  // a corrected retry still goes through; a closed case refuses any other.
  return apiPost(`/interactions/${encodeURIComponent(interactionId)}/wrap-up`, body, {
    headers: { "Idempotency-Key": `wrap-${handoffId}` },
    schema: wrapUpSchema,
  });
}

export function useWrapUpHandoff() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: (
      input: { interactionId: string; handoffId: string; customerId: string } & WrapUpPayload,
    ) => wrapUpHandoff(input.interactionId, input.handoffId, input.customerId, input),
    // The records it filed are read on their own pages and in the 360.
    onSuccess: (result, input) => {
      // The queue page shows its cache while it refetches: the closed case
      // must not flash back into the caseload.
      qc.setQueriesData<HandoffQueue>(
        { queryKey: ["handoff", "queue"] },
        (q) => q && { ...q, mine: q.mine.filter((c) => c.interactionId !== input.interactionId) },
      );
      void qc.invalidateQueries({ queryKey: ["handoff"] });
      if (result.spawned.promise) invalidatePromiseReads(qc, input.customerId);
      if (result.spawned.dispute) invalidateDisputeReads(qc, input.customerId);
      if (result.spawned.callback) void qc.invalidateQueries({ queryKey: ["callbacks"] });
      invalidateCustomer(qc, input.customerId);
      invalidateCaseReaders(qc);
    },
  });
}

// -----------------------------------------------------------------------------
// Copilot — the engines' draft for this case, streamed: the pack, then the
// whisper as tokens. One finite stream per open. It reopens when the case's
// evidence changes (the transcript, a policy, the approvals waiting: the
// session's `copilotEvidence`) and on `refresh()`, never on an unchanged poll.
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

export function useCopilotStream(interactionId: string, evidence: string) {
  const [state, setState] = useState<CopilotStreamState>(EMPTY_STREAM);
  const [opened, setOpened] = useState(0);

  useEffect(() => {
    const ac = new AbortController();
    // The pack carries the engines' own draft: it shows at once, and the
    // polished wording replaces it as its tokens arrive.
    let polished = "";
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
            whisper: str(payload.engineDraft) ?? "",
            vetoes: pack.vetoes ?? [],
            unavailable: pack.engines.unavailable ?? [],
            card: pack.card,
            approvals: pack.approvals ?? [],
            streaming: true,
          });
          return;
        }
        if (event === "token") {
          polished += str(payload.text) ?? "";
          setState((prev) => ({ ...prev, whisper: polished }));
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
  }, [interactionId, evidence, opened]);

  return { ...state, refresh: () => setOpened((n) => n + 1) };
}
