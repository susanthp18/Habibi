import type { Channel, Sentiment, SlaLevel, ThreadStatus } from "@/data/inbox-seed";
import { MessageCircle, Mail, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";

export const channelMeta: Record<
  Channel,
  { label: string; icon: typeof MessageCircle; badge: string }
> = {
  whatsapp: {
    label: "WhatsApp",
    icon: MessageCircle,
    badge: "bg-success-bg text-success",
  },
  sms: {
    label: "SMS",
    icon: MessageSquare,
    badge: "bg-surface-sunken text-text-secondary",
  },
  email: {
    label: "Email",
    icon: Mail,
    badge: "bg-brand-tint text-brand-primary-dark",
  },
};

export const slaColor: Record<SlaLevel, string> = {
  ok: "bg-success",
  warn: "bg-warning",
  breach: "bg-danger",
};

export const sentimentColor: Record<Sentiment, string> = {
  positive: "bg-sentiment-positive",
  neutral: "bg-sentiment-neutral",
  negative: "bg-sentiment-negative",
};

export const statusMeta: Record<
  ThreadStatus | "mine",
  { label: string; className: string }
> = {
  bot: { label: "Bot", className: "bg-brand-tint text-brand-primary-dark" },
  needs_human: {
    label: "Needs human",
    className: "bg-warning-bg text-warning",
  },
  escalated: { label: "Escalated", className: "bg-danger-bg text-danger" },
  assigned: {
    label: "Assigned",
    className: "bg-surface-sunken text-text-secondary",
  },
  mine: { label: "Mine", className: "bg-success-bg text-success" },
};

/** Chip key for a row — Mine is derived, never stored. */
export function chipStatus(thread: { status: ThreadStatus; isMine: boolean }): ThreadStatus | "mine" {
  return thread.isMine ? "mine" : thread.status;
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
  "bg-[#1877F2]",
  "bg-[#0A4DA6]",
  "bg-[#2E7D32]",
  "bg-[#F9A825]",
  "bg-[#D93025]",
  "bg-[#7E57C2]",
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
