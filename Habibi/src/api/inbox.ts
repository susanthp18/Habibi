// -----------------------------------------------------------------------------
// Conversation Inbox — data access seam.
//   fetchConversations() → list          (GET /conversations)
//   takeover / send message              → POST writes
//   fetchCannedResponses()               (GET /canned-responses)
//
// Mock branch preserves the in-memory seed. Live branch maps to the Phase 3B
// endpoints; callers invalidate + refetch rather than trusting partial bodies.
// "Mine" is derived server-side (assignedUserId === GET /me).
//
// Live polling uses ?updatedAfter= deltas when the tab is visible, with a
// periodic full refresh to heal drift.
// -----------------------------------------------------------------------------

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import type { Thread } from "@/api/types/inbox";
import { apiGet, apiPost, apiUpload, retryUnlessClientError } from "./config";

export type CannedResponse = { id: string; label: string; text: string };

/** Shared across hook instances so Strict Mode remounts don't reset full-refresh cadence. */
let conversationPollCount = 0;

function formatNowLabel(): string {
  const now = new Date();
  const h = now.getHours();
  const m = now.getMinutes().toString().padStart(2, "0");
  const ampm = h >= 12 ? "PM" : "AM";
  const hh = ((h + 11) % 12) + 1;
  return `${hh}:${m} ${ampm}`;
}

function maxUpdatedAt(rows: Thread[]): string | null {
  let best: string | null = null;
  for (const row of rows) {
    const at = row.updatedAt;
    if (!at) continue;
    if (!best || at > best) best = at;
  }
  return best;
}

function mergeThread(existing: Thread, delta: Thread): Thread {
  // Delta polls may omit heavy fields; never wipe cached transcript / RAG chips.
  const merged: Thread = { ...existing, ...delta };
  if (delta.messages === undefined) merged.messages = existing.messages;
  if (delta.ragSuggestions === undefined) merged.ragSuggestions = existing.ragSuggestions;
  if (delta.ragDraftAnswer === undefined) merged.ragDraftAnswer = existing.ragDraftAnswer;
  if (delta.context === undefined) merged.context = existing.context;
  return merged;
}

/**
 * The server's list order, reproduced exactly:
 *   ORDER BY COALESCE(updated_at, created_at) DESC, cv.id
 *
 * Both halves used to differ. The tiebreak compared `lastTime`, which is a
 * 12-hour clock string with no date — so `"9:40 AM"` sorts after `"10:29 AM"`
 * lexicographically, and every thread whose hour has one digit fewer landed in
 * the wrong place. That is not hypothetical: the seeded threads all carry the
 * same `updatedAt` to the microsecond (one bulk transaction), so the tiebreak
 * decided the entire list.
 *
 * Sorting ties by id instead also settles a second disagreement. A full poll
 * renders the server's order verbatim while a delta poll re-sorts here, so any
 * mismatch made rows swap places every ~60s for no reason a user could see.
 */
export function compareThreads(a: Thread, b: Thread): number {
  const au = a.updatedAt || "";
  const bu = b.updatedAt || "";
  if (au !== bu) return bu.localeCompare(au);
  return (a.id || "").localeCompare(b.id || "");
}

export function mergeThreads(prev: Thread[], deltas: Thread[]): Thread[] {
  if (!deltas.length) return prev;
  const byId = new Map(prev.map((t) => [t.id, t]));
  for (const d of deltas) {
    const existing = byId.get(d.id);
    byId.set(d.id, existing ? mergeThread(existing, d) : d);
  }
  return Array.from(byId.values()).sort(compareThreads);
}

export async function fetchConversations(opts?: {
  updatedAfter?: string | null;
}): Promise<Thread[]> {
  const q =
    opts?.updatedAfter != null && opts.updatedAfter !== ""
      ? `?updatedAfter=${encodeURIComponent(opts.updatedAfter)}`
      : "";
  return apiGet<Thread[]>(`/conversations${q}`);
}

export async function fetchConversation(threadId: string): Promise<Thread> {
  return apiGet<Thread>(`/conversations/${encodeURIComponent(threadId)}`);
}

/** The one thread on screen, with its customer context. */
export function useConversation(threadId: string | null | undefined) {
  return useQuery({
    queryKey: ["conversation", threadId],
    queryFn: () => fetchConversation(threadId as string),
    enabled: Boolean(threadId),
    retry: retryUnlessClientError,
  });
}

export function useConversations() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["conversations"],
    queryFn: async () => {
      conversationPollCount += 1;
      const prev = queryClient.getQueryData<Thread[]>(["conversations"]);
      // Full list on first fetch and every ~15th poll (~60s at 4s interval).
      if (!prev || conversationPollCount === 1 || conversationPollCount % 15 === 0) {
        return fetchConversations();
      }
      const after = maxUpdatedAt(prev);
      if (!after) return fetchConversations();
      const deltas = await fetchConversations({ updatedAfter: after });
      return mergeThreads(prev, deltas);
    },
    staleTime: 2_000,
    // The global default retries every failure once, including the 4xx that
    // will fail identically on the retry. A malformed `updatedAfter` is a
    // client bug, not a blip.
    retry: retryUnlessClientError,
    refetchInterval: (q) => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        return false;
      }
      const rows = q.state.data;
      if (Array.isArray(rows) && rows.some((t) => t?.botTyping || t?.pendingOutbound)) {
        return 1_500;
      }
      return 4_000;
    },
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

export async function takeoverConversation(threadId: string): Promise<Thread> {
  return apiPost<Thread>(`/conversations/${threadId}/takeover`, {});
}

export async function returnConversationToBot(threadId: string): Promise<Thread> {
  return apiPost<Thread>(`/conversations/${threadId}/return-to-bot`, {});
}

export async function sendConversationMessage(threadId: string, text: string): Promise<Thread> {
  return apiPost<Thread>(`/conversations/${threadId}/messages`, { text });
}

export interface ConversationSuggestionsRefreshResult {
  conversationId: string;
  ragSuggestions: string[];
  draftAnswer?: string | null;
  chatModel?: string | null;
  latencyMs?: number | null;
  logId?: string | null;
  thread?: Thread | null;
}

/** Debounced Inbox RAG — shared retrieve() → ai_response_suggestions chips (+ optional draft). */
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

export async function ingestInboxDocument(
  customerId: string,
  file: File,
  conversationId?: string,
): Promise<{ documentRequestId?: string; source?: string }> {
  const form = new FormData();
  form.append("customer_id", customerId);
  form.append("file", file);
  if (conversationId) form.append("conversation_id", conversationId);
  return apiUpload("/document-requests/ingest", form);
}
