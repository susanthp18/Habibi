import type { Violation } from "@/api/types/compliance";
import { trendByDay } from "@/lib/compliance";
import { ChartCard, ChartStage, LivelineTrend, SnapshotPill } from "@/components/charts";

// Tokens, so the lines follow the theme; a dash per severity, so the four
// are told apart without colour.
const SERIES = [
  { id: "critical", label: "Critical", color: "var(--chart-red-bolder)", key: "critical" as const },
  {
    id: "high",
    label: "High",
    color: "var(--chart-orange-bold)",
    dash: "6 3",
    key: "high" as const,
  },
  {
    id: "medium",
    label: "Medium",
    color: "var(--chart-yellow-bold)",
    dash: "2 3",
    key: "medium" as const,
  },
  { id: "low", label: "Low", color: "var(--chart-gray-bolder)", dash: "1 4", key: "low" as const },
];

export function ViolationTrendChart({ all }: { all: Violation[] }) {
  const data = trendByDay(all, 30);
  const labels = data.map((d) => d.day);
  const series = SERIES.map((s) => ({
    id: s.id,
    label: s.label,
    color: s.color,
    dash: s.dash,
    values: data.map((d) => d[s.key]),
  }));

  return (
    <ChartCard
      title="Violation trend"
      subtitle="Last 30 days · by severity"
      action={
        <div className="flex flex-wrap items-center gap-100 text-body-tiny text-text-subtle">
          {SERIES.map((s) => (
            <span key={s.id} className="inline-flex items-center gap-050">
              <svg width="18" height="6" aria-hidden className="shrink-0">
                <line
                  x1="0"
                  y1="3"
                  x2="18"
                  y2="3"
                  stroke={s.color}
                  strokeWidth={2}
                  strokeDasharray={s.dash}
                  strokeLinecap="round"
                />
              </svg>
              {s.label}
            </span>
          ))}
        </div>
      }
    >
      <ChartStage
        toolbar={
          <>
            <span className="text-body-tiny tabular-nums text-text-subtlest">30-day snapshot</span>
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
