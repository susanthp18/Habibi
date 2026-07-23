import { useState } from "react";
import { Activity, Gauge, Layers, LineChart, Radio } from "lucide-react";
import type { SandboxTurn } from "@/data/sandbox-seed";
import { RetrievalTab } from "./inspector/RetrievalTab";
import { IntentTab } from "./inspector/IntentTab";
import { SentimentTab } from "./inspector/SentimentTab";
import { TraceTab } from "./inspector/TraceTab";
import { MetricsTab, type TurnMetric } from "./inspector/MetricsTab";
import { cn } from "@/lib/utils";

type Tab = "retrieval" | "intent" | "sentiment" | "trace" | "metrics";

type Props = { turns: SandboxTurn[]; metrics?: TurnMetric[] };

export function InspectorPanel({ turns, metrics = [] }: Props) {
  const [tab, setTab] = useState<Tab>("retrieval");
  const TABS: Array<{ key: Tab; label: string; icon: typeof Layers }> = [
    { key: "retrieval", label: "Retrieval", icon: Layers },
    { key: "intent", label: "Intent", icon: Radio },
    { key: "sentiment", label: "Sentiment", icon: LineChart },
    { key: "trace", label: "Trace", icon: Activity },
    { key: "metrics", label: "Metrics", icon: Gauge },
  ];

  return (
    <aside className="hidden h-full min-h-0 w-[340px] shrink-0 flex-col border-l border-[var(--border-token)] bg-surface-card xl:flex">
      <div className="shrink-0 border-b border-[var(--border-token)] px-3">
        <div className="flex gap-0.5">
          {TABS.map((t) => {
            const Icon = t.icon;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                className={cn(
                  "inline-flex flex-1 items-center justify-center gap-1 border-b-2 px-1 py-2 text-[11.5px]",
                  tab === t.key
                    ? "border-brand-primary font-semibold text-brand-primary-dark"
                    : "border-transparent text-text-secondary hover:text-text-primary",
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {t.label}
              </button>
            );
          })}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {tab === "retrieval" && <RetrievalTab turns={turns} />}
        {tab === "intent" && <IntentTab turns={turns} />}
        {tab === "sentiment" && <SentimentTab turns={turns} />}
        {tab === "trace" && <TraceTab turns={turns} />}
        {tab === "metrics" && <MetricsTab metrics={metrics} turns={turns} />}
      </div>
    </aside>
  );
}
