import type { Trend } from "@/data/dashboard-seed";
import {
  ChartCard,
  ChartEmpty,
  ChartStage,
  LivelineTrend,
  SnapshotPill,
} from "@/components/charts";

function fmtDate(d: string) {
  const dt = new Date(d);
  return dt.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function fmtMoney(n: number) {
  if (Math.abs(n) >= 10_000_000) return `₹${(n / 10_000_000).toFixed(1)} Cr`;
  if (Math.abs(n) >= 100_000) return `₹${(n / 100_000).toFixed(1)} L`;
  if (Math.abs(n) >= 1_000) return `₹${(n / 1_000).toFixed(0)}K`;
  return `₹${n.toFixed(0)}`;
}

export function RecoveryTrendChart({ data }: { data: Trend[] }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  const values = data.map((d) => d.value);
  const labels = data.map((d) => d.date);

  return (
    <ChartCard
      title="Recovery over time"
      subtitle="Payments posted in the selected period"
      action={
        <div className="text-right">
          <div className="text-body-micro text-text-subtlest">Period total</div>
          <div className="text-body font-semibold text-text tabular-nums">{fmtMoney(total)}</div>
        </div>
      }
    >
      <ChartStage
        className="min-h-0 flex-1"
        toolbar={
          <>
            <span className="text-body-tiny tabular-nums text-text-subtlest">Trend snapshot</span>
            <SnapshotPill />
          </>
        }
      >
        {data.length === 0 ? (
          <ChartEmpty>No payments recorded in this period.</ChartEmpty>
        ) : (
          <LivelineTrend
            values={values}
            labels={labels}
            color="#1868db"
            height={200}
            formatValue={fmtMoney}
            formatTime={(i) => fmtDate(labels[i] ?? "")}
            fill
            grid={false}
            className="h-full min-h-[12rem]"
          />
        )}
      </ChartStage>
    </ChartCard>
  );
}
