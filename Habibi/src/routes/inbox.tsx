import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/shell/AppShell";
import { ConversationList } from "@/components/inbox/ConversationList";
import { ChatThread } from "@/components/inbox/ChatThread";
import { Composer } from "@/components/inbox/Composer";
import { ContextRail } from "@/components/inbox/ContextRail";
import {
  threads as seedThreads,
  type Message,
  type SystemEvent,
  type Thread,
} from "@/data/inbox-seed";

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

function nowLabel() {
  const d = new Date();
  const h = d.getHours();
  const m = d.getMinutes().toString().padStart(2, "0");
  const ampm = h >= 12 ? "PM" : "AM";
  const hh = ((h + 11) % 12) + 1;
  return `${hh}:${m} ${ampm}`;
}

function InboxPage() {
  const [threads, setThreads] = useState<Thread[]>(seedThreads);
  const [activeId, setActiveId] = useState<string>(seedThreads[0].id);
  const [railOpen, setRailOpen] = useState(true);
  const [takenOver, setTakenOver] = useState<Record<string, boolean>>({});

  const active = useMemo(
    () => threads.find((t) => t.id === activeId) ?? threads[0],
    [threads, activeId],
  );

  const handleTakeOver = () => {
    setTakenOver((prev) => ({ ...prev, [active.id]: true }));
    const sysEvent: SystemEvent = {
      id: `sys-${Date.now()}`,
      kind: "system",
      text: "You took over from bot",
      time: nowLabel(),
    };
    setThreads((prev) =>
      prev.map((t) =>
        t.id === active.id
          ? { ...t, status: "mine", messages: [...t.messages, sysEvent] }
          : t,
      ),
    );
  };

  const handleSend = (text: string) => {
    const msg: Message = {
      id: `m-${Date.now()}`,
      sender: "agent",
      text,
      time: nowLabel(),
      delivery: "sent",
    };
    setThreads((prev) =>
      prev.map((t) =>
        t.id === active.id
          ? {
              ...t,
              messages: [...t.messages, msg],
              lastPreview: text,
              lastFrom: "agent",
              lastTime: msg.time,
              unread: 0,
            }
          : t,
      ),
    );
  };

  return (
    <AppShell>
      <div className="flex h-full min-h-0 w-full overflow-hidden">
        <ConversationList
          threads={threads}
          activeId={active.id}
          onSelect={setActiveId}
        />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <ChatThread
            thread={active}
            onToggleRail={() => setRailOpen((o) => !o)}
            tookOver={!!takenOver[active.id]}
          />
          <Composer
            thread={active}
            tookOver={!!takenOver[active.id]}
            onTakeOver={handleTakeOver}
            onSend={handleSend}
          />
        </div>
        {railOpen && <ContextRail thread={active} />}
      </div>
    </AppShell>
  );
}
