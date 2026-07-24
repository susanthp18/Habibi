import { useState } from "react";
import { Activity, FileText, Gauge, Layers, LineChart, Radio, Wrench } from "lucide-react";
import type { SandboxTurn } from "@/data/sandbox-seed";
import { RetrievalTab } from "./inspector/RetrievalTab";
import { IntentTab } from "./inspector/IntentTab";
import { SentimentTab } from "./inspector/SentimentTab";
import { TraceTab } from "./inspector/TraceTab";
import { ToolsTab } from "./inspector/ToolsTab";
import { MetricsTab, type TurnMetric } from "./inspector/MetricsTab";
import { EMPTY_INSIGHTS, type LiveCallInsights } from "./voice/liveEvents";
import { cn } from "@/lib/utils";

type Tab = "retrieval" | "tools" | "intent" | "sentiment" | "trace" | "metrics" | "context";

type Props = {
  turns: SandboxTurn[];
  metrics?: TurnMetric[];
  /** Live-call domain events; empty in text mode. */
  insights?: LiveCallInsights;
  /** Force-show Context tab (PII) outside DEV — off by default. */
  showContextDebug?: boolean;
};

export function InspectorPanel({
  turns,
  metrics = [],
  insights = EMPTY_INSIGHTS,
  showContextDebug = false,
}: Props) {
  const [tab, setTab] = useState<Tab>("retrieval");
  const toolCount = insights.toolCalls.length;
  const contextAllowed = Boolean(import.meta.env.DEV) || showContextDebug;
  const TABS: Array<{ key: Tab; label: string; icon: typeof Layers; badge?: number }> = [
    { key: "retrieval", label: "Retrieval", icon: Layers },
    { key: "tools", label: "Tools", icon: Wrench, badge: toolCount || undefined },
    { key: "intent", label: "Intent", icon: Radio },
    { key: "sentiment", label: "Sentiment", icon: LineChart },
    { key: "trace", label: "Trace", icon: Activity },
    { key: "metrics", label: "Metrics", icon: Gauge },
    ...(contextAllowed
      ? [{ key: "context" as const, label: "Context", icon: FileText }]
      : []),
  ];

  return (
    <aside className="hidden h-full min-h-0 w-[340px] shrink-0 flex-col border-l border-[var(--border-token)] bg-surface-card xl:flex">
      <div className="shrink-0 border-b border-[var(--border-token)] px-3">
        <div className="flex gap-0.5 overflow-x-auto">
          {TABS.map((t) => {
            const Icon = t.icon;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                className={cn(
                  "inline-flex shrink-0 flex-1 items-center justify-center gap-1 border-b-2 px-1 py-2 text-[11.5px]",
                  tab === t.key
                    ? "border-brand-primary font-semibold text-brand-primary-dark"
                    : "border-transparent text-text-secondary hover:text-text-primary",
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {t.label}
                {t.badge ? (
                  <span className="rounded-full bg-brand-primary px-1 text-[9.5px] font-semibold leading-4 text-white">
                    {t.badge}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {tab === "retrieval" && <RetrievalTab turns={turns} ragHits={insights.ragHits} />}
        {tab === "tools" && <ToolsTab calls={insights.toolCalls} />}
        {tab === "intent" && <IntentTab turns={turns} />}
        {tab === "sentiment" && <SentimentTab turns={turns} />}
        {tab === "trace" && <TraceTab turns={turns} />}
        {tab === "metrics" && (
          <MetricsTab metrics={metrics} turns={turns} turnAudio={insights.turnAudio} />
        )}
        {tab === "context" && contextAllowed && (
          <div className="space-y-2">
            <p className="text-[11px] text-amber-800">
              Debug only — may contain real customer PII. Not shown in production builds.
            </p>
            {insights.contextCard ? (
              <pre className="whitespace-pre-wrap break-words rounded-md border border-[var(--border-token)] bg-surface-sunken p-2 font-mono text-[10.5px] leading-relaxed text-text-secondary">
                {insights.contextCard}
              </pre>
            ) : (
              <div className="rounded-md border border-dashed border-[var(--border-token)] p-6 text-center text-[12px] text-text-muted">
                Context card arrives after the voice session binds CRM state.
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
