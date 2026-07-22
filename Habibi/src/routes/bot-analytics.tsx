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
import { useBotAnalytics } from "@/api/bot-analytics";
import { USE_MOCK } from "@/api/config";
import {
  computeKpis,
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

  const { data } = useBotAnalytics(range, channel);
  const points = data?.dailySeries ?? [];
  const intentAggs = data?.intentAggs ?? [];
  const kpis = useMemo(() => {
    const base = computeKpis(points);
    // Mock-only: historic PoC scaled KPI sessions by channel. Live pushes channel to SQL.
    if (!USE_MOCK || channel === "all") return base;
    const factor = channel === "voice" ? 0.72 : channel === "whatsapp" ? 0.2 : 0.08;
    return { ...base, sessions: Math.round(base.sessions * factor) };
  }, [points, channel]);

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <BotAnalyticsHeader range={range} channel={channel} onRange={setRange} onChannel={setChannel} />
        <HeroStrip kpis={kpis} />

        <div className="min-h-0 flex-1 overflow-y-auto bg-surface-app px-5 py-4">
          <div className="grid gap-4">
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
              <IntentDistribution intents={intentAggs} activeId={activeIntent} onSelect={setActiveIntent} />
              <DropOffFunnel stages={data?.funnelStages ?? []} />
            </div>
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
              <EscalationReasons reasons={data?.escalationReasons ?? []} />
              <SentimentByIntentHeatmap intents={intentAggs} activeId={activeIntent} />
            </div>
            <UnansweredTable questions={data?.unansweredQuestions ?? []} />
            <div className="grid gap-4 xl:grid-cols-2">
              <LatencyChart points={points} />
              <TurnsHistogram buckets={data?.turnsHistogram ?? []} />
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
