import { useEffect, useRef, useState } from "react";
import { Copy, Bot, Info, MoreHorizontal, UserRound } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { Thread, ThreadItem } from "@/data/inbox-seed";
import { resolveChannelMeta, sentimentColor } from "./meta";
import { MessageBubble } from "./MessageBubble";

function isMessage(item: ThreadItem): item is Extract<ThreadItem, { sender: unknown }> {
  return (item as { kind?: string }).kind !== "system";
}

function BotTypingBubble() {
  return (
    <div className="animate-fade-up flex flex-col items-start" aria-live="polite" aria-label="Bot is typing">
      <span className="mb-0.5 px-1 text-[10px] font-semibold uppercase tracking-wider text-brand-primary">
        Bot
      </span>
      <div className="inline-flex items-center gap-1 rounded-2xl rounded-bl-md border border-[var(--border-token)] bg-brand-tint px-3.5 py-2.5 shadow-card">
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-brand-primary" style={{ animationDelay: "0ms" }} />
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-brand-primary" style={{ animationDelay: "160ms" }} />
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-brand-primary" style={{ animationDelay: "320ms" }} />
      </div>
      <div className="mt-1 px-1 text-[10.5px] text-text-muted">typing…</div>
    </div>
  );
}

export function ChatThread({
  thread,
  onToggleRail,
  onTakeOver,
  onReturnToBot,
  busy = false,
}: {
  thread: Thread;
  onToggleRail: () => void;
  onTakeOver?: () => void;
  onReturnToBot?: () => void;
  busy?: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const chan = resolveChannelMeta(thread.channel);
  const ChanIcon = chan.icon;
  const botTyping = Boolean(thread.botTyping) && thread.status === "bot" && !thread.isMine;
  const needsClaim =
    !thread.isMine &&
    (thread.status === "bot" || thread.status === "needs_human" || thread.status === "escalated");
  const canReturnToBot =
    Boolean(onReturnToBot) &&
    thread.isMine &&
    (thread.status === "assigned" || thread.status === "needs_human" || thread.status === "escalated");

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [thread.id, thread.messages.length, botTyping]);

  useEffect(() => {
    setMenuOpen(false);
  }, [thread.id]);

  useEffect(() => {
    if (!menuOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [menuOpen]);

  const botHandling = thread.status === "bot" && !thread.isMine;

  const copyAccount = async () => {
    try {
      await navigator.clipboard.writeText(thread.accountId);
      toast.success("Account ID copied");
    } catch {
      toast.error("Could not copy account ID");
    }
    setMenuOpen(false);
  };

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
          {botTyping ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-tint px-2.5 py-1 text-[11.5px] font-semibold text-brand-primary-dark">
              <span className="pulse-dot h-2 w-2 rounded-full bg-brand-primary" />
              Bot is typing…
            </span>
          ) : botHandling ? (
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
            aria-label="Toggle customer context"
            title="Toggle customer context"
          >
            <Info className="h-4 w-4" />
          </button>
          <div className="relative" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen((o) => !o)}
              className={cn(
                "grid h-8 w-8 place-items-center rounded-md text-text-secondary hover:bg-surface-sunken",
                menuOpen && "bg-surface-sunken text-brand-primary",
              )}
              aria-label="More actions"
              aria-expanded={menuOpen}
            >
              <MoreHorizontal className="h-4 w-4" />
            </button>
            {menuOpen && (
              <div className="absolute right-0 z-20 mt-1 w-52 overflow-hidden rounded-md border border-[var(--border-token)] bg-white py-1 shadow-pop">
                {needsClaim && onTakeOver && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setMenuOpen(false);
                      onTakeOver();
                    }}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12.5px] text-text-primary hover:bg-brand-tint disabled:opacity-50"
                  >
                    <UserRound className="h-3.5 w-3.5 text-brand-primary" />
                    Take over
                  </button>
                )}
                {canReturnToBot && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setMenuOpen(false);
                      onReturnToBot?.();
                    }}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12.5px] text-text-primary hover:bg-brand-tint disabled:opacity-50"
                  >
                    <Bot className="h-3.5 w-3.5 text-brand-primary" />
                    Return to bot
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => void copyAccount()}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12.5px] text-text-primary hover:bg-brand-tint"
                >
                  <Copy className="h-3.5 w-3.5 text-text-muted" />
                  Copy account ID
                </button>
              </div>
            )}
          </div>
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
          {botTyping && <BotTypingBubble />}
        </div>
      </div>
    </div>
  );
}
