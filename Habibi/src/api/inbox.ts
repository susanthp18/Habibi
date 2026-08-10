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

import {
  cannedResponses as seedCanned,
  threads as seedThreads,
  type Thread,
} from "@/data/inbox-seed";
import { apiGet, apiPost, mockDelay, USE_MOCK } from "./config";

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

function mergeThreads(prev: Thread[], deltas: Thread[]): Thread[] {
  if (!deltas.length) return prev;
  const byId = new Map(prev.map((t) => [t.id, t]));
  for (const d of deltas) {
    const existing = byId.get(d.id);
    byId.set(d.id, existing ? mergeThread(existing, d) : d);
  }
  return Array.from(byId.values()).sort((a, b) => {
    const au = a.updatedAt || "";
    const bu = b.updatedAt || "";
    if (au !== bu) return bu.localeCompare(au);
    return (b.lastTime || "").localeCompare(a.lastTime || "");
  });
}

export async function fetchConversations(opts?: {
  updatedAfter?: string | null;
}): Promise<Thread[]> {
  if (USE_MOCK) return mockDelay(structuredClone(seedThreads));
  const q =
    opts?.updatedAfter != null && opts.updatedAfter !== ""
      ? `?updatedAfter=${encodeURIComponent(opts.updatedAfter)}`
      : "";
  return apiGet<Thread[]>(`/conversations${q}`);
}

export function useConversations() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["conversations"],
    queryFn: async () => {
      if (USE_MOCK) return fetchConversations();
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
    refetchInterval: (q) => {
      if (USE_MOCK) return false;
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        return false;
      }
      const rows = q.state.data;
      if (
        Array.isArray(rows) &&
        rows.some((t) => t?.botTyping || t?.pendingOutbound)
      ) {
        return 1_500;
      }
      return 4_000;
    },
    refetchOnWindowFocus: true,
  });

  // Resume polling immediately when the tab becomes visible again.
  useEffect(() => {
    if (USE_MOCK) return;
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
  if (USE_MOCK) return mockDelay(seedCanned);
  return apiGet<CannedResponse[]>("/canned-responses");
}

export function useCannedResponses() {
  return useQuery({
    queryKey: ["canned-responses"],
    queryFn: fetchCannedResponses,
    staleTime: 5 * 60_000,
  });
}

export async function takeoverConversation(threadId: string): Promise<Thread> {
  if (USE_MOCK) {
    const thread = seedThreads.find((t) => t.id === threadId);
    if (!thread) throw new Error("conversation_not_found");
    thread.status = "assigned";
    thread.assignedUserId = "priya-nair";
    thread.isMine = true;
    const time = formatNowLabel();
    thread.messages.push({
      id: `sys-${Date.now()}`,
      kind: "system",
      text: "You took over from bot",
      time,
    });
    return structuredClone(thread);
  }
  return apiPost<Thread>(`/conversations/${threadId}/takeover`, {});
}

export async function returnConversationToBot(threadId: string): Promise<Thread> {
  if (USE_MOCK) {
    const thread = seedThreads.find((t) => t.id === threadId);
    if (!thread) throw new Error("conversation_not_found");
    thread.status = "bot";
    thread.assignedUserId = null;
    thread.isMine = false;
    const time = formatNowLabel();
    thread.messages.push({
      id: `sys-${Date.now()}`,
      kind: "system",
      text: "Returned conversation to bot",
      time,
    });
    return structuredClone(thread);
  }
  return apiPost<Thread>(`/conversations/${threadId}/return-to-bot`, {});
}

export async function sendConversationMessage(
  threadId: string,
  text: string,
): Promise<Thread> {
  if (USE_MOCK) {
    const thread = seedThreads.find((t) => t.id === threadId);
    if (!thread) throw new Error("conversation_not_found");
    const time = formatNowLabel();
    thread.messages.push({
      id: `m-${Date.now()}`,
      sender: "agent",
      text,
      time,
      delivery: "sent",
    });
    thread.lastPreview = text;
    thread.lastFrom = "agent";
    thread.lastTime = time;
    thread.unread = 0;
    thread.status = "assigned";
    thread.assignedUserId = "priya-nair";
    thread.isMine = true;
    return structuredClone(thread);
  }
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
  if (USE_MOCK) {
    const thread = seedThreads.find((t) => t.id === threadId);
    const chips = thread?.ragSuggestions?.length
      ? thread.ragSuggestions
      : ["Mock KB: NCD protector preserves bonus on windscreen claims."];
    const includeDraft = opts.includeDraftAnswer ?? false;
    const draftAnswer = includeDraft
      ? "Mock draft: NCD Protector keeps your no-claim bonus if you claim for windscreen damage only (see Motor policy)."
      : null;
    if (thread) {
      thread.ragSuggestions = chips;
      thread.ragDraftAnswer = draftAnswer;
    }
    return mockDelay(
      {
        conversationId: threadId,
        ragSuggestions: chips,
        draftAnswer,
        chatModel: includeDraft ? "mock-chat" : null,
        latencyMs: 120,
        logId: `mock-${Date.now()}`,
        thread: thread ? structuredClone(thread) : null,
      },
      400,
    );
  }
  return apiPost<ConversationSuggestionsRefreshResult>(
    `/conversations/${threadId}/suggestions/refresh`,
    {
      topK: opts.topK ?? 4,
      includeDraftAnswer: opts.includeDraftAnswer ?? false,
    },
  );
}
