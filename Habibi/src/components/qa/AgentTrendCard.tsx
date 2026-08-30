import type { AgentQaStat } from "@/data/qa-seed";
import { ScoreBand } from "./ScoreBand";
import { ChartStage, LivelineTrend, SnapshotPill } from "@/components/charts";
import { cn } from "@/lib/utils";

export function AgentTrendCard({ stat }: { stat: AgentQaStat | null }) {
  if (!stat) {
    return (
      <div className="rounded-large border border-border bg-surface p-300 text-center text-body-small text-text-subtlest shadow-raised">
        Select an agent to view their trend.
      </div>
    );
  }

  const labels = stat.trend.map((_, i) => `D${i + 1}`);
  const maxSection = Math.max(...stat.sectionScores.map((s) => s.value), 1);

  return (
    <div className="space-y-150 rounded-large border border-border bg-surface p-150 shadow-raised">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-body font-semibold text-text">{stat.agentId}</div>
          <div className="text-body-small text-text-subtlest">
            {stat.scored} scorecards · weakest: {stat.weakestSection}
          </div>
        </div>
        <ScoreBand total={stat.avg} size="md" />
      </div>

      <div>
        <div className="mb-050 flex items-center justify-between">
          <div className="text-body-small font-medium text-text-subtlest">7-day score trend</div>
          <SnapshotPill />
        </div>
        <ChartStage>
          <LivelineTrend
            values={stat.trend}
            labels={labels}
            color="#1868db"
            height={96}
            formatValue={(v) => v.toFixed(0)}
            formatTime={(i) => labels[i] ?? ""}
            fill
          />
        </ChartStage>
      </div>

      <div>
        <div className="mb-100 text-body-small font-medium text-text-subtlest">
          Section breakdown
        </div>
        <div className="space-y-075">
          {stat.sectionScores.map((s) => (
            <div key={s.section} className="grid grid-cols-[7rem_1fr_2.5rem] items-center gap-100">
              <span className="truncate text-body-tiny text-text-subtle">{s.section}</span>
              <div className="h-2 overflow-hidden rounded-full bg-surface-sunken">
                <div
                  className={cn(
                    "h-full rounded-full transition-[width] duration-300",
                    s.value >= 80
                      ? "bg-background-success-bold"
                      : s.value >= 60
                        ? "bg-background-brand-bold"
                        : "bg-background-warning-bold",
                  )}
                  style={{ width: `${(s.value / maxSection) * 100}%` }}
                />
              </div>
              <span className="text-right text-body-tiny font-semibold tabular-nums text-text">
                {Math.round(s.value)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
