import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
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

export const Route = createFileRoute("/inbox")({
  head: () => ({
    meta: [
      { title: "Conversation Inbox — BigBond AI" },
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
    return "Customer care window closed (24h). Free-form WhatsApp send is blocked — use an approved template later.";
  }
  if (raw.includes("take_over_required") || raw.includes("bot_still_handling")) {
    return "Take over this conversation before sending on WhatsApp.";
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

function lastCustomerFingerprint(thread: {
  messages: Array<{ id?: string; sender?: string; text?: string; kind?: string }>;
} | null) {
  if (!thread) return "";
  for (let i = thread.messages.length - 1; i >= 0; i--) {
    const m = thread.messages[i];
    if (m.kind === "system") continue;
    if (m.sender === "customer") return `${m.id ?? i}:${m.text ?? ""}`;
  }
  return `len:${thread.messages.length}`;
}

function InboxPage() {
  const queryClient = useQueryClient();
  const { data: threads = [], isLoading, isError, error } = useConversations();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [railOpen, setRailOpen] = useState(true);
  const [pending, setPending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [ragLoading, setRagLoading] = useState(false);
  const [ragError, setRagError] = useState<string | null>(null);
  const [localSuggestions, setLocalSuggestions] = useState<string[] | null>(null);
  const [localDraft, setLocalDraft] = useState<string | null | undefined>(undefined);
  const [includeDraftAnswer, setIncludeDraftAnswer] = useState(false);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastFp = useRef<string>("");

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
    lastFp.current = "";
  }, [activeId]);

  const active = useMemo(
    () => threads.find((t) => t.id === activeId) ?? threads[0] ?? null,
    [threads, activeId],
  );

  const displayThread = useMemo(() => {
    if (!active) return null;
    const next = { ...active };
    if (localSuggestions != null) next.ragSuggestions = localSuggestions;
    if (localDraft !== undefined) next.ragDraftAnswer = localDraft;
    return next;
  }, [active, localSuggestions, localDraft]);

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["conversations"] });
  };

  const runRagRefresh = (conversationId: string, withDraft: boolean) => {
    setRagLoading(true);
    setRagError(null);
    void refreshConversationSuggestions(conversationId, {
      topK: 4,
      includeDraftAnswer: withDraft,
    })
      .then((res) => {
        setLocalSuggestions(res.ragSuggestions ?? []);
        setLocalDraft(res.draftAnswer ?? null);
        if (res.thread) {
          queryClient.setQueryData(["conversations"], (prev: unknown) => {
            if (!Array.isArray(prev)) return prev;
            return prev.map((t: { id?: string }) =>
              t?.id === res.conversationId ? { ...t, ...res.thread } : t,
            );
          });
        }
        void invalidate();
      })
      .catch((err) => {
        setRagError(friendlyInboxError((err as Error)?.message ?? "rag_refresh_failed"));
      })
      .finally(() => setRagLoading(false));
  };

  useEffect(() => {
    if (!active) return;
    const fp = `${active.id}|${lastCustomerFingerprint(active)}|draft:${includeDraftAnswer}`;
    if (fp === lastFp.current) return;
    lastFp.current = fp;

    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    refreshTimer.current = setTimeout(() => {
      runRagRefresh(active.id, includeDraftAnswer);
    }, 500);

    return () => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- debounce keyed on fingerprint + draft toggle
  }, [active?.id, active ? lastCustomerFingerprint(active) : "", includeDraftAnswer]);

  const handleDraftToggle = (next: boolean) => {
    setIncludeDraftAnswer(next);
    if (!next) setLocalDraft(null);
  };

  const handleTakeOver = async () => {
    if (!active || pending) return;
    setPending(true);
    setSendError(null);
    try {
      await takeoverConversation(active.id);
      await invalidate();
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
      await returnConversationToBot(active.id);
      await invalidate();
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
      await sendConversationMessage(active.id, text);
      await invalidate();
    } catch (err) {
      setSendError(friendlyInboxError((err as Error)?.message ?? "send_failed"));
      throw err;
    } finally {
      setPending(false);
    }
  };

  return (
    <AppShell>
      <div className="flex h-full min-h-0 w-full overflow-hidden">
        {isLoading && (
          <div className="grid flex-1 place-items-center text-[13px] text-text-secondary">
            Loading conversations…
          </div>
        )}
        {isError && (
          <div className="grid flex-1 place-items-center text-[13px] text-danger">
            Failed to load inbox: {(error as Error)?.message ?? "unknown error"}
          </div>
        )}
        {!isLoading && !isError && displayThread && (
          <SplitPanes
            storageKey={railOpen ? "bigbond.inbox.split.3" : "bigbond.inbox.split.2"}
            defaultWidths={railOpen ? [28, 47, 25] : [34, 66]}
            minWidthsPx={railOpen ? [220, 360, 240] : [220, 360]}
          >
            {[
              <ConversationList
                key="list"
                threads={threads}
                activeId={displayThread.id}
                onSelect={setActiveId}
              />,
              <div key="chat" className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
                <ChatThread
                  thread={displayThread}
                  onToggleRail={() => setRailOpen((o) => !o)}
                  onTakeOver={handleTakeOver}
                  onReturnToBot={handleReturnToBot}
                  busy={pending}
                />
                <Composer
                  key={displayThread.id}
                  thread={displayThread}
                  onTakeOver={handleTakeOver}
                  onReturnToBot={handleReturnToBot}
                  onSend={handleSend}
                  onRefreshRag={() => runRagRefresh(displayThread.id, includeDraftAnswer)}
                  busy={pending}
                  errorMessage={sendError}
                  ragLoading={ragLoading}
                  ragError={ragError}
                  includeDraftAnswer={includeDraftAnswer}
                  onIncludeDraftAnswerChange={handleDraftToggle}
                />
              </div>,
              railOpen ? (
                <div key="rail" className="h-full min-h-0 border-l border-[var(--border-token)]">
                  <ContextRail thread={displayThread} />
                </div>
              ) : null,
            ]}
          </SplitPanes>
        )}
        {!isLoading && !isError && !displayThread && (
          <div className="grid flex-1 place-items-center text-[13px] text-text-secondary">
            No conversations yet.
          </div>
        )}
      </div>
    </AppShell>
  );
}
