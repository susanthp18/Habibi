import type { Trend } from "@/api/types/dashboard";
import { inrCompact } from "@/lib/format";
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
          <div className="text-body font-semibold text-text tabular-nums">{inrCompact(total)}</div>
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
            formatValue={inrCompact}
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
