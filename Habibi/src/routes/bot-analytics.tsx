import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/shell/AppShell";
import { BotAnalyticsHeader } from "@/components/bot-analytics/BotAnalyticsHeader";
import { HeroStrip } from "@/components/bot-analytics/HeroStrip";
import { IntentDistribution } from "@/components/bot-analytics/IntentDistribution";
import { DropOffFunnel } from "@/components/bot-analytics/DropOffFunnel";
import { EscalationReasons } from "@/components/bot-analytics/EscalationReasons";
import { SentimentByIntentHeatmap } from "@/components/bot-analytics/SentimentByIntentHeatmap";
import { UnansweredTable } from "@/components/bot-analytics/UnansweredTable";
import { LatencyChart } from "@/components/bot-analytics/LatencyChart";
import { TurnsHistogram } from "@/components/bot-analytics/TurnsHistogram";
import {
  filterByRange,
  computeKpis,
  intentAggs,
  type ChannelKey,
  type RangeKey,
} from "@/data/bot-analytics-seed";

export const Route = createFileRoute("/bot-analytics")({
  head: () => ({
    meta: [
      { title: "Conversation & Bot Analytics — Collections Agent" },
      { name: "description", content: "Diagnostic analytics for the collections bot — intents, containment funnel, escalation reasons, RAG misses, latency percentiles." },
      { property: "og:title", content: "Conversation & Bot Analytics" },
      { property: "og:description", content: "Understand why the bot fails and where to improve prompts and RAG coverage." },
    ],
  }),
  component: BotAnalyticsPage,
});

function BotAnalyticsPage() {
  const [range, setRange] = useState<RangeKey>("30d");
  const [channel, setChannel] = useState<ChannelKey>("all");
  const [activeIntent, setActiveIntent] = useState<string | null>(null);

  const points = useMemo(() => filterByRange(range), [range]);
  const kpis = useMemo(() => computeKpis(points), [points]);
  // channel filter is UI-only for PoC — apply a symbolic scale
  const scaledKpis = useMemo(() => {
    if (channel === "all") return kpis;
    const factor = channel === "voice" ? 0.72 : channel === "whatsapp" ? 0.2 : 0.08;
    return {
      ...kpis,
      sessions: Math.round(kpis.sessions * factor),
    };
  }, [kpis, channel]);

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <BotAnalyticsHeader range={range} channel={channel} onRange={setRange} onChannel={setChannel} />
        <HeroStrip kpis={scaledKpis} />

        <div className="min-h-0 flex-1 overflow-y-auto bg-surface-app px-5 py-4">
          <div className="grid gap-4">
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
              <IntentDistribution intents={intentAggs} activeId={activeIntent} onSelect={setActiveIntent} />
              <DropOffFunnel />
            </div>
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
              <EscalationReasons />
              <SentimentByIntentHeatmap intents={intentAggs} activeId={activeIntent} />
            </div>
            <UnansweredTable />
            <div className="grid gap-4 xl:grid-cols-2">
              <LatencyChart points={points} />
              <TurnsHistogram />
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
