import { useEffect, useRef } from "react";
import { Info, MoreHorizontal } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { Thread, ThreadItem } from "@/data/inbox-seed";
import { channelMeta, sentimentColor } from "./meta";
import { MessageBubble } from "./MessageBubble";

function isMessage(item: ThreadItem): item is Extract<ThreadItem, { sender: unknown }> {
  return (item as { kind?: string }).kind !== "system";
}

export function ChatThread({
  thread,
  onToggleRail,
}: {
  thread: Thread;
  onToggleRail: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const chan = channelMeta[thread.channel];
  const ChanIcon = chan.icon;

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [thread.id, thread.messages.length]);

  const botHandling = thread.status === "bot" && !thread.isMine;

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-surface-app">
      {/* Header */}
      <div className="grid shrink-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-[var(--border-token)] bg-surface-card px-5 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-[15px] font-semibold text-brand-navy">
              {thread.customer}
            </h2>
            <span className="font-mono text-[11px] text-text-muted">
              {thread.accountId}
            </span>
          </div>
          <div className="mt-0.5 flex items-center gap-2">
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-semibold",
                chan.badge,
              )}
            >
              <ChanIcon className="h-3 w-3" />
              {chan.label}
            </span>
            <span className="inline-flex items-center gap-1 text-[11.5px] text-text-secondary">
              <span className={cn("h-1.5 w-1.5 rounded-full", sentimentColor[thread.sentiment])} />
              {thread.sentiment} sentiment
            </span>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {botHandling ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-success-bg px-2.5 py-1 text-[11.5px] font-semibold text-success">
              <span className="pulse-dot h-2 w-2 rounded-full bg-success" />
              Bot is handling
            </span>
          ) : thread.isMine ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-tint px-2.5 py-1 text-[11.5px] font-semibold text-brand-primary-dark">
              You've taken over
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-warning-bg px-2.5 py-1 text-[11.5px] font-semibold text-warning">
              Awaiting agent
            </span>
          )}
          <button
            type="button"
            onClick={onToggleRail}
            className="grid h-8 w-8 place-items-center rounded-md text-text-secondary hover:bg-surface-sunken"
            aria-label="Toggle context"
          >
            <Info className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => toast("More actions")}
            className="grid h-8 w-8 place-items-center rounded-md text-text-secondary hover:bg-surface-sunken"
            aria-label="More"
          >
            <MoreHorizontal className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto flex max-w-[720px] flex-col gap-2">
          {thread.messages.map((item, idx) => {
            if (!isMessage(item)) {
              return (
                <div key={item.id} className="my-2 flex items-center gap-2">
                  <div className="h-px flex-1 bg-[var(--border-token)]" />
                  <span className="rounded-full bg-surface-sunken px-2.5 py-0.5 text-[11px] text-text-secondary">
                    {item.text} · {item.time}
                  </span>
                  <div className="h-px flex-1 bg-[var(--border-token)]" />
                </div>
              );
            }
            const prev = thread.messages[idx - 1];
            const prevSender = prev && isMessage(prev) ? prev.sender : null;
            const showTag = prevSender !== item.sender;
            return <MessageBubble key={item.id} message={item} showTag={showTag} />;
          })}
        </div>
      </div>
    </div>
  );
}
