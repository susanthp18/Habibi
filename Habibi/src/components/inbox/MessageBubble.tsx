import { AlertCircle, Check, CheckCheck, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Message } from "@/api/types/inbox";

const DELIVERY_WORDS: Record<NonNullable<Message["delivery"]>, string> = {
  pending: "Queued — not yet sent",
  sent: "Sent",
  delivered: "Delivered",
  read: "Read",
  failed: "Not delivered",
};

/**
 * The delivery state, as an icon with its name. Drawn on the page surface
 * below the bubble, so in surface colours: inverse (white) ticks there were
 * invisible on a light theme.
 */
function Ticks({ status }: { status: Message["delivery"] }) {
  if (!status) return null;
  const Icon =
    status === "pending"
      ? Clock
      : status === "failed"
        ? AlertCircle
        : status === "sent"
          ? Check
          : CheckCheck;
  const color =
    status === "failed"
      ? "text-text-danger"
      : status === "read"
        ? "text-text-brand"
        : "text-text-subtlest";
  return (
    <span role="img" aria-label={DELIVERY_WORDS[status]} title={DELIVERY_WORDS[status]}>
      <Icon className={cn("h-3.5 w-3.5", color)} aria-hidden />
    </span>
  );
}

/**
 * One message. An agent's message is labelled "Agent", not "You": the record
 * does not say which agent wrote it, and every colleague's reply used to read
 * as the viewer's own.
 */
export function MessageBubble({ message, showTag }: { message: Message; showTag: boolean }) {
  const ours = message.sender !== "customer";

  const bubbleClass = cn(
    "relative max-w-[78%] rounded-xxlarge px-200 py-100 text-body leading-relaxed whitespace-pre-wrap break-words",
    !ours && "bg-surface text-text border border-border rounded-bl-md",
    message.sender === "bot" && "bg-background-brand-subtlest text-text rounded-br-md",
    message.sender === "agent" && "bg-background-brand-bold text-text-inverse rounded-br-md",
    message.delivery === "failed" && "opacity-75",
  );

  return (
    <div className={cn("animate-fade-up flex flex-col", ours ? "items-end" : "items-start")}>
      {showTag && (
        <span
          className={cn(
            "mb-025 px-050 text-body-small font-semibold",
            ours ? "text-text-brand" : "text-text-subtlest",
          )}
        >
          {message.sender === "bot" ? "Bot" : message.sender === "agent" ? "Agent" : "Customer"}
        </span>
      )}
      <div className={bubbleClass}>{message.text}</div>
      <div
        className={cn(
          "mt-050 flex items-center gap-050 text-body-small text-text-subtlest",
          ours ? "justify-end" : "justify-start",
        )}
      >
        <time
          dateTime={message.at ?? undefined}
          title={
            message.at
              ? new Date(message.at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })
              : undefined
          }
        >
          {message.time}
        </time>
        {ours && <Ticks status={message.delivery} />}
      </div>
      {message.deliveryNote && (
        <div
          className={cn(
            "mt-025 max-w-[78%] text-body-small",
            message.delivery === "failed" ? "text-text-danger" : "text-text-subtle",
          )}
        >
          {message.deliveryNote}
        </div>
      )}
    </div>
  );
}
