import { trendByDay, type Violation } from "@/data/compliance-seed";
import { ChartCard, ChartStage, LivelineTrend, SnapshotPill } from "@/components/charts";

const SERIES = [
  { id: "critical", label: "Critical", color: "#e2483d", key: "critical" as const },
  { id: "high", label: "High", color: "#e06c00", key: "high" as const },
  { id: "medium", label: "Medium", color: "#b38600", key: "medium" as const },
  { id: "low", label: "Low", color: "#7d818a", key: "low" as const },
];

export function ViolationTrendChart({ all }: { all: Violation[] }) {
  const data = trendByDay(all, 30);
  const labels = data.map((d) => d.day);
  const series = SERIES.map((s) => ({
    id: s.id,
    label: s.label,
    color: s.color,
    values: data.map((d) => d[s.key]),
  }));

  return (
    <ChartCard
      title="Violation trend"
      subtitle="Last 30 days · by severity"
      action={
        <div className="flex flex-wrap items-center gap-100 text-[11px] text-text-subtle">
          {SERIES.map((s) => (
            <span key={s.id} className="inline-flex items-center gap-050">
              <span className="size-1.5 rounded-full" style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
      }
    >
      <ChartStage
        toolbar={
          <>
            <span className="text-[11px] tabular-nums text-text-subtlest">30-day snapshot</span>
            <SnapshotPill />
          </>
        }
      >
        <LivelineTrend
          series={series}
          labels={labels}
          height={180}
          formatValue={(v) => String(Math.round(v))}
          formatTime={(i) => labels[i] ?? ""}
        />
      </ChartStage>
    </ChartCard>
  );
}
