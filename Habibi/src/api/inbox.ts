// -----------------------------------------------------------------------------
// Conversation Inbox — data access.
//   GET  /conversations               the list: summaries, no transcripts.
//                                     ?updatedAfter= deltas; ?q= / ?customerId=
//                                     search the whole inbox on the server
//   GET  /conversations/{id}          the open thread: transcript, suggestions,
//                                     customer context. Polled on its own.
//   POST takeover / return-to-bot / messages / suggestions/refresh
//
// "Mine" is derived server-side (assignedUserId === the caller). A write's
// response is the thread's newest state; it is put into both caches at once.
// -----------------------------------------------------------------------------

import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import type { Thread, ThreadSummary } from "@/api/types/inbox";
import { apiGet, apiPost, apiUpload, retryUnlessClientError } from "./config";

export type CannedResponse = { id: string; label: string; text: string };

/** The newest threads the list carries (db_inbox.INBOX_LIST_LIMIT). */
export const INBOX_LIST_LIMIT = 500;

/** Shared across hook instances so Strict Mode remounts don't reset full-refresh cadence. */
let conversationPollCount = 0;

/** Poll every 4s; 1.5s while the bot is composing or a reply is in flight; never while hidden. */
function pollEvery(busy: boolean): number | false {
  if (typeof document !== "undefined" && document.visibilityState === "hidden") return false;
  return busy ? 1_500 : 4_000;
}

function maxUpdatedAt(rows: ThreadSummary[]): string | null {
  let best: string | null = null;
  for (const row of rows) {
    const at = row.updatedAt;
    if (at && (!best || at > best)) best = at;
  }
  return best;
}

/**
 * The server's list order, reproduced exactly:
 *   ORDER BY COALESCE(last message, created_at) DESC, cv.id
 *
 * By the last message, not by `updatedAt`: that is the change watermark, and a
 * takeover or a delivery receipt moves it -- sorting on it made threads jump
 * to the top for something nobody said. Ties break on id, as the server's do,
 * so a delta poll and a full poll agree and rows never swap on their own.
 */
export function compareThreads(a: ThreadSummary, b: ThreadSummary): number {
  const au = a.lastAt || "";
  const bu = b.lastAt || "";
  if (au !== bu) return bu.localeCompare(au);
  return (a.id || "").localeCompare(b.id || "");
}

export function mergeThreads(prev: ThreadSummary[], deltas: ThreadSummary[]): ThreadSummary[] {
  if (!deltas.length) return prev;
  const byId = new Map(prev.map((t) => [t.id, t]));
  for (const d of deltas) byId.set(d.id, d);
  return Array.from(byId.values()).sort(compareThreads);
}

export async function fetchConversations(
  opts: { updatedAfter?: string | null; q?: string; customerId?: string } = {},
): Promise<ThreadSummary[]> {
  const params = new URLSearchParams();
  if (opts.updatedAfter) params.set("updatedAfter", opts.updatedAfter);
  if (opts.q?.trim()) params.set("q", opts.q.trim());
  if (opts.customerId) params.set("customerId", opts.customerId);
  const qs = params.toString();
  return apiGet<ThreadSummary[]>(`/conversations${qs ? `?${qs}` : ""}`);
}

export async function fetchConversation(threadId: string): Promise<Thread> {
  return apiGet<Thread>(`/conversations/${encodeURIComponent(threadId)}`);
}

/**
 * The open thread. Read by id -- never looked up in the list, so a link to a
 * thread older than the list's page still opens it -- and polled on its own,
 * so its transcript, ticks and customer context stay as fresh as the list.
 */
export function useConversation(threadId: string | null | undefined) {
  return useQuery({
    queryKey: ["conversation", threadId],
    queryFn: () => fetchConversation(threadId as string),
    enabled: Boolean(threadId),
    retry: retryUnlessClientError,
    refetchInterval: (q) => {
      const t = q.state.data;
      const busy = Boolean(
        t?.botTyping || t?.messages?.some((m) => "delivery" in m && m.delivery === "pending"),
      );
      return pollEvery(busy);
    },
    refetchOnWindowFocus: true,
  });
}

/** The list; with a search term, the server's matches across the whole inbox. */
export function useConversations(search = "") {
  const queryClient = useQueryClient();
  const q = search.trim();

  const query = useQuery({
    queryKey: ["conversations", q],
    queryFn: async () => {
      if (q) return fetchConversations({ q });
      conversationPollCount += 1;
      const prev = queryClient.getQueryData<ThreadSummary[]>(["conversations", ""]);
      // Full list on first fetch and every ~15th poll (~60s at 4s interval).
      const after = prev ? maxUpdatedAt(prev) : null;
      if (!prev || !after || conversationPollCount % 15 === 0) return fetchConversations();
      return mergeThreads(prev, await fetchConversations({ updatedAfter: after }));
    },
    staleTime: 2_000,
    // A malformed `updatedAfter` is a client bug, not a blip.
    retry: retryUnlessClientError,
    refetchInterval: (query) => pollEvery(Boolean(query.state.data?.some((t) => t.botTyping))),
    refetchOnWindowFocus: true,
  });

  // Resume polling immediately when the tab becomes visible again.
  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === "visible") {
        void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [queryClient]);

  return query;
}

/** Put a write's answer into the thread's cache and its row in every list. */
export function applyThread(queryClient: QueryClient, thread: Thread) {
  queryClient.setQueryData(["conversation", thread.id], thread);
  queryClient.setQueriesData<ThreadSummary[]>({ queryKey: ["conversations"] }, (prev) =>
    prev?.map((t) => (t.id === thread.id ? { ...t, ...summaryOf(thread) } : t)),
  );
}

function summaryOf(thread: Thread): ThreadSummary {
  const { messages: _m, ragSuggestions: _r, ragDraftAnswer: _d, context: _c, ...summary } = thread;
  return summary;
}

export async function fetchCannedResponses(): Promise<CannedResponse[]> {
  return apiGet<CannedResponse[]>("/canned-responses");
}

export function useCannedResponses() {
  return useQuery({
    queryKey: ["canned-responses"],
    queryFn: fetchCannedResponses,
    staleTime: 5 * 60_000,
    retry: retryUnlessClientError,
  });
}

/** `expectedAssigneeId`: who the caller saw holding it. The server refuses if that changed. */
export async function takeoverConversation(
  threadId: string,
  expectedAssigneeId: string | null,
): Promise<Thread> {
  return apiPost<Thread>(`/conversations/${threadId}/takeover`, { expectedAssigneeId });
}

export async function returnConversationToBot(threadId: string): Promise<Thread> {
  return apiPost<Thread>(`/conversations/${threadId}/return-to-bot`, {});
}

/** `idempotencyKey` names one attempt at one reply: a resend after a lost response is not a second message. */
export async function sendConversationMessage(
  threadId: string,
  text: string,
  idempotencyKey: string,
): Promise<Thread> {
  return apiPost<Thread>(
    `/conversations/${threadId}/messages`,
    { text },
    { headers: { "Idempotency-Key": idempotencyKey } },
  );
}

export interface ConversationSuggestionsRefreshResult {
  conversationId: string;
  ragSuggestions: string[];
  draftAnswer?: string | null;
  chatModel?: string | null;
  latencyMs?: number | null;
  logId?: string | null;
  /** The knowledge base could not be searched; these are last time's passages. */
  stale?: boolean;
}

/** Voice Studio knowledge base → passages for the thread (+ optional drafted reply). */
export async function refreshConversationSuggestions(
  threadId: string,
  opts: { topK?: number; includeDraftAnswer?: boolean } = {},
): Promise<ConversationSuggestionsRefreshResult> {
  return apiPost<ConversationSuggestionsRefreshResult>(
    `/conversations/${threadId}/suggestions/refresh`,
    {
      topK: opts.topK ?? 4,
      includeDraftAnswer: opts.includeDraftAnswer ?? false,
    },
  );
}

/** Files an image to the customer's documents. It is not sent to the customer. */
export async function ingestInboxDocument(
  customerId: string,
  file: File,
  conversationId: string,
): Promise<{ documentRequestId?: string; source?: string }> {
  const form = new FormData();
  form.append("customer_id", customerId);
  form.append("file", file);
  form.append("conversation_id", conversationId);
  return apiUpload("/document-requests/ingest", form);
}
