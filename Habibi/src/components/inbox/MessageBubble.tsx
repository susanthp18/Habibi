import { Check, CheckCheck, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Message } from "@/data/inbox-seed";

function Ticks({ status }: { status: Message["delivery"] }) {
  if (!status) return null;
  if (status === "failed") {
    return <X className="h-3.5 w-3.5 text-text-danger" aria-label="Delivery failed" />;
  }
  const color =
    status === "read"
      ? "text-text-brand"
      : status === "delivered"
        ? "text-text-inverse/70"
        : "text-text-inverse/50";
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
    "relative max-w-[78%] rounded-xxlarge px-200 py-100 text-body leading-snug",
    !isMine && "bg-surface text-text border border-border rounded-bl-md",
    message.sender === "bot" && "bg-background-brand-subtlest text-text rounded-br-md",
    message.sender === "agent" && "bg-background-brand-bold text-text-inverse rounded-br-md",
  );

  const metaClass = cn(
    "mt-050 flex items-center gap-050 text-body-small",
    isMine ? "justify-end" : "justify-start",
    message.sender === "agent" ? "text-text-inverse/75" : "text-text-subtlest",
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
            "mb-025 px-050 text-body-small font-semibold",
            message.sender === "bot" && "text-text-brand",
            message.sender === "agent" && "text-text-brand",
            message.sender === "customer" && "text-text-subtlest",
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
