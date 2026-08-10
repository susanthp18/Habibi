import { Download } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { ChannelKey, RangeKey } from "@/data/bot-analytics-seed";
import { Lozenge } from "@/components/ui/lozenge";

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
    <header className="shrink-0 border-b border-border bg-surface px-250 py-150">
      <div className="flex flex-wrap items-center gap-100">
        <h1 className="text-[1.25rem] font-semibold text-text">Conversation & bot analytics</h1>
        <Lozenge tone="neutral">
          Diagnostic view · feeds KB + Prompt Studio
        </Lozenge>
        <div className="ml-auto flex flex-wrap items-center gap-100">
          <div className="inline-flex overflow-hidden rounded-medium border border-border">
            {RANGES.map((r) => (
              <button
                key={r.key}
                onClick={() => onRange(r.key)}
                className={cn(
                  "px-150 py-050 text-body-small",
                  range === r.key ? "bg-background-brand-subtlest text-text-brand font-semibold" : "text-text-subtle hover:bg-surface-sunken",
                )}
              >
                {r.label}
              </button>
            ))}
          </div>
          <select
            value={channel}
            onChange={(e) => onChannel(e.target.value as ChannelKey)}
            className="rounded-medium border border-border bg-surface px-100 py-050 text-body-small"
          >
            {CHANNELS.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select>
          <button
            onClick={() => toast.success("Export queued", { description: "Conversation analytics CSV will be ready in ~30 seconds." })}
            className="inline-flex items-center gap-050 rounded-medium border border-border px-150 py-075 text-body-small text-text-brand hover:bg-background-brand-subtlest"
          >
            <Download className="h-3.5 w-3.5" /> Export
          </button>
        </div>
      </div>
      <p className="text-body-small text-text-subtle">
        Intent mix, containment funnel, escalation reasons, RAG misses, latency — every gap here is a candidate for KB or prompt tuning.
      </p>
    </header>
  );
}
