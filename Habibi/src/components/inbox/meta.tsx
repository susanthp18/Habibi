import type { Channel, Sentiment, SlaLevel, Thread, ThreadStatus } from "@/data/inbox-seed";
import { MessageCircle, Mail, MessageSquare, Phone } from "lucide-react";
import { cn } from "@/lib/utils";
import type { LozengeProps } from "@/components/ui/lozenge";
import type { TagProps } from "@/components/ui/tag";

type Tone = NonNullable<LozengeProps["tone"]>;
type Hue = NonNullable<TagProps["hue"]>;

/*
 * Channel is a decorative classification, not a status, so Design.md puts it on a Tag
 * (transparent + accent border) rather than a Lozenge — "Decorative Tag used for status"
 * and "Filled tag pills with semantic-looking backgrounds" are both listed as DON'Ts, and
 * the old filled-green WhatsApp pill was reading as a success state it never meant.
 */
export const channelMeta: Record<
  Channel,
  { label: string; icon: typeof MessageCircle; hue: Hue }
> = {
  whatsapp: { label: "WhatsApp", icon: MessageCircle, hue: "green" },
  sms: { label: "SMS", icon: MessageSquare, hue: "blue" },
  email: { label: "Email", icon: Mail, hue: "purple" },
  chat: { label: "Web chat", icon: MessageCircle, hue: "teal" },
  voice: { label: "Voice", icon: Phone, hue: "magenta" },
};

/** Safe lookup — unknown / future channels degrade instead of crashing. */
export function resolveChannelMeta(channel: string | null | undefined) {
  // Own-property check, not `in`: a channel value of "constructor" or
  // "toString" walks the prototype chain and returns a function, which then
  // renders as garbage instead of falling back.
  if (channel && Object.prototype.hasOwnProperty.call(channelMeta, channel)) {
    return channelMeta[channel as Channel];
  }
  return channelMeta.whatsapp;
}


export const slaColor: Record<SlaLevel, string> = {
  ok: "bg-background-success",
  warn: "bg-background-warning",
  breach: "bg-background-danger",
};

export const sentimentColor: Record<Sentiment, string> = {
  positive: "bg-sentiment-positive",
  neutral: "bg-sentiment-neutral",
  negative: "bg-sentiment-negative",
};

export const statusMeta: Record<ThreadStatus | "mine", { label: string; tone: Tone }> = {
  bot: { label: "Bot", tone: "selected" },
  needs_human: { label: "Needs human", tone: "warning" },
  escalated: { label: "Escalated", tone: "danger" },
  assigned: { label: "Assigned", tone: "neutral" },
  mine: { label: "Mine", tone: "success" },
};

/** Chip key for a row — Mine is derived, never stored. */
export function chipStatus(thread: { status: ThreadStatus; isMine: boolean }): ThreadStatus | "mine" {
  return thread.isMine ? "mine" : thread.status;
}

/** Shared handoff / claim state for inbox thread chrome. */
export function getThreadHandoffState(thread: Thread, hasReturnToBot = false) {
  const needsClaim =
    !thread.isMine &&
    (thread.status === "bot" || thread.status === "needs_human" || thread.status === "escalated");
  const canReturnToBot =
    hasReturnToBot &&
    thread.isMine &&
    (thread.status === "assigned" || thread.status === "needs_human" || thread.status === "escalated");
  const botHandling = thread.status === "bot" && !thread.isMine;
  return { needsClaim, canReturnToBot, botHandling };
}

export function initials(name: string) {
  return name
    .split(" ")
    .slice(0, 2)
    .map((n) => n[0])
    .join("")
    .toUpperCase();
}

const avatarColors = [
  "bg-background-accent-blue-bolder",
  "bg-background-accent-teal-bolder",
  "bg-background-accent-green-bolder",
  "bg-background-accent-orange-bolder",
  "bg-background-accent-red-bolder",
  "bg-background-accent-purple-bolder",
];

export function avatarColor(seed: string) {
  const idx =
    seed.split("").reduce((a, c) => a + c.charCodeAt(0), 0) % avatarColors.length;
  return avatarColors[idx];
}

export function Avatar({
  name,
  size = 36,
  className,
}: {
  name: string;
  size?: number;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid shrink-0 place-items-center rounded-full font-semibold text-white",
        avatarColor(name),
        className,
      )}
      style={{ width: size, height: size, fontSize: size * 0.36 }}
    >
      {initials(name)}
    </div>
  );
}
