import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { ConversationList, type Filter } from "@/components/inbox/ConversationList";
import { ChatThread } from "@/components/inbox/ChatThread";
import { Composer, type SuggestedReply } from "@/components/inbox/Composer";
import { ContextRail } from "@/components/inbox/ContextRail";
import { inboxErrorWords } from "@/components/inbox/inbox-words";
import { QueryState, QueryErrorBanner } from "@/components/ui/query-state";
import { SplitPanes } from "@/components/shared/SplitPanes";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import {
  applyThread,
  fetchConversation,
  refreshConversationSuggestions,
  returnConversationToBot,
  sendConversationMessage,
  takeoverConversation,
  useConversation,
  useConversationCounts,
  useConversations,
  useOlderConversations,
} from "@/api/inbox";
import { can, useMe } from "@/api/me";
import { isNotFound } from "@/api/config";
import type { Thread } from "@/api/types/inbox";
import { getThreadHandoffState, type InboxRights } from "@/components/inbox/meta";
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

/** The customer message the thread is answering now: its latest. */
function latestCustomerMessageId(thread: Thread | undefined): string {
  if (!thread) return "";
  for (let i = (thread.messages?.length ?? 0) - 1; i >= 0; i--) {
    const m = thread.messages?.[i];
    if (m && "sender" in m && m.sender === "customer") return m.id;
  }
  return "";
}

/**
 * Pixels the inbox itself has, not the viewport's: the app sidebar takes its
 * share, so a viewport query put two panes needing 660px into less than that.
 * Measured before paint, so the first frame is already the right layout.
 */
function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(() =>
    typeof window === "undefined" ? 1280 : window.innerWidth,
  );
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.getBoundingClientRect().width);
    const ro = new ResizeObserver(([entry]) => {
      if (entry) setWidth(entry.contentRect.width);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

/** Below this, list and thread don't both fit (240 + 420 + separator). */
const TWO_PANES_PX = 680;
/** From this, the customer context docks beside them (240 + 420 + 280 + separators). */
const DOCKED_RAIL_PX = 1180;

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

/** One attempt at one reply: a resend of the same text reuses its key. */
type Attempt = { text: string; key: string };

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
  const [filter, setFilter] = useState<Filter>("all");
  const q = useDebounced(search);
  const view = filter === "all" ? undefined : filter;
  // `isPending`, not `isLoading`: they differ exactly when the fetch is paused
  // (tab hidden, browser offline), and then "No conversations yet." would be
  // a claim about an inbox nobody had managed to read.
  const list = useConversations(q, view);
  const older = useOlderConversations(q, view);
  const counts = useConversationCounts();
  const threads = useMemo(() => list.data?.rows ?? [], [list.data]);
  const detail = useConversation(activeId);
  const thread = detail.data;

  const [paneRef, width] = useWidth();
  const narrow = width < TWO_PANES_PX;
  const canDock = width >= DOCKED_RAIL_PX;
  const railUserToggled = useRef(false);
  const [railOpen, setRailOpen] = useState(canDock);
  // Per thread, so a send still in flight on one conversation neither blocks
  // nor reports its failure on the next one the operator opens.
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [errors, setErrors] = useState<Record<string, string>>({});
  // Each thread's unsent reply and its send attempt live here, not in the
  // composer: switching threads unmounts the composer, and an attempt's key
  // lost with it turned a retry after a lost response into a second message.
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const attempts = useRef(new Map<string, Attempt>());
  const [rag, setRag] = useState<Rag>(NO_RAG);
  const ragToken = useRef(0);
  // What had focus when the overlay rail opened: it gets it back on close.
  const railOpener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!railUserToggled.current) setRailOpen(canDock);
  }, [canDock]);

  // Landing on the inbox opens the newest thread, and the URL says which, so
  // the address can be copied. Replace, not push: it is not a step the
  // operator took.
  useEffect(() => {
    const first = threads[0];
    if (!activeId && first && !q && !view && !narrow) {
      void navigate({ search: { conversationId: first.id }, replace: true });
    }
  }, [threads, activeId, q, view, narrow, navigate]);

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

  /** One write on one thread: busy while it runs, its answer into the caches, its failure on that thread. */
  const write = async (target: Thread, run: () => Promise<Thread>): Promise<unknown> => {
    if (busy.has(target.id)) return new Error("busy");
    setThreadBusy(target.id, true);
    setThreadError(target.id, null);
    try {
      applyThread(queryClient, await run());
      return null;
    } catch (err) {
      setThreadError(target.id, inboxErrorWords(err, target.channel));
      // The refusal may be because the thread moved on: read it again.
      void queryClient.invalidateQueries({ queryKey: ["conversation", target.id] });
      return err;
    } finally {
      setThreadBusy(target.id, false);
    }
  };

  const ragFor = rag.threadId === thread?.id ? rag : NO_RAG;

  /** Search the knowledge base for this thread's latest customer message. */
  const refreshRag = async (threadId: string, withDraft: boolean): Promise<SuggestedReply> => {
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
  // message. Only for someone who could use them: the search is a write, and a
  // read-only viewer's every open thread drew a permission error.
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
  const ragStale =
    passages.list.length === 0
      ? null
      : passages.answers !== answering
        ? "customer_wrote"
        : passages.failed
          ? "search_failed"
          : null;
  useEffect(() => {
    if (!thread?.id || !answering || !rights.canWrite) return;
    const timer = setTimeout(() => void refreshRag(thread.id, false), 500);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the thread and its last customer turn
  }, [thread?.id, answering, rights.canWrite]);

  const handleTakeOver = async () => {
    if (!thread) return;
    if (getThreadHandoffState(thread, rights).heldByTeammate) {
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

  const handleSend = async (text: string): Promise<boolean> => {
    if (!thread) return false;
    const id = thread.id;
    let attempt = attempts.current.get(id);
    if (attempt?.text !== text) {
      attempt = { text, key: crypto.randomUUID() };
      attempts.current.set(id, attempt);
    }
    const key = attempt.key;
    const err = await write(thread, () => sendConversationMessage(id, text, key));
    // The key goes only with a success. A failure -- even a 4xx -- does not
    // settle an earlier attempt whose answer was lost: a 429 on the retry
    // says nothing of whether the first one queued, and a new key would let
    // it queue twice. Keeping it costs nothing: the server replays only a
    // key that succeeded.
    if (!err) attempts.current.delete(id);
    if (err) return false;
    // Only the text that went: anything typed while it was sending stays.
    setDrafts((d) => {
      if ((d[id] ?? "").trim() !== text) return d;
      const { [id]: _sent, ...rest } = d;
      return rest;
    });
    return true;
  };

  const toggleRail = () => {
    railUserToggled.current = true;
    if (!railOpen) railOpener.current = document.activeElement as HTMLElement | null;
    setRailOpen((o) => !o);
  };
  const closeRail = () => {
    railUserToggled.current = true;
    setRailOpen(false);
  };

  const dockedRail = railOpen && canDock && !narrow;
  const overlayRail = railOpen && !dockedRail;

  // An error with nothing behind it is fatal; an error with cached rows is a
  // stale-data warning -- one failed poll must not replace a working inbox.
  const filtered = Boolean(q || view);
  const fatalError = list.isError && threads.length === 0 && !filtered;
  const staleWarning = list.isError && threads.length > 0;
  const deadLink = Boolean(activeId) && isNotFound(detail.error);
  // The open thread polls on its own; when that fails, say so beside the
  // transcript -- the list's warning and the rail (often closed) didn't.
  const threadStale = Boolean(thread) && detail.isError && !deadLink;

  const rail = thread ? (
    <QueryState query={detail} label="customer context">
      <ContextRail
        thread={thread}
        context={thread.context}
        onClose={closeRail}
        canFileRecords={rights.canFileDocuments}
      />
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
      searching={search.trim() !== q.trim() || (filtered && (list.isPending || list.isFetching))}
      searchFailed={filtered && list.isError}
      filter={filter}
      onFilterChange={setFilter}
      counts={counts.data}
      more={Boolean(list.data?.more)}
      onLoadOlder={() => void older.load()}
      loadingOlder={older.loading}
      olderFailed={older.failed}
      empty={!filtered ? "No conversations yet." : "No conversations match."}
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
            <div className="mt-150 flex flex-wrap justify-center gap-100">
              {threads[0] && (
                <button
                  type="button"
                  onClick={() => select(threads[0]!.id)}
                  className="focus-ring inline-flex h-400 items-center rounded-medium bg-background-brand-bold px-150 text-body font-medium text-text-inverse hover:bg-background-brand-bold-hovered"
                >
                  Open the most recent conversation
                </button>
              )}
              <button
                type="button"
                onClick={() => void navigate({ search: {} })}
                className="focus-ring inline-flex h-400 items-center rounded-medium border border-border px-150 text-body font-medium text-text hover:bg-surface-sunken"
              >
                View all conversations
              </button>
            </div>
          </div>
        </div>
      ) : thread ? (
        <>
          {threadStale && (
            <div
              role="status"
              className="shrink-0 border-b border-border-warning-subtle bg-background-warning-subtler px-250 py-075 text-body-small text-text-warning-bolder"
            >
              Couldn’t refresh this conversation. Showing what was last received — new messages may
              be missing.
            </div>
          )}
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
            draft={drafts[thread.id] ?? ""}
            onDraftChange={(next) =>
              setDrafts((d) => ({
                ...d,
                [thread.id]: typeof next === "function" ? next(d[thread.id] ?? "") : next,
              }))
            }
            onSend={handleSend}
            onRefreshRag={() => void refreshRag(thread.id, false)}
            onSuggestReply={() => refreshRag(thread.id, true)}
            ragSuggestions={passages.list}
            ragLoading={ragFor.loading}
            ragError={ragFor.error}
            ragStale={ragStale}
            ragSearched={ragFor.suggestions !== null || !rights.canWrite}
            busy={busy.has(thread.id)}
            errorMessage={errors[thread.id] ?? null}
          />
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
      <div ref={paneRef} className="flex h-full min-h-0 w-full flex-col overflow-hidden">
        {staleWarning && (
          <div
            role="status"
            className="shrink-0 border-b border-border-warning-subtle bg-background-warning-subtler px-250 py-075 text-body-small text-text-warning-bolder"
          >
            Live updates interrupted. Showing the last state received — new messages may be missing.
          </div>
        )}
        <div className="flex min-h-0 w-full flex-1 overflow-hidden">
          {list.isPending && !list.isError && !filtered ? (
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
      {/* A dialog when it covers the thread: focus moves into it and stays in
          it. Radix returns focus to its own trigger, and the button that opens
          this lives in the thread header, outside the Sheet -- so it is given
          back here. */}
      <Sheet open={overlayRail && Boolean(thread)} onOpenChange={(open) => !open && closeRail()}>
        <SheetContent
          side="right"
          hideClose
          aria-describedby={undefined}
          onCloseAutoFocus={(e) => {
            e.preventDefault();
            railOpener.current?.focus();
          }}
          className="flex w-[20rem] max-w-[85%] flex-col p-0"
        >
          <SheetTitle className="sr-only">Customer context</SheetTitle>
          {rail}
        </SheetContent>
      </Sheet>
      {confirmDialog}
    </>
  );
}
