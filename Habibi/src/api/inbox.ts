// -----------------------------------------------------------------------------
// Conversation Inbox — data access seam.
//   fetchConversations() → list          (GET /conversations)
//   takeover / send message              → POST writes
//   fetchCannedResponses()               (GET /canned-responses)
//
// Mock branch preserves the in-memory seed. Live branch maps to the Phase 3B
// endpoints; callers invalidate + refetch rather than trusting partial bodies.
// "Mine" is derived server-side (assignedUserId === GET /me).
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  cannedResponses as seedCanned,
  threads as seedThreads,
  type Thread,
} from "@/data/inbox-seed";
import { apiGet, apiPost, mockDelay, USE_MOCK } from "./config";

export type CannedResponse = { id: string; label: string; text: string };

export async function fetchConversations(): Promise<Thread[]> {
  if (USE_MOCK) return mockDelay(structuredClone(seedThreads));
  return apiGet<Thread[]>("/conversations");
}

export function useConversations() {
  return useQuery({
    queryKey: ["conversations"],
    queryFn: fetchConversations,
    staleTime: 10_000,
  });
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
    const now = new Date();
    const h = now.getHours();
    const m = now.getMinutes().toString().padStart(2, "0");
    const ampm = h >= 12 ? "PM" : "AM";
    const hh = ((h + 11) % 12) + 1;
    const time = `${hh}:${m} ${ampm}`;
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

export async function sendConversationMessage(
  threadId: string,
  text: string,
): Promise<Thread> {
  if (USE_MOCK) {
    const thread = seedThreads.find((t) => t.id === threadId);
    if (!thread) throw new Error("conversation_not_found");
    const now = new Date();
    const h = now.getHours();
    const m = now.getMinutes().toString().padStart(2, "0");
    const ampm = h >= 12 ? "PM" : "AM";
    const hh = ((h + 11) % 12) + 1;
    const time = `${hh}:${m} ${ampm}`;
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
