import { useEffect, useRef, useState } from "react";
import { ArrowDown, Copy, Bot, Info, MoreHorizontal, UserRound } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { Thread, ThreadItem } from "@/api/types/inbox";
import { getThreadHandoffState, resolveChannelMeta, type InboxRights } from "./meta";
import { MessageBubble } from "./MessageBubble";
import { Lozenge } from "@/components/ui/lozenge";
import { Tag } from "@/components/ui/tag";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

function isMessage(item: ThreadItem): item is Extract<ThreadItem, { sender: unknown }> {
  return "sender" in item;
}

const DAY = new Intl.DateTimeFormat("en-IN", {
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "Asia/Kolkata",
});

/** The IST calendar day an item belongs to, for the divider between days. */
function dayOf(item: ThreadItem): string | null {
  return item.at ? DAY.format(new Date(item.at)) : null;
}

function BotTypingBubble() {
  return (
    <div className="animate-fade-up flex flex-col items-start" aria-label="Bot is typing">
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
  rights,
  onToggleRail,
  railOpen = false,
  onTakeOver,
  onReturnToBot,
  busy = false,
}: {
  thread: Thread;
  rights: InboxRights;
  onToggleRail: () => void;
  railOpen?: boolean;
  onTakeOver: () => void;
  onReturnToBot: () => void;
  busy?: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const { canClaim, canReturnToBot, botHandling, heldByTeammate } = getThreadHandoffState(
    thread,
    rights,
  );
  const botTyping = Boolean(thread.botTyping) && thread.status === "bot" && !thread.isMine;
  const channel = resolveChannelMeta(thread.channel);
  const ChannelIcon = channel.icon;
  const messages = thread.messages ?? [];

  // Opening a thread lands at the newest message; after that, follow only if
  // the reader is already at the bottom -- polls re-render every few seconds,
  // and yanking the view down made reading earlier history impossible. What
  // arrives while they read above is announced instead.
  const atBottomRef = useRef(true);
  const [unseen, setUnseen] = useState(0);
  const seenCount = useRef(messages.length);
  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 64;
    if (atBottomRef.current) {
      seenCount.current = messages.length;
      setUnseen(0);
    }
  };
  const toBottom = () => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  };

  useEffect(() => {
    atBottomRef.current = true;
    seenCount.current = messages.length;
    setUnseen(0);
    toBottom();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- on opening a thread only
  }, [thread.id]);

  useEffect(() => {
    if (atBottomRef.current) {
      seenCount.current = messages.length;
      toBottom();
    } else {
      setUnseen(Math.max(0, messages.length - seenCount.current));
    }
  }, [messages.length, botTyping]);

  const copyAccount = async () => {
    try {
      await navigator.clipboard.writeText(thread.accountId);
      toast.success("Account ID copied");
    } catch {
      toast.error("Could not copy account ID");
    }
  };

  let previousDay: string | null = null;

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-surface">
      <div className="flex shrink-0 items-center gap-150 border-b border-border bg-surface px-250 py-100">
        <h2 className="min-w-0 truncate heading-xsmall text-text">{thread.customer}</h2>
        <Tag hue={channel.hue}>
          <ChannelIcon className="h-3 w-3" aria-hidden />
          {channel.label}
        </Tag>
        {thread.sentiment === "negative" && (
          <Lozenge tone="danger" title="The customer's recent messages read as negative">
            Negative sentiment
          </Lozenge>
        )}

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
            <Lozenge tone="neutral">Another agent has this</Lozenge>
          ) : (
            <Lozenge tone="warning">Awaiting agent</Lozenge>
          )}
          {canClaim && (
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
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="focus-ring grid h-400 w-400 place-items-center rounded-medium text-text-subtle hover:bg-surface-sunken"
                aria-label="More actions"
              >
                <MoreHorizontal className="h-4 w-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {canReturnToBot && (
                <DropdownMenuItem disabled={busy} onSelect={onReturnToBot}>
                  <Bot className="h-3.5 w-3.5 text-text-brand" />
                  Return to bot
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onSelect={() => void copyAccount()}>
                <Copy className="h-3.5 w-3.5 text-text-subtlest" />
                Copy account ID
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <div className="relative min-h-0 flex-1">
        <div
          ref={scrollRef}
          onScroll={onScroll}
          className="h-full overflow-y-auto px-300 py-250"
          role="log"
          aria-label={`Conversation with ${thread.customer}`}
        >
          <div className="mx-auto flex max-w-[50rem] flex-col gap-100">
            {messages.length === 0 && (
              <p className="py-400 text-center text-body-small text-text-subtle">
                No messages in this conversation yet.
              </p>
            )}
            {messages.map((item, idx) => {
              const day = dayOf(item);
              const divider = day && day !== previousDay ? day : null;
              if (day) previousDay = day;
              const prev = messages[idx - 1];
              const prevSender = prev && isMessage(prev) ? prev.sender : null;
              return (
                <div key={item.id} className="flex flex-col gap-100">
                  {divider && (
                    <div className="my-100 text-center text-body-small font-medium text-text-subtlest">
                      {divider}
                    </div>
                  )}
                  {isMessage(item) ? (
                    <MessageBubble
                      message={item}
                      showTag={Boolean(divider) || prevSender !== item.sender}
                    />
                  ) : (
                    <div className="my-100 flex items-center gap-100">
                      <div className="h-px flex-1 bg-border" />
                      <Lozenge tone="neutral">
                        {item.text} · {item.time}
                      </Lozenge>
                      <div className="h-px flex-1 bg-border" />
                    </div>
                  )}
                </div>
              );
            })}
            {botTyping && <BotTypingBubble />}
          </div>
        </div>
        {unseen > 0 && (
          <button
            type="button"
            onClick={toBottom}
            className="focus-ring absolute bottom-150 left-1/2 inline-flex -translate-x-1/2 items-center gap-075 rounded-full bg-background-brand-bold px-150 py-050 text-body-small font-medium text-text-inverse shadow-overlay"
          >
            <ArrowDown className="h-3.5 w-3.5" />
            {unseen === 1 ? "1 new message" : `${unseen} new messages`}
          </button>
        )}
      </div>
    </div>
  );
}
