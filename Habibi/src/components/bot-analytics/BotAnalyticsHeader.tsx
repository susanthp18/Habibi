import { Download } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { ChannelKey, RangeKey } from "@/data/bot-analytics-seed";

const RANGES: Array<{ key: RangeKey; label: string }> = [
  { key: "7d", label: "7d" },
  { key: "30d", label: "30d" },
  { key: "90d", label: "90d" },
];
const CHANNELS: Array<{ key: ChannelKey; label: string }> = [
  { key: "all", label: "All channels" },
  { key: "voice", label: "Voice" },
  { key: "whatsapp", label: "WhatsApp" },
  { key: "sms", label: "SMS" },
];

export function BotAnalyticsHeader({
  range,
  channel,
  onRange,
  onChannel,
}: {
  range: RangeKey;
  channel: ChannelKey;
  onRange: (r: RangeKey) => void;
  onChannel: (c: ChannelKey) => void;
}) {
  return (
    <header className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-[18px] font-semibold text-brand-navy">Conversation & Bot Analytics</h1>
        <span className="rounded-full bg-surface-sunken px-2 py-0.5 text-[11px] font-medium text-text-secondary">
          Diagnostic view · feeds KB + Prompt Studio
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="inline-flex overflow-hidden rounded-md border border-[var(--border-token)]">
            {RANGES.map((r) => (
              <button
                key={r.key}
                onClick={() => onRange(r.key)}
                className={cn(
                  "px-2.5 py-1 text-[12px]",
                  range === r.key ? "bg-brand-tint text-brand-primary-dark font-semibold" : "text-text-secondary hover:bg-surface-sunken",
                )}
              >
                {r.label}
              </button>
            ))}
          </div>
          <select
            value={channel}
            onChange={(e) => onChannel(e.target.value as ChannelKey)}
            className="rounded-md border border-[var(--border-token)] bg-surface-card px-2 py-1 text-[12px]"
          >
            {CHANNELS.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select>
          <button
            onClick={() => toast.success("Export queued", { description: "Conversation analytics CSV will be ready in ~30 seconds." })}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-3 py-1.5 text-[12px] text-brand-primary hover:bg-brand-tint"
          >
            <Download className="h-3.5 w-3.5" /> Export
          </button>
        </div>
      </div>
      <p className="text-[12px] text-text-secondary">
        Intent mix, containment funnel, escalation reasons, RAG misses, latency — every gap here is a candidate for KB or prompt tuning.
      </p>
    </header>
  );
}
