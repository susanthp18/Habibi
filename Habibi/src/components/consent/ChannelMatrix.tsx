import { Phone, MessageCircle, MessageSquare, Mail, type LucideIcon } from "lucide-react";
import { SelectField } from "@/components/ui/select";
import type { ChannelConsent, ConsentChannel, ConsentStatus } from "@/api/types/consent";

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
/** Promotional consent is captured or withdrawn, never set to DND/expired here. */
const PROMO_OPTIONS: { value: string; label: string }[] = [
  { value: "opted_in", label: "Opted-in" },
  { value: "opted_out", label: "Opted-out" },
];
const NOT_CAPTURED = { value: "", label: "Not captured" };

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
      <div className="grid grid-cols-[110px_1fr_1fr_90px] items-center gap-100 border-b border-border bg-surface-sunken px-150 py-075 text-body-small font-semibold text-text-subtlest">
        <div>Channel</div>
        <div title="Collections and account servicing contact">Servicing</div>
        <div title="Offers and cross-sell">Promotional</div>
        <div className="text-right">Weekly usage</div>
      </div>
      {CHANNEL_ORDER.map((key) => {
        const c = channels.find((x) => x.channel === key);
        if (!c) return null;
        const { label, Icon } = CHANNEL_META[key];
        return (
          <div
            key={key}
            className="grid grid-cols-[110px_1fr_1fr_90px] items-center gap-100 border-b border-border px-150 py-100 last:border-b-0"
          >
            <div className="inline-flex items-center gap-075 text-body-small font-medium text-text">
              <Icon className="h-3.5 w-3.5 text-text-subtle" /> {label}
            </div>
            <SelectField
              aria-label={`${label} consent`}
              value={c.status}
              onChange={(v) => update(key, { status: v as ConsentStatus })}
              size="compact"
              options={STATUS_OPTIONS}
            />
            <SelectField
              aria-label={`${label} promotional consent`}
              value={c.promotional ?? ""}
              onChange={(v) => v && update(key, { promotional: v as ConsentStatus })}
              size="compact"
              options={
                !c.promotional
                  ? [NOT_CAPTURED, ...PROMO_OPTIONS]
                  : PROMO_OPTIONS.some((o) => o.value === c.promotional)
                    ? PROMO_OPTIONS
                    : [STATUS_OPTIONS.find((o) => o.value === c.promotional)!, ...PROMO_OPTIONS]
              }
            />
            <div className="text-right text-body-small text-text-subtle">
              {c.usedThisWeek}/{c.frequencyCapPerWeek}
            </div>
          </div>
        );
      })}
    </div>
  );
}
