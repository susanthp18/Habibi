import { Phone, MessageSquare, MessageCircle, Mail, type LucideIcon } from "lucide-react";
import type { ChannelConsent, ConsentChannel } from "@/data/consent-seed";

const ICONS: Record<ConsentChannel, LucideIcon> = {
  call: Phone,
  whatsapp: MessageCircle,
  sms: MessageSquare,
  email: Mail,
};

export function ChannelChip({ cc }: { cc: ChannelConsent }) {
  const Icon = ICONS[cc.channel];
  const capHit = cc.usedThisWeek >= cc.frequencyCapPerWeek;
  const tone =
    cc.status === "opted_in" && !capHit
      ? { bg: "var(--success-bg)", fg: "var(--success)" }
      : cc.status === "opted_in" && capHit
        ? { bg: "var(--warning-bg)", fg: "var(--warning)" }
        : cc.status === "dnd"
          ? { bg: "var(--danger-bg)", fg: "var(--danger)" }
          : cc.status === "opted_out"
            ? { bg: "var(--surface-sunken)", fg: "var(--text-muted)" }
            : { bg: "var(--warning-bg)", fg: "var(--warning)" }; // expired

  const label =
    cc.status === "opted_in"
      ? `${cc.usedThisWeek}/${cc.frequencyCapPerWeek}`
      : cc.status === "opted_out"
        ? "Opt-out"
        : cc.status === "dnd"
          ? "DND"
          : "Expired";

  return (
    <span
      title={`${cc.channel} · ${cc.status.replace("_", " ")} · ${cc.usedThisWeek}/${cc.frequencyCapPerWeek} this week`}
      className="inline-flex items-center gap-050 rounded-medium px-075 py-025 text-body-small font-semibold"
      style={{ background: tone.bg, color: tone.fg }}
    >
      <Icon className="h-3 w-3" />
      {label}
    </span>
  );
}
