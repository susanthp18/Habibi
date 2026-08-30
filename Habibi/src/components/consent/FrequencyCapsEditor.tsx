import type { ChannelConsent, ConsentChannel } from "@/data/consent-seed";
import { CHANNEL_LABEL } from "@/data/consent-seed";

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
    <div className="space-y-075 rounded-medium border border-border bg-surface p-150">
      {channels.map((c) => {
        const pct = Math.min(
          100,
          Math.round((c.usedThisWeek / Math.max(1, c.frequencyCapPerWeek)) * 100),
        );
        const tone =
          pct >= 100
            ? "var(--danger)"
            : pct >= 75
              ? "var(--warning)"
              : "var(--background-brand-bold)";
        return (
          <div
            key={c.channel}
            className="grid grid-cols-[90px_1fr_auto] items-center gap-100 text-body-small"
          >
            <div className="text-text">{CHANNEL_LABEL[c.channel]}</div>
            <div className="h-1.5 overflow-hidden rounded-full bg-surface-sunken">
              <div className="h-full rounded-full" style={{ width: `${pct}%`, background: tone }} />
            </div>
            <div className="flex items-center gap-050">
              <div className="text-text-subtle tabular-nums">
                {c.usedThisWeek}/{c.frequencyCapPerWeek}
              </div>
              <input
                type="number"
                min={0}
                max={20}
                value={c.frequencyCapPerWeek}
                onChange={(e) =>
                  update(c.channel, {
                    frequencyCapPerWeek: Math.max(0, Number(e.target.value) || 0),
                  })
                }
                className="h-300 w-600 rounded-medium border border-border bg-surface px-050 text-right text-body-small"
                title="Weekly cap (ledger counts usage)"
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
