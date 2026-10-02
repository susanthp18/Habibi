// -----------------------------------------------------------------------------
// Conversation Inbox — data access.
//   GET  /conversations               the list: summaries, no transcripts, a page
//                                     at a time (?beforeAt=&beforeId= the next).
//                                     ?updatedAfter= deltas; ?q= / ?customerId= /
//                                     ?view= search the whole inbox on the server
//   GET  /conversations/counts        threads per view, across the whole inbox
//   GET  /conversations/{id}          the open thread: transcript, suggestions,
//                                     customer context. Polled on its own.
//   POST takeover / return-to-bot / messages / suggestions/refresh
//
// "Mine" is derived server-side (assignedUserId === the caller). A write's
// response is the open thread's newest state; the list is read again.
// -----------------------------------------------------------------------------

import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import type { InboxView, Thread, ThreadSummary } from "@/api/types/inbox";
import { apiGet, apiPost, apiUpload, retryUnlessClientError } from "./config";

export type CannedResponse = { id: string; label: string; text: string };

/** Threads per page of the list (db_inbox.INBOX_LIST_LIMIT). */
export const INBOX_LIST_LIMIT = 500;

/**
 * The list as held: the server's rows in its order, whether older ones exist
 * past them, and how many times it has been polled -- per list, so two lists
 * never share a refresh cadence.
 */
export type ConversationPage = { rows: ThreadSummary[]; more: boolean; polls: number };

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
 *   ORDER BY COALESCE(last message, created_at) DESC, cv.id COLLATE "C"
 *
 * By the last message, not by `updatedAt`: that is the change watermark, and a
 * takeover or a delivery receipt moves it -- sorting on it made threads jump
 * to the top for something nobody said. Ties break on id bytewise, as the
 * server's do -- not by locale, which put CV-10 and CV-9 the other way round
 * -- so a delta poll, a full poll and the next page agree.
 */
export function compareThreads(a: ThreadSummary, b: ThreadSummary): number {
  const at = Date.parse(a.lastAt ?? "") || 0;
  const bt = Date.parse(b.lastAt ?? "") || 0;
  if (at !== bt) return bt - at;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

export function mergeThreads(prev: ThreadSummary[], deltas: ThreadSummary[]): ThreadSummary[] {
  if (!deltas.length) return prev;
  const byId = new Map(prev.map((t) => [t.id, t]));
  for (const d of deltas) byId.set(d.id, d);
  return Array.from(byId.values()).sort(compareThreads);
}

/**
 * A fresh first page, and the older rows the operator had loaded past it --
 * a refresh of the first page must not take away the ones they paged to.
 */
export function withOlder(
  page: ThreadSummary[],
  prev: ConversationPage | undefined,
): Pick<ConversationPage, "rows" | "more"> {
  const last = page[page.length - 1];
  if (!prev || !last || page.length < INBOX_LIST_LIMIT) {
    return { rows: page, more: page.length >= INBOX_LIST_LIMIT };
  }
  const fresh = new Set(page.map((t) => t.id));
  const older = prev.rows.filter((t) => !fresh.has(t.id) && compareThreads(last, t) < 0);
  return { rows: [...page, ...older], more: older.length ? prev.more : true };
}

export async function fetchConversations(
  opts: {
    updatedAfter?: string | null;
    q?: string;
    customerId?: string;
    view?: InboxView;
    /** The last row held: the page after it. */
    before?: Pick<ThreadSummary, "id" | "lastAt">;
  } = {},
): Promise<ThreadSummary[]> {
  const params = new URLSearchParams();
  if (opts.updatedAfter) params.set("updatedAfter", opts.updatedAfter);
  if (opts.q?.trim()) params.set("q", opts.q.trim());
  if (opts.customerId) params.set("customerId", opts.customerId);
  if (opts.view) params.set("view", opts.view);
  if (opts.before?.lastAt) {
    params.set("beforeAt", opts.before.lastAt);
    params.set("beforeId", opts.before.id);
  }
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

const listKey = (q: string, view?: InboxView) => ["conversations", q, view ?? null] as const;

/**
 * The list. With a search term or a view, the server's matches across the
 * whole inbox -- a view filtered on the loaded page missed every older thread
 * it should have held. Unfiltered, the newest page kept fresh by deltas.
 * Either way a page at a time: `useOlderConversations` reads the next.
 *
 * A search is not polled: it scans every message, and an operator reading
 * results needs them to hold still. It is read again on focus and after any
 * write.
 */
export function useConversations(search = "", view?: InboxView) {
  const queryClient = useQueryClient();
  const q = search.trim();
  const key = listKey(q, view);

  const query = useQuery({
    queryKey: key,
    queryFn: async (): Promise<ConversationPage> => {
      const prev = queryClient.getQueryData<ConversationPage>(key);
      const polls = (prev?.polls ?? 0) + 1;
      // Unfiltered: only what changed since the newest watermark, and the
      // whole first page every ~15th poll (~60s at 4s).
      const after = prev && !q && !view ? maxUpdatedAt(prev.rows) : null;
      if (prev && after && polls % 15 !== 0) {
        const deltas = await fetchConversations({ updatedAfter: after });
        return { ...prev, rows: mergeThreads(prev.rows, deltas), polls };
      }
      return { ...withOlder(await fetchConversations({ q, view }), prev), polls };
    },
    staleTime: 2_000,
    // A malformed `updatedAfter` is a client bug, not a blip.
    retry: retryUnlessClientError,
    refetchInterval: (query) =>
      q ? false : pollEvery(Boolean(query.state.data?.rows.some((t) => t.botTyping))),
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

/** The page after the last row the list holds, appended to it. */
export function useOlderConversations(search = "", view?: InboxView) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<{ loading: boolean; failed: boolean }>({
    loading: false,
    failed: false,
  });
  const load = async () => {
    const key = listKey(search.trim(), view);
    const last = queryClient.getQueryData<ConversationPage>(key)?.rows.at(-1);
    if (!last || state.loading) return;
    setState({ loading: true, failed: false });
    try {
      const page = await fetchConversations({ q: search.trim(), view, before: last });
      // A poll in flight read the list before this page: it would drop it.
      await queryClient.cancelQueries({ queryKey: key });
      queryClient.setQueryData<ConversationPage>(
        key,
        (cur) =>
          cur && {
            ...cur,
            rows: mergeThreads(cur.rows, page),
            more: page.length >= INBOX_LIST_LIMIT,
          },
      );
      setState({ loading: false, failed: false });
    } catch {
      setState({ loading: false, failed: true });
    }
  };
  return { load, ...state };
}

/** Threads in each view, across the whole inbox. */
export function useConversationCounts() {
  return useQuery({
    queryKey: ["conversation-counts"],
    queryFn: () => apiGet<Record<"all" | InboxView, number>>("/conversations/counts"),
    retry: retryUnlessClientError,
    refetchInterval: () => (pollEvery(false) === false ? false : 15_000),
    refetchOnWindowFocus: true,
  });
}

/**
 * A write's answer is the open thread; the list is read again rather than
 * patched. Patching a row in place left it out of order, and carried the
 * write's newer `updatedAt` into the delta watermark -- the next delta then
 * skipped every other thread that changed in between.
 */
export function applyThread(queryClient: QueryClient, thread: Thread) {
  queryClient.setQueryData(["conversation", thread.id], thread);
  void queryClient.invalidateQueries({ queryKey: ["conversations"] });
  void queryClient.invalidateQueries({ queryKey: ["conversation-counts"] });
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
  /** The customer message these answer; once they write again, they answer nothing. */
  answersMessageId?: string | null;
  ragSuggestions: string[];
  /** A reply to the customer, in their language; null when the passages do not answer them. */
  draftAnswer?: string | null;
  /** A draft was asked for and the model could not be reached. */
  draftFailed?: boolean;
  /** The knowledge base could not be searched; these are last time's passages. */
  stale?: boolean;
  /** The customer wrote again while this searched: nothing to show, nothing kept. */
  superseded?: boolean;
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
