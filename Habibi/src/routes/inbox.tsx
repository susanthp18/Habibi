import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/shell/AppShell";
import { ConversationList } from "@/components/inbox/ConversationList";
import { ChatThread } from "@/components/inbox/ChatThread";
import { Composer } from "@/components/inbox/Composer";
import { ContextRail } from "@/components/inbox/ContextRail";
import {
  sendConversationMessage,
  takeoverConversation,
  useConversations,
} from "@/api/inbox";

export const Route = createFileRoute("/inbox")({
  head: () => ({
    meta: [
      { title: "Conversation Inbox — Collections Agent" },
      {
        name: "description",
        content:
          "Omnichannel text inbox — monitor bot conversations, take over on WhatsApp/SMS/email, and resolve with RAG-suggested replies.",
      },
    ],
  }),
  component: InboxPage,
});

function InboxPage() {
  const queryClient = useQueryClient();
  const { data: threads = [], isLoading, isError, error } = useConversations();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [railOpen, setRailOpen] = useState(true);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!activeId && threads.length > 0) {
      setActiveId(threads[0].id);
    }
  }, [threads, activeId]);

  const active = useMemo(
    () => threads.find((t) => t.id === activeId) ?? threads[0] ?? null,
    [threads, activeId],
  );

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["conversations"] });
  };

  const handleTakeOver = async () => {
    if (!active || pending) return;
    setPending(true);
    try {
      await takeoverConversation(active.id);
      await invalidate();
    } finally {
      setPending(false);
    }
  };

  const handleSend = async (text: string) => {
    if (!active || pending) return;
    setPending(true);
    try {
      await sendConversationMessage(active.id, text);
      await invalidate();
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
        {!isLoading && !isError && active && (
          <>
            <ConversationList
              threads={threads}
              activeId={active.id}
              onSelect={setActiveId}
            />
            <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
              <ChatThread
                thread={active}
                onToggleRail={() => setRailOpen((o) => !o)}
              />
              <Composer
                thread={active}
                onTakeOver={handleTakeOver}
                onSend={handleSend}
                busy={pending}
              />
            </div>
            {railOpen && <ContextRail thread={active} />}
          </>
        )}
        {!isLoading && !isError && !active && (
          <div className="grid flex-1 place-items-center text-[13px] text-text-secondary">
            No conversations yet.
          </div>
        )}
      </div>
    </AppShell>
  );
}
