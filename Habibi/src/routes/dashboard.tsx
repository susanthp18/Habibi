import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { AppShell } from "@/components/shell/AppShell";
import { FiltersBar } from "@/components/dashboard/FiltersBar";
import { HeroKpiCard } from "@/components/dashboard/HeroKpiCard";
import { KpiTile } from "@/components/dashboard/KpiTile";
import { RecoveryTrendChart } from "@/components/dashboard/RecoveryTrendChart";
import { CallVolumeChart } from "@/components/dashboard/CallVolumeChart";
import { SentimentDistribution } from "@/components/dashboard/SentimentDistribution";
import { BotVsHumanDonut } from "@/components/dashboard/BotVsHumanDonut";
import { AgentLeaderboard } from "@/components/dashboard/AgentLeaderboard";
import { AtRiskAccounts } from "@/components/dashboard/AtRiskAccounts";
import { Skeleton } from "@/components/ui/skeleton";
import { useDashboard } from "@/api/dashboard";
import type { Range, Segment, TeamFilter } from "@/data/dashboard-seed";

export const Route = createFileRoute("/dashboard")({
  head: () => ({
    meta: [
      { title: "Executive Dashboard — BigBound AI" },
      {
        name: "description",
        content:
          "Portfolio health at a glance: AHT, upsell conversion, recovery, bot containment, sentiment, leaderboard, and at-risk accounts.",
      },
      { property: "og:title", content: "Executive Dashboard — BigBound AI" },
      {
        property: "og:description",
        content: "Leadership view of collections performance across bot and human channels.",
      },
    ],
  }),
  component: DashboardPage,
});

function DashboardPage() {
  const [range, setRange] = useState<Range>("30d");
  const [segment, setSegment] = useState<Segment>("all");
  const [team, setTeam] = useState<TeamFilter>("all");

  const { data } = useDashboard({ range, segment, team });

  const handleExport = () => toast.success("Report queued — you'll get an email when it's ready.");
  const handleAgent = () => toast.info("Opens agent scorecard (QA module) — coming soon.");
  const handleAccount = () => toast.info("Opens Customer 360 — coming soon.");

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <FiltersBar
          range={range}
          segment={segment}
          team={team}
          onRange={setRange}
          onSegment={setSegment}
          onTeam={setTeam}
          onExport={handleExport}
        />

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[100rem] space-y-200 p-300">
            {!data ? (
              <DashboardSkeleton />
            ) : (
              <>
                {/* Hero KPIs */}
                <section className="grid grid-cols-1 gap-200 md:grid-cols-2">
                  {data.heroKpis.map((k) => (
                    <HeroKpiCard key={k.label} kpi={k} />
                  ))}
                </section>

                {/* Secondary KPIs */}
                <section className="grid grid-cols-2 gap-150 md:grid-cols-3 xl:grid-cols-6">
                  {data.kpis.map((k) => (
                    <KpiTile key={k.key} kpi={k} />
                  ))}
                </section>

                {/* Trend row */}
                <section className="grid grid-cols-1 gap-200 lg:grid-cols-2">
                  <div className="h-[18.75rem]">
                    <RecoveryTrendChart data={data.recoveryTrend} />
                  </div>
                  <div className="h-[18.75rem]">
                    <CallVolumeChart data={data.callVolumeStacked} />
                  </div>
                </section>

                {/* Sentiment + Bot/Human row */}
                <section className="grid grid-cols-1 gap-200 lg:grid-cols-2">
                  <div className="h-[16.25rem]">
                    <SentimentDistribution {...data.sentimentDistribution} />
                  </div>
                  <div className="h-[16.25rem]">
                    <BotVsHumanDonut data={data.botVsHuman} />
                  </div>
                </section>

                {/* Bottom row */}
                <section className="grid grid-cols-1 gap-200 lg:grid-cols-2">
                  <div className="h-[25rem]">
                    <AgentLeaderboard rows={data.leaderboard} onOpen={handleAgent} />
                  </div>
                  <div className="h-[25rem]">
                    <AtRiskAccounts accounts={data.atRiskAccounts} onOpen={handleAccount} />
                  </div>
                </section>
              </>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-200" aria-busy="true" aria-label="Loading dashboard">
      <section className="grid grid-cols-1 gap-200 md:grid-cols-2">
        <Skeleton className="h-[8.75rem] rounded-large" />
        <Skeleton className="h-[8.75rem] rounded-large" />
      </section>
      <section className="grid grid-cols-2 gap-150 md:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-[5.75rem] rounded-large" />
        ))}
      </section>
      <section className="grid grid-cols-1 gap-200 lg:grid-cols-2">
        <Skeleton className="h-[18.75rem] rounded-large" />
        <Skeleton className="h-[18.75rem] rounded-large" />
      </section>
      <section className="grid grid-cols-1 gap-200 lg:grid-cols-2">
        <Skeleton className="h-[16.25rem] rounded-large" />
        <Skeleton className="h-[16.25rem] rounded-large" />
      </section>
      <section className="grid grid-cols-1 gap-200 lg:grid-cols-2">
        <Skeleton className="h-[25rem] rounded-large" />
        <Skeleton className="h-[25rem] rounded-large" />
      </section>
    </div>
  );
}
