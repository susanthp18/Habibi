import type { TurnsBucket } from "@/data/bot-analytics-seed";
import { ChartCard, ChartStage, ModernBars, SnapshotPill } from "@/components/charts";

const COLORS = ["#82b536", "#5b7f24", "#f68909", "#bd5b00", "#e2483d"];

export function TurnsHistogram({ buckets }: { buckets: TurnsBucket[] }) {
  const data = buckets.map((b, i) => ({
    label: b.label,
    value: b.count,
    color: COLORS[i % COLORS.length],
  }));
  const total = data.reduce((a, b) => a + b.value, 0);

  return (
    <ChartCard
      title="Turns to resolution"
      subtitle={`${total.toLocaleString()} sessions · fewer turns = better`}
      action={<SnapshotPill />}
    >
      <ChartStage>
        <div className="min-h-[14rem] p-150">
          <ModernBars data={data} height={200} />
        </div>
      </ChartStage>
    </ChartCard>
  );
}
