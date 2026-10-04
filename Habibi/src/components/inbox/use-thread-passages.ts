import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { SuggestedReply } from "@/components/inbox/Composer";
import { inboxErrorWords } from "@/components/inbox/inbox-words";
import { fetchConversation, refreshConversationSuggestions } from "@/api/inbox";
import type { Thread } from "@/api/types/inbox";

/** The customer message the thread is answering now: its latest. */
export function latestCustomerMessageId(thread: Thread | undefined): string {
  if (!thread) return "";
  for (let i = (thread.messages?.length ?? 0) - 1; i >= 0; i--) {
    const m = thread.messages?.[i];
    if (m && "sender" in m && m.sender === "customer") return m.id;
  }
  return "";
}

type Rag = {
  threadId: string | null;
  loading: boolean;
  error: string | null;
  stale: boolean;
  suggestions: string[] | null;
  /** The customer message the passages answer. */
  answers: string | null;
};

const NO_RAG: Rag = {
  threadId: null,
  loading: false,
  error: null,
  stale: false,
  suggestions: null,
  answers: null,
};

/**
 * The knowledge-base passages for the open thread: this page's own search,
 * else what the thread's last search stored, and whether they still answer
 * the customer. `canSearch`: the search is a write, so only someone who could
 * use it runs one -- a read-only viewer's every open thread drew a permission
 * error.
 */
export function useThreadPassages(thread: Thread | undefined, canSearch: boolean) {
  const queryClient = useQueryClient();
  const [rag, setRag] = useState<Rag>(NO_RAG);
  const ragToken = useRef(0);
  const ragFor = rag.threadId === thread?.id ? rag : NO_RAG;

  /** Search the knowledge base for this thread's latest customer message. */
  const refresh = async (threadId: string, withDraft: boolean): Promise<SuggestedReply> => {
    // Only the newest request for the still-open thread may touch the panel:
    // retrieval is slow enough that switching mid-flight was routine.
    const token = ++ragToken.current;
    const current = () => token === ragToken.current;
    setRag((r) => ({
      ...(r.threadId === threadId ? r : NO_RAG),
      threadId,
      loading: true,
      error: null,
    }));
    try {
      const res = await refreshConversationSuggestions(threadId, {
        topK: 4,
        includeDraftAnswer: withDraft,
      });
      // The customer wrote again while it searched: these answer an older
      // message, and the newer one's own search replaces them.
      if (res.superseded) {
        if (current()) setRag((r) => ({ ...r, loading: false }));
        return withDraft ? { kind: "superseded" } : { kind: "none" };
      }
      if (current()) {
        setRag({
          threadId,
          loading: false,
          error: null,
          stale: Boolean(res.stale),
          suggestions: res.ragSuggestions ?? [],
          answers: res.answersMessageId ?? null,
        });
      }
      if (!withDraft) return { kind: "none" };
      if (res.stale) return { kind: "failed" };
      if (res.draftFailed) return { kind: "failed" };
      if (!res.draftAnswer) return { kind: "none" };
      // Drafting takes seconds; the customer may have written again. Read
      // the thread now and offer the draft only if it still answers them.
      // A read that fails is no answer: the cache it would have fallen back
      // on is exactly the old thread this check exists to doubt.
      const now = await queryClient.fetchQuery({
        queryKey: ["conversation", threadId],
        queryFn: () => fetchConversation(threadId),
        staleTime: 0,
        retry: false,
      });
      if (res.answersMessageId !== latestCustomerMessageId(now)) return { kind: "superseded" };
      return { kind: "draft", text: res.draftAnswer };
    } catch (err) {
      if (current()) {
        setRag((r) => ({
          ...r,
          loading: false,
          error: inboxErrorWords(err, thread?.channel ?? "whatsapp"),
        }));
      }
      return { kind: "failed" };
    }
  };

  // A new customer message asks for new passages. Debounced, keyed on that
  // message.
  const answering = latestCustomerMessageId(thread);
  // This page's own search, else what the thread's last search stored. Both
  // judged against the thread on screen, not when they arrived: a search
  // answering an earlier message can land after the next one has, and stored
  // passages stop fitting the moment the customer writes again -- for a
  // viewer who never searches, indefinitely.
  const passages =
    ragFor.suggestions !== null
      ? { list: ragFor.suggestions, answers: ragFor.answers, failed: ragFor.stale }
      : {
          list: thread?.ragSuggestions ?? [],
          answers: thread?.ragAnswersMessageId ?? null,
          failed: false,
        };
  // No link at all is not "the customer wrote since": passages stored before
  // searches recorded it, or inherited from the interaction (a voice call's),
  // answer nothing we can name -- in a thread with no customer message too.
  const stale =
    passages.list.length === 0
      ? null
      : passages.answers === null
        ? "unlinked"
        : passages.answers !== answering
          ? "customer_wrote"
          : passages.failed
            ? "search_failed"
            : null;
  useEffect(() => {
    if (!thread?.id || !answering || !canSearch) return;
    const timer = setTimeout(() => void refresh(thread.id, false), 500);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the thread and its last customer turn
  }, [thread?.id, answering, canSearch]);

  return {
    refresh,
    list: passages.list,
    loading: ragFor.loading,
    error: ragFor.error,
    stale,
    searched: ragFor.suggestions !== null || !canSearch,
  } as const;
}
