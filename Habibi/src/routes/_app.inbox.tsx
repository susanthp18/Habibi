import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { ConversationList } from "@/components/inbox/ConversationList";
import { ChatThread } from "@/components/inbox/ChatThread";
import { Composer } from "@/components/inbox/Composer";
import { ContextRail } from "@/components/inbox/ContextRail";
import { inboxErrorWords } from "@/components/inbox/inbox-words";
import { QueryState, QueryErrorBanner } from "@/components/ui/query-state";
import { SplitPanes } from "@/components/shared/SplitPanes";
import {
  applyThread,
  refreshConversationSuggestions,
  returnConversationToBot,
  sendConversationMessage,
  takeoverConversation,
  useConversation,
  useConversations,
} from "@/api/inbox";
import { can, useMe } from "@/api/me";
import { isNotFound } from "@/api/config";
import type { Thread } from "@/api/types/inbox";
import type { InboxRights } from "@/components/inbox/meta";
import { LoadingState } from "@/components/ui/loading-state";
import { useConfirm } from "@/components/ui/use-confirm";
import { useDebounced } from "@/lib/use-debounced";

export type InboxSearch = {
  conversationId?: string;
};

export const Route = createFileRoute("/_app/inbox")({
  validateSearch: (search: Record<string, unknown>): InboxSearch => ({
    conversationId: typeof search.conversationId === "string" ? search.conversationId : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Conversation Inbox — PayInt" },
      {
        name: "description",
        content:
          "Omnichannel text inbox — monitor bot conversations, take over on WhatsApp/SMS, and resolve with knowledge-base suggested replies.",
      },
    ],
  }),
  component: InboxPage,
});

function lastCustomerFingerprint(thread: Thread | undefined): string {
  if (!thread) return "";
  for (let i = (thread.messages?.length ?? 0) - 1; i >= 0; i--) {
    const m = thread.messages?.[i];
    if (m && "sender" in m && m.sender === "customer") return `${m.id}`;
  }
  return "";
}

/** The query's answer on first render, so a laptop never mounts in the wrong layout and then jumps. */
function useMedia(query: string) {
  const [matches, setMatches] = useState(() =>
    typeof window === "undefined" ? true : window.matchMedia(query).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia(query);
    const apply = () => setMatches(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [query]);
  return matches;
}

type Rag = {
  threadId: string | null;
  loading: boolean;
  error: string | null;
  stale: boolean;
  suggestions: string[] | null;
};

const NO_RAG: Rag = {
  threadId: null,
  loading: false,
  error: null,
  stale: false,
  suggestions: null,
};

function InboxPage() {
  const queryClient = useQueryClient();
  const { confirm, confirmDialog } = useConfirm();
  const navigate = useNavigate({ from: "/inbox" });
  const { conversationId: activeId } = Route.useSearch();
  const { data: me } = useMe();
  const rights: InboxRights = {
    canWrite: can(me, "perm-interactions-write"),
    canReassign: can(me, "perm-supervisor-write"),
    canFileDocuments: can(me, "perm-collections-write"),
  };

  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  // `isPending`, not `isLoading`: they differ exactly when the fetch is paused
  // (tab hidden, browser offline), and then "No conversations yet." would be
  // a claim about an inbox nobody had managed to read.
  const list = useConversations(q);
  const threads = useMemo(() => list.data ?? [], [list.data]);
  const detail = useConversation(activeId);
  const thread = detail.data;

  const wideLayout = useMedia("(min-width: 1440px)");
  const narrow = !useMedia("(min-width: 768px)");
  const railUserToggled = useRef(false);
  const [railOpen, setRailOpen] = useState(wideLayout);
  // Per thread, so a send still in flight on one conversation neither blocks
  // nor reports its failure on the next one the operator opens.
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [errors, setErrors] = useState<Record<string, string>>({});
  const drafts = useRef(new Map<string, string>());
  const [rag, setRag] = useState<Rag>(NO_RAG);
  const ragToken = useRef(0);

  useEffect(() => {
    if (!railUserToggled.current) setRailOpen(wideLayout);
  }, [wideLayout]);

  // Landing on the inbox opens the newest thread, and the URL says which, so
  // the address can be copied. Replace, not push: it is not a step the
  // operator took.
  useEffect(() => {
    const first = threads[0];
    if (!activeId && first && !q && !narrow) {
      void navigate({ search: { conversationId: first.id }, replace: true });
    }
  }, [threads, activeId, q, narrow, navigate]);

  const select = (id: string) => {
    // A step the operator took: Back returns to the previous thread.
    if (id !== activeId) void navigate({ search: { conversationId: id } });
  };

  const setThreadBusy = (id: string, on: boolean) =>
    setBusy((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  const setThreadError = (id: string, message: string | null) =>
    setErrors((prev) => {
      const next = { ...prev };
      if (message) next[id] = message;
      else delete next[id];
      return next;
    });

  /** One write on one thread: busy while it runs, its answer into both caches, its failure on that thread. */
  const write = async (target: Thread, run: () => Promise<Thread>): Promise<boolean> => {
    if (busy.has(target.id)) return false;
    setThreadBusy(target.id, true);
    setThreadError(target.id, null);
    try {
      applyThread(queryClient, await run());
      return true;
    } catch (err) {
      setThreadError(target.id, inboxErrorWords(err, target.channel));
      // The refusal may be because the thread moved on: read it again.
      void queryClient.invalidateQueries({ queryKey: ["conversation", target.id] });
      return false;
    } finally {
      setThreadBusy(target.id, false);
    }
  };

  const ragFor = rag.threadId === thread?.id ? rag : NO_RAG;

  /** Search the knowledge base for this thread. Resolves to the drafted reply, when one was asked for. */
  const refreshRag = async (threadId: string, withDraft: boolean): Promise<string | null> => {
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
      if (current()) {
        setRag({
          threadId,
          loading: false,
          error: null,
          stale: Boolean(res.stale),
          suggestions: res.ragSuggestions ?? [],
        });
      }
      return withDraft && !res.stale ? (res.draftAnswer ?? null) : null;
    } catch (err) {
      if (current()) {
        setRag((r) => ({
          ...r,
          loading: false,
          error: inboxErrorWords(err, thread?.channel ?? "whatsapp"),
        }));
      }
      return null;
    }
  };

  // A new customer message asks for new passages. Debounced, keyed on that message.
  const fingerprint = lastCustomerFingerprint(thread);
  useEffect(() => {
    if (!thread?.id || !fingerprint) return;
    const timer = setTimeout(() => void refreshRag(thread.id, false), 500);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the thread and its last customer turn
  }, [thread?.id, fingerprint]);

  const handleTakeOver = async () => {
    if (!thread) return;
    if (!thread.isMine && thread.status === "assigned") {
      const ok = await confirm({
        title: "Take over from another agent?",
        description: `${thread.customer}'s conversation is assigned to a colleague. Taking over reassigns it to you, and they will not be able to reply until you hand it back.`,
        confirmLabel: "Take over anyway",
        cancelLabel: "Leave it with them",
      });
      if (!ok) return;
    }
    // Conditional on the holder this screen showed: if someone else got there
    // first, the server refuses rather than silently overwriting them.
    await write(thread, () => takeoverConversation(thread.id, thread.assignedUserId ?? null));
  };

  const handleReturnToBot = async () => {
    if (thread) await write(thread, () => returnConversationToBot(thread.id));
  };

  const handleSend = async (text: string, idempotencyKey: string) => {
    if (!thread) return false;
    return write(thread, () => sendConversationMessage(thread.id, text, idempotencyKey));
  };

  const toggleRail = () => {
    railUserToggled.current = true;
    setRailOpen((o) => !o);
  };
  const closeRail = () => {
    railUserToggled.current = true;
    setRailOpen(false);
  };

  const dockedRail = railOpen && wideLayout && !narrow;
  const overlayRail = railOpen && !dockedRail;

  // The overlay covers the thread, so Escape closes it.
  useEffect(() => {
    if (!overlayRail) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeRail();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [overlayRail]);

  // An error with nothing behind it is fatal; an error with cached rows is a
  // stale-data warning -- one failed poll must not replace a working inbox.
  const fatalError = list.isError && threads.length === 0 && !q;
  const staleWarning = list.isError && threads.length > 0;
  const deadLink = Boolean(activeId) && isNotFound(detail.error);

  const rail = thread ? (
    <QueryState query={detail} label="customer context">
      <ContextRail thread={thread} context={thread.context} onClose={closeRail} />
    </QueryState>
  ) : null;

  const listPane = (
    <ConversationList
      key="list"
      threads={threads}
      activeId={activeId ?? null}
      onSelect={select}
      search={search}
      onSearchChange={setSearch}
      searching={search.trim() !== q.trim() || (Boolean(q) && list.isFetching)}
      searchFailed={Boolean(q) && list.isError}
    />
  );

  const threadPane = (
    <div key="chat" className="relative flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
      {narrow && (
        <button
          type="button"
          onClick={() => void navigate({ search: {} })}
          className="focus-ring flex shrink-0 items-center gap-075 border-b border-border px-200 py-100 text-body-small font-medium text-text-subtle"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> All conversations
        </button>
      )}
      {deadLink ? (
        <div className="grid flex-1 place-items-center px-300 text-center">
          <div className="max-w-[28rem]">
            <p className="text-body font-semibold text-text">No conversation with this id</p>
            <p className="mt-075 text-body-small text-text-subtle">
              Nothing in this inbox is registered as “{activeId}”. It may have been deleted, or
              belong to another tenant.
            </p>
            {threads[0] && (
              <button
                type="button"
                onClick={() => select(threads[0]!.id)}
                className="focus-ring mt-150 inline-flex h-400 items-center rounded-medium bg-background-brand-bold px-150 text-body font-medium text-text-inverse hover:bg-background-brand-bold-hovered"
              >
                Open the most recent conversation
              </button>
            )}
          </div>
        </div>
      ) : thread ? (
        <>
          <ChatThread
            thread={thread}
            rights={rights}
            onToggleRail={toggleRail}
            railOpen={railOpen}
            onTakeOver={() => void handleTakeOver()}
            onReturnToBot={() => void handleReturnToBot()}
            busy={busy.has(thread.id)}
          />
          <Composer
            key={thread.id}
            thread={thread}
            rights={rights}
            draft={drafts.current.get(thread.id) ?? ""}
            onDraftChange={(text) => {
              if (text) drafts.current.set(thread.id, text);
              else drafts.current.delete(thread.id);
            }}
            onSend={handleSend}
            onRefreshRag={() => void refreshRag(thread.id, false)}
            onSuggestReply={() => refreshRag(thread.id, true)}
            ragSuggestions={ragFor.suggestions ?? thread.ragSuggestions ?? []}
            ragDraft={thread.ragDraftAnswer ?? null}
            ragLoading={ragFor.loading}
            ragError={ragFor.error}
            ragStale={ragFor.stale}
            ragSearched={ragFor.suggestions !== null}
            busy={busy.has(thread.id)}
            errorMessage={errors[thread.id] ?? null}
          />
          {overlayRail && (
            <>
              <button
                type="button"
                aria-label="Close customer context"
                onClick={closeRail}
                className="absolute inset-0 z-10 bg-background-neutral-bold/20"
              />
              <div
                role="dialog"
                aria-label="Customer context"
                className="absolute inset-y-0 right-0 z-20 flex w-[20rem] max-w-[85%] flex-col border-l border-border bg-surface shadow-overlay"
              >
                {rail}
              </div>
            </>
          )}
        </>
      ) : detail.isError ? (
        <div className="grid flex-1 place-items-center p-400">
          <QueryErrorBanner label="this conversation" error={detail.error} />
        </div>
      ) : activeId ? (
        <div className="grid flex-1 place-items-center">
          <LoadingState label="Loading conversation" />
        </div>
      ) : (
        <div className="grid flex-1 place-items-center text-body text-text-subtle">
          Select a conversation.
        </div>
      )}
    </div>
  );

  return (
    <>
      <div className="flex h-full min-h-0 w-full flex-col overflow-hidden">
        {staleWarning && (
          <div
            role="status"
            className="shrink-0 border-b border-border-warning-subtle bg-background-warning-subtler px-250 py-075 text-body-small text-text-warning-bolder"
          >
            Live updates interrupted. Showing the last state received — new messages may be missing.
          </div>
        )}
        <div className="flex min-h-0 w-full flex-1 overflow-hidden">
          {list.isPending && !list.isError && !q ? (
            <div className="grid flex-1 place-items-center">
              <LoadingState
                label={
                  list.fetchStatus === "paused" ? "Waiting to reconnect" : "Loading conversations"
                }
              />
            </div>
          ) : fatalError ? (
            <div className="grid flex-1 place-items-center p-400">
              <QueryErrorBanner label="the inbox" error={list.error} />
            </div>
          ) : !threads.length && !q && !activeId ? (
            <div className="grid flex-1 place-items-center text-body text-text-subtle">
              No conversations yet.
            </div>
          ) : narrow ? (
            activeId ? (
              threadPane
            ) : (
              listPane
            )
          ) : (
            <SplitPanes
              storageKey={dockedRail ? "bigbound.inbox.split.3" : "bigbound.inbox.split.2"}
              defaultWidths={dockedRail ? [20, 58, 22] : [24, 76]}
              minWidthsPx={dockedRail ? [240, 420, 280] : [240, 420]}
              paneLabels={["conversation list", "conversation", "customer context"]}
            >
              {[
                listPane,
                threadPane,
                dockedRail ? (
                  <div key="rail" className="h-full min-h-0 border-l border-border">
                    {rail}
                  </div>
                ) : null,
              ]}
            </SplitPanes>
          )}
        </div>
      </div>
      {confirmDialog}
    </>
  );
}
