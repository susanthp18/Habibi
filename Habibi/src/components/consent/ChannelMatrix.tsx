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
    <div className="rounded-medium border border-border bg-surface">
      <div className="grid grid-cols-[110px_1fr_90px] items-center gap-100 border-b border-border bg-surface-sunken px-150 py-075 text-body-small font-semibold text-text-subtlest">
        <div>Channel</div>
        <div>Status</div>
        <div className="text-right">Weekly usage</div>
      </div>
      {CHANNEL_ORDER.map((key) => {
        const c = channels.find((x) => x.channel === key);
        if (!c) return null;
        const { label, Icon } = CHANNEL_META[key];
        return (
          <div
            key={key}
            className="grid grid-cols-[110px_1fr_90px] items-center gap-100 border-b border-border px-150 py-100 last:border-b-0"
          >
            <div className="inline-flex items-center gap-075 text-body-small font-medium text-text">
              <Icon className="h-3.5 w-3.5 text-text-subtle" /> {label}
            </div>
            <select
              value={c.status}
              onChange={(e) => update(key, { status: e.target.value as ConsentStatus })}
              className="h-7 rounded-medium border border-border bg-surface px-100 text-body-small"
            >
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <div className="text-right text-body-small text-text-subtle">
              {c.usedThisWeek}/{c.frequencyCapPerWeek}
            </div>
          </div>
        );
      })}
    </div>
  );
}
