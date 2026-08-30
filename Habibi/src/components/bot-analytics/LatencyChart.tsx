import type { DailyPoint } from "@/data/bot-analytics-seed";
import { VOICE_TTFA_SLO_MS } from "@/data/bot-analytics-seed";
import { ChartCard, ChartStage, LivelineTrend, SnapshotPill } from "@/components/charts";

export function LatencyChart({ points }: { points: DailyPoint[] }) {
  const labels = points.map((p) => p.date.slice(5));
  const series = [
    {
      id: "p50",
      label: "p50",
      values: points.map((p) => Math.round(p.latencyP50)),
      color: "#82b536",
    },
    {
      id: "p90",
      label: "p90",
      values: points.map((p) => Math.round(p.latencyP90)),
      color: "#f68909",
    },
    {
      id: "p99",
      label: "p99",
      values: points.map((p) => Math.round(p.latencyP99)),
      color: "#e2483d",
    },
  ];

  return (
    <ChartCard
      title="Response latency"
      subtitle={`p50 / p90 / p99 in ms · voice SLO ${VOICE_TTFA_SLO_MS} ms user-stop → first audio`}
      action={<SnapshotPill />}
    >
      <div className="mb-100 flex flex-wrap gap-150 text-body-tiny text-text-subtle">
        {series.map((s) => (
          <span key={s.id} className="inline-flex items-center gap-050">
            <span className="size-1.5 rounded-full" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
      <ChartStage>
        <LivelineTrend
          series={series}
          labels={labels}
          height={200}
          formatValue={(v) => `${Math.round(v)} ms`}
          formatTime={(i) => labels[i] ?? ""}
        />
      </ChartStage>
    </ChartCard>
  );
}
