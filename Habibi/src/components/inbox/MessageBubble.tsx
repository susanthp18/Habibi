import { Check, CheckCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Message } from "@/data/inbox-seed";

function Ticks({ status }: { status: Message["delivery"] }) {
  if (!status) return null;
  const color =
    status === "read"
      ? "text-brand-primary"
      : status === "delivered"
        ? "text-white/70"
        : "text-white/50";
  const Icon = status === "sent" ? Check : CheckCheck;
  return <Icon className={cn("h-3.5 w-3.5", color)} />;
}

export function MessageBubble({
  message,
  showTag,
}: {
  message: Message;
  showTag: boolean;
}) {
  const isMine = message.sender !== "customer";

  const bubbleClass = cn(
    "relative max-w-[78%] rounded-2xl px-3.5 py-2 text-[13.5px] leading-snug shadow-card",
    !isMine && "bg-white text-text-primary border border-[var(--border-token)] rounded-bl-md",
    message.sender === "bot" && "bg-brand-tint text-brand-navy rounded-br-md",
    message.sender === "agent" && "bg-brand-primary text-white rounded-br-md",
  );

  const metaClass = cn(
    "mt-1 flex items-center gap-1 text-[10.5px]",
    isMine ? "justify-end" : "justify-start",
    message.sender === "agent" ? "text-white/75" : "text-text-muted",
  );

  return (
    <div
      className={cn(
        "animate-fade-up flex flex-col",
        isMine ? "items-end" : "items-start",
      )}
    >
      {showTag && (
        <span
          className={cn(
            "mb-0.5 px-1 text-[10px] font-semibold uppercase tracking-wider",
            message.sender === "bot" && "text-brand-primary",
            message.sender === "agent" && "text-brand-primary-dark",
            message.sender === "customer" && "text-text-muted",
          )}
        >
          {message.sender === "bot" ? "Bot" : message.sender === "agent" ? "You" : "Customer"}
        </span>
      )}
      <div className={bubbleClass}>{message.text}</div>
      <div className={metaClass}>
        <span>{message.time}</span>
        {isMine && <Ticks status={message.delivery} />}
      </div>
    </div>
  );
}
