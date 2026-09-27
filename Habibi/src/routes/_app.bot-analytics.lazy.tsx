import { useMemo, useState } from "react";
import { createLazyFileRoute } from "@tanstack/react-router";
import { BotAnalyticsHeader } from "@/components/bot-analytics/BotAnalyticsHeader";
import { HeroStrip } from "@/components/bot-analytics/HeroStrip";
import { IntentDistribution } from "@/components/bot-analytics/IntentDistribution";
import { DropOffFunnel } from "@/components/bot-analytics/DropOffFunnel";
import { EscalationReasons } from "@/components/bot-analytics/EscalationReasons";
import { SentimentByIntentHeatmap } from "@/components/bot-analytics/SentimentByIntentHeatmap";
import { UnansweredTable } from "@/components/bot-analytics/UnansweredTable";
import { LatencyChart } from "@/components/bot-analytics/LatencyChart";
import { TurnsHistogram } from "@/components/bot-analytics/TurnsHistogram";
import { analyticsKpis, useBotAnalytics } from "@/api/bot-analytics";
import { botAnalyticsCsv } from "@/lib/bot-analytics";
import { triggerCsvDownload } from "@/lib/dashboard-export";
import type { ChannelKey, RangeKey } from "@/api/types/bot-analytics";
import { LoadingState } from "@/components/ui/loading-state";
import { QueryErrorBanner } from "@/components/ui/query-state";
import { CardSkillAnalytics } from "@/components/bot-analytics/CardSkillAnalytics";

export const Route = createLazyFileRoute("/_app/bot-analytics")({
  component: BotAnalyticsPage,
});

function BotAnalyticsPage() {
  const [range, setRange] = useState<RangeKey>("30d");
  const [channel, setChannel] = useState<ChannelKey>("all");
  const [botId, setBotId] = useState("");
  const [version, setVersion] = useState("");
  const [activeIntent, setActiveIntent] = useState<string | null>(null);

  const filters = { range, channel, botId: botId || undefined, version: version || undefined };
  const { data, isLoading, isError, error } = useBotAnalytics(filters);
  const points = data?.dailySeries ?? [];
  const intentAggs = data?.intentAggs ?? [];
  const agents = data?.agents ?? [];
  const kpis = useMemo(() => analyticsKpis(points, data?.summary), [points, data?.summary]);

  // Client-side from what is on screen: the same rows, the same filters.
  const exportCsv = () => {
    const agentName = agents.find((a) => a.botId === botId)?.name;
    triggerCsvDownload(
      botAnalyticsCsv({ ...filters, agentName }, kpis, points),
      `bot-analytics-${range}-${channel}${botId ? `-${botId}` : ""}${version ? `-v${version}` : ""}.csv`,
    );
  };

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        <BotAnalyticsHeader
          range={range}
          channel={channel}
          onRange={setRange}
          onChannel={setChannel}
          agents={agents}
          botId={botId}
          version={version}
          onAgent={(b, v) => {
            setBotId(b);
            setVersion(v);
          }}
          onExport={data ? exportCsv : undefined}
        />

        {isLoading && !data ? (
          <div className="flex flex-1 items-center justify-center">
            <LoadingState label="Loading bot analytics" />
          </div>
        ) : isError && !data ? (
          <div className="flex flex-1 items-center justify-center p-400">
            <QueryErrorBanner label="bot analytics" error={error} />
          </div>
        ) : (
          <>
            <HeroStrip kpis={kpis} />

            <div className="min-h-0 flex-1 overflow-y-auto bg-surface px-250 py-200">
              <div className="grid gap-200">
                <div className="grid gap-200 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
                  <IntentDistribution
                    intents={intentAggs}
                    activeId={activeIntent}
                    onSelect={setActiveIntent}
                  />
                  <DropOffFunnel stages={data?.funnelStages ?? []} />
                </div>
                <div className="grid gap-200 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
                  <EscalationReasons reasons={data?.escalationReasons ?? []} />
                  <SentimentByIntentHeatmap intents={intentAggs} activeId={activeIntent} />
                </div>
                <UnansweredTable
                  questions={data?.unansweredQuestions ?? []}
                  isLoading={isLoading}
                  isError={isError}
                  error={error}
                />
                <div className="grid gap-200 xl:grid-cols-2">
                  <LatencyChart points={points} />
                  <TurnsHistogram buckets={data?.turnsHistogram ?? []} />
                </div>
                <CardSkillAnalytics byCard={data?.byCard} skillHistogram={data?.skillHistogram} />
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}
