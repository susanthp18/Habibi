import { Phone, MessageCircle, MessageSquare, Mail, type LucideIcon } from "lucide-react";
import type { ChannelConsent, ConsentChannel, ConsentStatus } from "@/data/consent-seed";

const CHANNEL_ORDER: ConsentChannel[] = ["call", "whatsapp", "sms", "email"];
const CHANNEL_META: Record<ConsentChannel, { label: string; Icon: LucideIcon }> = {
  call: { label: "Voice call", Icon: Phone },
  whatsapp: { label: "WhatsApp", Icon: MessageCircle },
  sms: { label: "SMS", Icon: MessageSquare },
  email: { label: "Email", Icon: Mail },
};

const STATUS_OPTIONS: { value: ConsentStatus; label: string }[] = [
  { value: "opted_in", label: "Opted-in" },
  { value: "opted_out", label: "Opted-out" },
  { value: "dnd", label: "DND" },
  { value: "expired", label: "Expired" },
];

export function ChannelMatrix({
  channels,
  onChange,
}: {
  channels: ChannelConsent[];
  onChange: (next: ChannelConsent[]) => void;
}) {
  const update = (channel: ConsentChannel, patch: Partial<ChannelConsent>) => {
    onChange(channels.map((c) => (c.channel === channel ? { ...c, ...patch } : c)));
  };

  return (
    <div className="rounded-md border border-[var(--border-token)] bg-surface-card">
      <div className="grid grid-cols-[110px_1fr_90px] items-center gap-2 border-b border-[var(--border-token)] bg-surface-sunken px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
        <div>Channel</div>
        <div>Status</div>
        <div className="text-right">Weekly usage</div>
      </div>
      {CHANNEL_ORDER.map((key) => {
        const c = channels.find((x) => x.channel === key);
        if (!c) return null;
        const { label, Icon } = CHANNEL_META[key];
        return (
          <div key={key} className="grid grid-cols-[110px_1fr_90px] items-center gap-2 border-b border-[var(--border-token)] px-3 py-2 last:border-b-0">
            <div className="inline-flex items-center gap-1.5 text-[12px] font-medium text-brand-navy">
              <Icon className="h-3.5 w-3.5 text-text-secondary" /> {label}
            </div>
            <select
              value={c.status}
              onChange={(e) => update(key, { status: e.target.value as ConsentStatus })}
              className="h-7 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[11px]"
            >
              {STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <div className="text-right text-[11px] text-text-secondary">
              {c.usedThisWeek}/{c.frequencyCapPerWeek}
            </div>
          </div>
        );
      })}
    </div>
  );
}
