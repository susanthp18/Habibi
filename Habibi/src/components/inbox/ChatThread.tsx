import { useEffect, useRef, useState } from "react";
import { Copy, Bot, Info, MoreHorizontal, UserRound } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { Thread, ThreadItem } from "@/data/inbox-seed";
import { getThreadHandoffState } from "./meta";
import { MessageBubble } from "./MessageBubble";
import { Lozenge } from "@/components/ui/lozenge";

function isMessage(item: ThreadItem): item is Extract<ThreadItem, { sender: unknown }> {
  return (item as { kind?: string }).kind !== "system";
}

function BotTypingBubble() {
  return (
    <div
      className="animate-fade-up flex flex-col items-start"
      aria-live="polite"
      aria-label="Bot is typing"
    >
      <span className="mb-025 px-050 text-body-small font-semibold text-text-brand">Bot</span>
      <div className="inline-flex items-center gap-050 rounded-xxlarge rounded-bl-md border border-border bg-background-brand-subtlest px-200 py-150">
        <span
          className="typing-dot h-1.5 w-1.5 rounded-full bg-background-brand-bold"
          style={{ animationDelay: "0ms" }}
        />
        <span
          className="typing-dot h-1.5 w-1.5 rounded-full bg-background-brand-bold"
          style={{ animationDelay: "160ms" }}
        />
        <span
          className="typing-dot h-1.5 w-1.5 rounded-full bg-background-brand-bold"
          style={{ animationDelay: "320ms" }}
        />
      </div>
      <div className="mt-050 px-050 text-body-small text-text-subtlest">typing…</div>
    </div>
  );
}

export function ChatThread({
  thread,
  onToggleRail,
  railOpen = false,
  onTakeOver,
  onReturnToBot,
  busy = false,
}: {
  thread: Thread;
  onToggleRail: () => void;
  railOpen?: boolean;
  onTakeOver?: () => void;
  onReturnToBot?: () => void;
  busy?: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const { needsClaim, canReturnToBot, botHandling, heldByTeammate } = getThreadHandoffState(
    thread,
    Boolean(onReturnToBot),
  );
  const botTyping = Boolean(thread.botTyping) && thread.status === "bot" && !thread.isMine;

  // Opening a thread always lands at the newest message; after that, follow
  // only if the reader is already at the bottom. The list re-renders on every
  // poll — 1.5s while the bot is typing — and each one used to yank the view
  // back down, so scrolling up to read what the customer said earlier was
  // impossible while a turn was in flight.
  const atBottomRef = useRef(true);
  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 64;
  };

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    atBottomRef.current = true;
    el.scrollTop = el.scrollHeight;
  }, [thread.id]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && atBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [thread.messages.length, botTyping]);

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
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-surface">
      <div className="flex shrink-0 items-center gap-150 border-b border-border bg-surface px-250 py-100">
        <h2 className="min-w-0 truncate heading-xsmall text-text">{thread.customer}</h2>

        <div className="ml-auto flex shrink-0 items-center gap-100">
          {botTyping ? (
            <Lozenge tone="selected">
              <span className="pulse-dot h-100 w-100 rounded-full bg-background-brand-bold" />
              Bot is typing…
            </Lozenge>
          ) : botHandling ? (
            <Lozenge tone="success">
              <span className="pulse-dot h-100 w-100 rounded-full bg-background-success-bold" />
              Bot is handling
            </Lozenge>
          ) : thread.isMine ? (
            <Lozenge tone="selected">You&apos;ve taken over</Lozenge>
          ) : heldByTeammate ? (
            // "Awaiting agent" was shown here too, about a thread an agent is
            // already holding.
            <Lozenge tone="neutral">Another agent has this</Lozenge>
          ) : (
            <Lozenge tone="warning">Awaiting agent</Lozenge>
          )}
          {needsClaim && onTakeOver && (
            <button
              type="button"
              disabled={busy}
              onClick={onTakeOver}
              className="focus-ring inline-flex h-400 items-center gap-075 rounded-medium bg-background-brand-bold px-150 text-body font-medium text-text-inverse hover:bg-background-brand-bold-hovered active:scale-[0.98] disabled:opacity-60"
            >
              <UserRound className="h-3.5 w-3.5" />
              Take over
            </button>
          )}
          <button
            type="button"
            onClick={onToggleRail}
            className={cn(
              "focus-ring grid h-400 w-400 place-items-center rounded-medium text-text-subtle hover:bg-surface-sunken",
              railOpen && "bg-surface-sunken text-text-brand",
            )}
            aria-label="Toggle customer context"
            aria-pressed={railOpen}
            title="Customer context"
          >
            <Info className="h-4 w-4" />
          </button>
          <div className="relative" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen((o) => !o)}
              className={cn(
                "focus-ring grid h-400 w-400 place-items-center rounded-medium text-text-subtle hover:bg-surface-sunken",
                menuOpen && "bg-surface-sunken text-text-brand",
              )}
              aria-label="More actions"
              aria-expanded={menuOpen}
            >
              <MoreHorizontal className="h-4 w-4" />
            </button>
            {menuOpen && (
              <div className="absolute right-0 z-20 mt-050 w-52 overflow-hidden rounded-medium border border-border bg-surface py-050 shadow-overlay">
                {canReturnToBot && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setMenuOpen(false);
                      onReturnToBot?.();
                    }}
                    className="focus-ring flex w-full items-center gap-100 px-150 py-100 text-left text-body-small text-text hover:bg-background-brand-subtlest disabled:opacity-50"
                  >
                    <Bot className="h-3.5 w-3.5 text-text-brand" />
                    Return to bot
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => void copyAccount()}
                  className="focus-ring flex w-full items-center gap-100 px-150 py-100 text-left text-body-small text-text hover:bg-background-brand-subtlest"
                >
                  <Copy className="h-3.5 w-3.5 text-text-subtlest" />
                  Copy account ID
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="min-h-0 flex-1 overflow-y-auto px-300 py-250"
      >
        <div className="mx-auto flex max-w-[50rem] flex-col gap-100">
          {thread.messages.map((item, idx) => {
            if (!isMessage(item)) {
              return (
                <div key={item.id} className="my-100 flex items-center gap-100">
                  <div className="h-px flex-1 bg-border" />
                  <Lozenge tone="neutral">
                    {item.text} · {item.time}
                  </Lozenge>
                  <div className="h-px flex-1 bg-border" />
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
