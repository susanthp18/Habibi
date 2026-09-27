import { Download } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ChannelKey, RangeKey } from "@/api/types/bot-analytics";
import { Lozenge } from "@/components/ui/lozenge";
import { SelectField } from "@/components/ui/select";

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
  agents,
  botId,
  version,
  onAgent,
  onExport,
}: {
  range: RangeKey;
  channel: ChannelKey;
  onRange: (r: RangeKey) => void;
  onChannel: (c: ChannelKey) => void;
  /** Agents with calls in range; Voice Studio ones list their published versions. */
  agents: Array<{ botId: string; name: string; versions: string[] }>;
  botId: string;
  version: string;
  /** Picking an agent clears the version; "" means all. */
  onAgent: (botId: string, version: string) => void;
  /** Disabled until there is data to export. */
  onExport?: () => void;
}) {
  const versions = agents.find((a) => a.botId === botId)?.versions ?? [];
  return (
    <header className="shrink-0 border-b border-border bg-surface px-250 py-150">
      <div className="flex flex-wrap items-center gap-100">
        <h1 className="heading-medium font-semibold text-text">Conversation & bot analytics</h1>
        <Lozenge tone="neutral">Diagnostic view · feeds KB + Prompt Studio</Lozenge>
        <div className="ml-auto flex flex-wrap items-center gap-100">
          <div className="inline-flex overflow-hidden rounded-medium border border-border">
            {RANGES.map((r) => (
              <button
                key={r.key}
                onClick={() => onRange(r.key)}
                className={cn(
                  "px-150 py-050 text-body-small",
                  range === r.key
                    ? "bg-background-brand-subtlest text-text-brand font-semibold"
                    : "text-text-subtle hover:bg-surface-sunken",
                )}
              >
                {r.label}
              </button>
            ))}
          </div>
          <SelectField
            aria-label="Channel"
            value={channel}
            onChange={(v) => onChannel(v as ChannelKey)}
            size="compact"
            className="w-[9.375rem]"
            options={CHANNELS.map((c) => ({ value: c.key, label: c.label }))}
          />
          <SelectField
            aria-label="Agent"
            value={botId}
            onChange={(v) => onAgent(v, "")}
            size="compact"
            className="w-[12rem]"
            options={[
              { value: "", label: "All agents" },
              // Keep a selection that has no calls in the new range visible.
              ...(botId && !agents.some((a) => a.botId === botId)
                ? [{ value: botId, label: botId }]
                : []),
              ...agents.map((a) => ({ value: a.botId, label: a.name })),
            ]}
          />
          {versions.length > 0 && (
            <SelectField
              aria-label="Agent version"
              value={version}
              onChange={(v) => onAgent(botId, v)}
              size="compact"
              className="w-[8.5rem]"
              options={[
                { value: "", label: "All versions" },
                ...versions.map((v) => ({ value: v, label: `Version ${v}` })),
              ]}
            />
          )}
          <button
            onClick={onExport}
            disabled={!onExport}
            title="Download the KPIs and daily series on screen as CSV"
            className="inline-flex items-center gap-050 rounded-medium border border-border px-150 py-075 text-body-small text-text-brand hover:bg-background-brand-subtlest disabled:opacity-40"
          >
            <Download className="h-3.5 w-3.5" /> Export
          </button>
        </div>
      </div>
      <p className="text-body-small text-text-subtle">
        Intent mix, containment funnel, escalation reasons, RAG misses, latency — every gap here is
        a candidate for KB or prompt tuning.
      </p>
    </header>
  );
}
