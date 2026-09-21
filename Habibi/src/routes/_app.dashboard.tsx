import { useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
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
import { QueryErrorBanner } from "@/components/ui/query-state";
import { useDashboard, useEmailDashboardExport, fetchDashboardCsv } from "@/api/dashboard";
import { dashboardFilename, dashboardToCsv, triggerCsvDownload } from "@/lib/dashboard-export";
import { mutationErrorMessage } from "@/lib/mutation-errors";
import type { LeaderRow, Range, Segment, TeamFilter } from "@/api/types/dashboard";

export const Route = createFileRoute("/_app/dashboard")({
  head: () => ({
    meta: [
      { title: "Executive Dashboard — PayInt" },
      {
        name: "description",
        content:
          "Portfolio health at a glance: AHT, upsell conversion, recovery, bot containment, sentiment, leaderboard, and at-risk accounts.",
      },
      { property: "og:title", content: "Executive Dashboard — PayInt" },
      {
        property: "og:description",
        content: "Leadership view of collections performance across bot and human channels.",
      },
    ],
  }),
  component: DashboardPage,
});

function DashboardPage() {
  const navigate = useNavigate();
  const [range, setRange] = useState<Range>("30d");
  const [segment, setSegment] = useState<Segment>("all");
  const [team, setTeam] = useState<TeamFilter>("all");

  const { data, isPending, isError, error } = useDashboard({ range, segment, team });
  const emailExport = useEmailDashboardExport();

  const handleDownloadCsv = async () => {
    try {
      const { blob, filename } = await fetchDashboardCsv({ range, segment, team });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("CSV downloaded");
    } catch {
      if (data) {
        triggerCsvDownload(dashboardToCsv(data), dashboardFilename({ range, segment, team }));
        toast.success("CSV downloaded");
        return;
      }
      toast.error("Could not download the dashboard CSV");
    }
  };

  const handleEmailReport = () => {
    emailExport.mutate(
      { range, segment, team },
      {
        onSuccess: (job) => {
          if (job.mailStatus === "smtp_disabled") {
            toast.success("Report is ready — mail was skipped (SMTP is not configured).");
            return;
          }
          toast.success("Report emailed");
        },
        onError: (err) => toast.error(mutationErrorMessage(err)),
      },
    );
  };
  const handleAgent = (row: LeaderRow) => {
    void navigate({ to: "/qa", search: { agent: row.name } });
  };

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        <FiltersBar
          range={range}
          segment={segment}
          team={team}
          onRange={setRange}
          onSegment={setSegment}
          onTeam={setTeam}
          onDownloadCsv={() => void handleDownloadCsv()}
          onEmailReport={handleEmailReport}
          emailPending={emailExport.isPending}
        />

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[100rem] space-y-200 p-300">
            {!data && isError ? (
              <QueryErrorBanner label="the dashboard" error={error} />
            ) : !data ? (
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
                    <AgentLeaderboard
                      rows={data.leaderboard}
                      onOpen={handleAgent}
                      isLoading={isPending}
                      isError={isError}
                      error={error}
                    />
                  </div>
                  <div className="h-[25rem]">
                    <AtRiskAccounts accounts={data.atRiskAccounts} />
                  </div>
                </section>
              </>
            )}
          </div>
        </div>
      </div>
    </>
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
