import type { ChannelConsent, ConsentChannel } from "@/data/consent-seed";
import { CHANNEL_LABEL } from "@/data/consent-seed";
import { RotateCcw } from "lucide-react";

export function FrequencyCapsEditor({
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
    <div className="space-y-1.5 rounded-md border border-[var(--border-token)] bg-surface-card p-3">
      {channels.map((c) => {
        const pct = Math.min(100, Math.round((c.usedThisWeek / Math.max(1, c.frequencyCapPerWeek)) * 100));
        const tone = pct >= 100 ? "var(--danger)" : pct >= 75 ? "var(--warning)" : "var(--brand-primary)";
        return (
          <div key={c.channel} className="grid grid-cols-[90px_1fr_auto_auto] items-center gap-2 text-[11px]">
            <div className="text-brand-navy">{CHANNEL_LABEL[c.channel]}</div>
            <div className="h-1.5 overflow-hidden rounded-full bg-surface-sunken">
              <div className="h-full rounded-full" style={{ width: `${pct}%`, background: tone }} />
            </div>
            <div className="text-text-secondary tabular-nums">{c.usedThisWeek}/{c.frequencyCapPerWeek}</div>
            <div className="flex items-center gap-1">
              <input
                type="number"
                min={0}
                max={20}
                value={c.frequencyCapPerWeek}
                onChange={(e) => update(c.channel, { frequencyCapPerWeek: Math.max(0, Number(e.target.value) || 0) })}
                className="h-6 w-12 rounded-md border border-[var(--border-token)] bg-surface-card px-1 text-right text-[11px]"
              />
              <button
                onClick={() => update(c.channel, { usedThisWeek: 0 })}
                title="Reset usage counter"
                className="rounded-md p-1 text-text-muted hover:bg-surface-sunken hover:text-brand-primary"
              >
                <RotateCcw className="h-3 w-3" />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
