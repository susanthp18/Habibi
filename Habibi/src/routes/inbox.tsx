import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { AppShell } from "@/components/shell/AppShell";
import { ConversationList } from "@/components/inbox/ConversationList";
import { ChatThread } from "@/components/inbox/ChatThread";
import { Composer } from "@/components/inbox/Composer";
import { ContextRail } from "@/components/inbox/ContextRail";
import { SplitPanes } from "@/components/inbox/SplitPanes";
import {
  refreshConversationSuggestions,
  returnConversationToBot,
  sendConversationMessage,
  takeoverConversation,
  useConversations,
} from "@/api/inbox";
import type { Thread } from "@/data/inbox-seed";
import { LoadingState } from "@/components/ui/loading-state";
import { useConfirm } from "@/components/ui/use-confirm";

export type InboxSearch = {
  conversationId?: string;
};

export const Route = createFileRoute("/inbox")({
  validateSearch: (search: Record<string, unknown>): InboxSearch => ({
    conversationId: typeof search.conversationId === "string" ? search.conversationId : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Conversation Inbox — BigBound AI" },
      {
        name: "description",
        content:
          "Omnichannel text inbox — monitor bot conversations, take over on WhatsApp/SMS/email, and resolve with RAG-suggested replies.",
      },
    ],
  }),
  component: InboxPage,
});

function friendlyInboxError(raw: string): string {
  if (raw.includes("whatsapp_window_closed")) {
    return "WhatsApp 24h window is closed. Open WhatsApp on the customer's phone and send any message to the business number first — then reply here within 24 hours.";
  }
  if (raw.includes("take_over_required") || raw.includes("bot_still_handling")) {
    return "Take over this conversation before sending on WhatsApp.";
  }
  if (raw.includes("whatsapp_missing_recipient")) {
    return "No WhatsApp phone number on this customer.";
  }
  if (raw.includes("whatsapp_not_configured")) {
    return "WhatsApp is not configured on the server.";
  }
  if (raw.includes("whatsapp_token_expired")) {
    return "WhatsApp access token expired. Paste a fresh WHATSAPP_TOKEN into backend/.env and restart the API.";
  }
  if (raw.includes("whatsapp_token_invalid")) {
    return "WhatsApp access token is invalid. Check WHATSAPP_TOKEN in backend/.env.";
  }
  if (raw.includes("whatsapp_send_failed")) {
    return `WhatsApp send failed: ${raw.replace(/^whatsapp_send_failed:/, "")}`;
  }
  if (raw.includes("rate_limited")) {
    return "RAG suggestions rate-limited — try again in a moment.";
  }
  if (raw.includes("inbox_rag_failed") || raw.includes("kb_retrieve_failed")) {
    return `Could not refresh RAG suggestions: ${raw}`;
  }
  return raw;
}

function lastCustomerFingerprint(
  thread: {
    messages: Array<{ id?: string; sender?: string; text?: string; kind?: string }>;
  } | null,
) {
  if (!thread) return "";
  for (let i = thread.messages.length - 1; i >= 0; i--) {
    const m = thread.messages[i];
    if (m.kind === "system") continue;
    if (m.sender === "customer") return `${m.id ?? i}:${m.text ?? ""}`;
  }
  return `len:${thread.messages.length}`;
}

function useWideLayout(minPx = 1440) {
  const [wide, setWide] = useState(true);
  useEffect(() => {
    const mq = window.matchMedia(`(min-width: ${minPx}px)`);
    const apply = () => setWide(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [minPx]);
  return wide;
}

function InboxPage() {
  const queryClient = useQueryClient();
  const { confirm, confirmDialog } = useConfirm();
  const navigate = useNavigate({ from: "/inbox" });
  const { conversationId } = Route.useSearch();
  // `isPending`, not `isLoading`. They differ exactly when the fetch is paused
  // — the tab is in the background, or the browser reports itself offline —
  // and in that state `isLoading` is false while no response has ever arrived.
  // The empty branch then rendered "No conversations yet." about an inbox
  // nobody had managed to read: the same graceful-degradation lie as a failed
  // canned-response load claiming none are configured.
  const { data: threads = [], isPending, isError, error, fetchStatus } = useConversations();
  const [activeId, setActiveId] = useState<string | null>(conversationId ?? null);
  const wideLayout = useWideLayout(1440);
  const railUserToggled = useRef(false);
  const [railOpen, setRailOpen] = useState(true);
  const [pending, setPending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [ragLoading, setRagLoading] = useState(false);
  const [ragError, setRagError] = useState<string | null>(null);
  const [localSuggestions, setLocalSuggestions] = useState<string[] | null>(null);
  const [localDraft, setLocalDraft] = useState<string | null | undefined>(undefined);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastFp = useRef<string>("");

  useEffect(() => {
    if (!railUserToggled.current) setRailOpen(wideLayout);
  }, [wideLayout]);

  useEffect(() => {
    if (conversationId) setActiveId(conversationId);
  }, [conversationId]);

  useEffect(() => {
    if (!activeId && threads.length > 0) {
      setActiveId(threads[0].id);
    }
  }, [threads, activeId]);

  useEffect(() => {
    setSendError(null);
    setRagError(null);
    setLocalSuggestions(null);
    setLocalDraft(undefined);
    // A refresh issued for the previous thread can no longer clear this flag
    // (it is not "current" any more), so without resetting it here the spinner
    // stayed up from the moment you switched until the next request settled.
    setRagLoading(false);
    lastFp.current = "";
  }, [activeId]);

  // No `?? threads[0]` fallback. A ?conversationId that matches nothing used to
  // render the first thread in the list instead — same URL, different customer,
  // no indication anything had been substituted.
  const active = useMemo(() => threads.find((t) => t.id === activeId) ?? null, [threads, activeId]);
  const deadLink = Boolean(activeId) && active === null && threads.length > 0;

  const displayThread = useMemo(() => {
    if (!active) return null;
    const next = { ...active };
    if (localSuggestions != null) next.ragSuggestions = localSuggestions;
    if (localDraft !== undefined) next.ragDraftAnswer = localDraft;
    return next;
  }, [active, localSuggestions, localDraft]);

  // Monotonic token + the conversation the newest request was issued for.
  const ragRequestToken = useRef(0);
  const activeIdRef = useRef<string | null>(null);
  activeIdRef.current = active?.id ?? null;

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["conversations"] });
  };

  /**
   * Merge one server-authoritative thread into the cached list.
   *
   * takeover / return-to-bot / send all return the updated Thread, and all
   * three used to throw it away and `await invalidate()` instead — a full
   * refetch of every thread, with messages, suggestions and typing state. That
   * request measures ~1.2s against a warm local API, and the button stayed
   * disabled for the whole of it, so an action the server completed in 0.2s
   * felt like a second and a half of nothing happening.
   *
   * The response is the newest state of the thread that changed. Apply it,
   * release the UI, and let the background refetch reconcile the rest.
   */
  const mergeThread = (updated: Thread | null | undefined) => {
    if (!updated?.id) return;
    queryClient.setQueryData(["conversations"], (prev: unknown) => {
      if (!Array.isArray(prev)) return prev;
      return prev.map((t: { id?: string }) => (t?.id === updated.id ? { ...t, ...updated } : t));
    });
  };

  const runRagRefresh = (conversationId: string, withDraft: boolean) => {
    // Retrieval is slow enough that switching threads mid-flight was routine,
    // and the older response then overwrote the newer one — one customer's KB
    // draft rendered in another customer's thread. Only the newest request for
    // the still-selected conversation may touch state.
    const token = ++ragRequestToken.current;
    const isCurrent = () =>
      token === ragRequestToken.current && activeIdRef.current === conversationId;

    setRagLoading(true);
    setRagError(null);
    void refreshConversationSuggestions(conversationId, {
      topK: 4,
      includeDraftAnswer: withDraft,
    })
      .then((res) => {
        // The thread cache patch is keyed by conversation id, so it is safe
        // (and useful) to apply even if the user has moved on.
        if (res.thread) {
          queryClient.setQueryData(["conversations"], (prev: unknown) => {
            if (!Array.isArray(prev)) return prev;
            return prev.map((t: { id?: string }) =>
              t?.id === res.conversationId ? { ...t, ...res.thread } : t,
            );
          });
        }
        if (!isCurrent()) return;
        setLocalSuggestions(res.ragSuggestions ?? []);
        if (withDraft) setLocalDraft(res.draftAnswer ?? null);
        void invalidate();
      })
      .catch((err) => {
        if (!isCurrent()) return;
        setRagError(friendlyInboxError((err as Error)?.message ?? "rag_refresh_failed"));
      })
      .finally(() => {
        if (isCurrent()) setRagLoading(false);
      });
  };

  useEffect(() => {
    if (!active) return;
    const fp = `${active.id}|${lastCustomerFingerprint(active)}`;
    if (fp === lastFp.current) return;
    lastFp.current = fp;

    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    refreshTimer.current = setTimeout(() => {
      runRagRefresh(active.id, false);
    }, 500);

    return () => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- debounce keyed on conversation + last customer turn
  }, [active?.id, active ? lastCustomerFingerprint(active) : ""]);

  const handleSuggestReply = () => {
    if (!active) return;
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    runRagRefresh(active.id, true);
  };

  const toggleRail = () => {
    railUserToggled.current = true;
    setRailOpen((o) => !o);
  };

  const closeRail = () => {
    railUserToggled.current = true;
    setRailOpen(false);
  };

  const handleTakeOver = async () => {
    if (!active || pending) return;
    // The backend puts no ownership check on takeover, so claiming a thread a
    // colleague is holding silently reassigns it to you and they find out by
    // being rejected. Offering the button is the fix for the dead-end; asking
    // first is what keeps it from being a silent steal.
    if (!active.isMine && active.status === "assigned") {
      const ok = await confirm({
        title: "Take over from another agent?",
        description: `${active.customer}'s conversation is assigned to a colleague. Taking over reassigns it to you, and they will not be able to reply until you hand it back.`,
        confirmLabel: "Take over anyway",
        cancelLabel: "Leave it with them",
      });
      if (!ok) return;
    }
    setPending(true);
    setSendError(null);
    try {
      mergeThread(await takeoverConversation(active.id));
      // Not awaited: the authoritative thread is already in the cache, so
      // holding the button for a full-list refetch buys the operator nothing.
      void invalidate();
    } catch (err) {
      setSendError(friendlyInboxError((err as Error)?.message ?? "takeover_failed"));
    } finally {
      setPending(false);
    }
  };

  const handleReturnToBot = async () => {
    if (!active || pending) return;
    setPending(true);
    setSendError(null);
    try {
      mergeThread(await returnConversationToBot(active.id));
      // Not awaited: the authoritative thread is already in the cache, so
      // holding the button for a full-list refetch buys the operator nothing.
      void invalidate();
    } catch (err) {
      setSendError(friendlyInboxError((err as Error)?.message ?? "return_to_bot_failed"));
    } finally {
      setPending(false);
    }
  };

  const handleSend = async (text: string) => {
    if (!active || pending) return;
    setPending(true);
    setSendError(null);
    try {
      mergeThread(await sendConversationMessage(active.id, text));
      void invalidate();
    } catch (err) {
      setSendError(friendlyInboxError((err as Error)?.message ?? "send_failed"));
      throw err;
    } finally {
      setPending(false);
    }
  };

  const dockedRail = railOpen && wideLayout;
  const overlayRail = railOpen && !wideLayout;

  // The inbox polls every 1.5–4s. Gating the whole screen on `isError` meant a
  // single failed poll replaced a working inbox — cached threads, open thread,
  // half-typed reply — with one line of red text, and the next successful poll
  // put it back. An error with nothing behind it is fatal; an error with
  // cached data is a stale-data warning.
  const fatalError = isError && threads.length === 0;
  const staleWarning = isError && threads.length > 0;

  return (
    <AppShell>
      <div className="flex h-full min-h-0 w-full flex-col overflow-hidden">
        {staleWarning && (
          <div
            role="status"
            className="shrink-0 border-b border-border-warning-subtle bg-background-warning-subtler px-250 py-075 text-body-small text-text-warning-bolder"
          >
            Live updates interrupted ({(error as Error)?.message ?? "unknown error"}). Showing the
            last state received — new messages may be missing.
          </div>
        )}
        <div className="flex min-h-0 w-full flex-1 overflow-hidden">
          {isPending && !isError && (
            <div className="grid flex-1 place-items-center">
              <LoadingState
                label={fetchStatus === "paused" ? "Waiting to reconnect" : "Loading conversations"}
              />
            </div>
          )}
          {fatalError && (
            <div className="grid flex-1 place-items-center text-body text-text-danger">
              Failed to load inbox: {(error as Error)?.message ?? "unknown error"}
            </div>
          )}
          {!isPending && !fatalError && deadLink && (
            <div className="grid flex-1 place-items-center px-300 text-center">
              <div className="max-w-[28rem]">
                <p className="text-body font-semibold text-text">No conversation with this id</p>
                <p className="mt-075 text-body-small text-text-subtle">
                  Nothing in this inbox is registered as “{activeId}”. It may have been deleted, or
                  belong to another tenant.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    const first = threads[0];
                    if (!first) return;
                    setActiveId(first.id);
                    void navigate({ search: { conversationId: first.id }, replace: true });
                  }}
                  className="focus-ring mt-150 inline-flex h-400 items-center rounded-medium bg-background-brand-bold px-150 text-body font-medium text-text-inverse hover:bg-background-brand-bold-hovered"
                >
                  Open the most recent conversation
                </button>
              </div>
            </div>
          )}
          {!isPending && !fatalError && !deadLink && displayThread && (
            <SplitPanes
              storageKey={dockedRail ? "bigbound.inbox.split.3" : "bigbound.inbox.split.2"}
              defaultWidths={dockedRail ? [20, 58, 22] : [24, 76]}
              minWidthsPx={dockedRail ? [240, 420, 280] : [240, 420]}
            >
              {[
                <ConversationList
                  key="list"
                  threads={threads}
                  activeId={displayThread.id}
                  onSelect={(id) => {
                    setActiveId(id);
                    void navigate({ search: { conversationId: id }, replace: true });
                  }}
                />,
                <div
                  key="chat"
                  className="relative flex h-full min-h-0 min-w-0 flex-col overflow-hidden"
                >
                  <ChatThread
                    thread={displayThread}
                    onToggleRail={toggleRail}
                    railOpen={railOpen}
                    onTakeOver={handleTakeOver}
                    onReturnToBot={handleReturnToBot}
                    busy={pending}
                  />
                  <Composer
                    key={displayThread.id}
                    thread={displayThread}
                    onSend={handleSend}
                    onRefreshRag={(withDraft) =>
                      runRagRefresh(displayThread.id, Boolean(withDraft))
                    }
                    onSuggestReply={handleSuggestReply}
                    busy={pending}
                    errorMessage={sendError}
                    ragLoading={ragLoading}
                    ragError={ragError}
                  />
                  {overlayRail && (
                    <div className="absolute inset-y-0 right-0 z-20 flex w-[20rem] max-w-[85%] flex-col border-l border-border bg-surface shadow-overlay">
                      <ContextRail thread={displayThread} onClose={closeRail} />
                    </div>
                  )}
                </div>,
                dockedRail ? (
                  <div key="rail" className="h-full min-h-0 border-l border-border">
                    <ContextRail thread={displayThread} onClose={closeRail} />
                  </div>
                ) : null,
              ]}
            </SplitPanes>
          )}
          {!isPending && !fatalError && !deadLink && !displayThread && (
            <div className="grid flex-1 place-items-center text-body text-text-subtle">
              No conversations yet.
            </div>
          )}
        </div>
      </div>
      {confirmDialog}
    </AppShell>
  );
}
