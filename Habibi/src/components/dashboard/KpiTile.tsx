import { Sparkline } from "./Sparkline";
import { DeltaChip } from "./DeltaChip";
import type { Kpi } from "@/data/dashboard-seed";
import { cn } from "@/lib/utils";

const toneMap: Record<
  NonNullable<Kpi["tone"]>,
  { stroke: string; fill: string; accent: string }
> = {
  default: {
    stroke: "var(--background-brand-bold)",
    fill: "rgba(24,104,219,0.10)",
    accent: "text-text",
  },
  brand: {
    stroke: "var(--background-brand-bold)",
    fill: "rgba(24,104,219,0.14)",
    accent: "text-text-brand",
  },
  success: {
    stroke: "var(--text-text-success)",
    fill: "rgba(76,107,31,0.12)",
    accent: "text-text-success",
  },
  warning: {
    stroke: "var(--text-text-warning)",
    fill: "rgba(158,76,0,0.14)",
    accent: "text-text-warning",
  },
};

export function KpiTile({ kpi }: { kpi: Kpi }) {
  const tone = toneMap[kpi.tone ?? "default"];
  return (
    <div className="flex flex-col justify-between rounded-large border border-border bg-surface p-200">
      <div className="flex items-start justify-between gap-100">
        <span className="text-xs font-medium text-text-subtle">{kpi.label}</span>
        <DeltaChip value={kpi.delta} good={kpi.deltaGood} />
      </div>
      <div className="mt-100 flex items-end justify-between gap-100">
        <span className={cn("text-2xl font-semibold tabular", tone.accent)}>{kpi.value}</span>
        {kpi.spark.length > 0 && (
          <div className="w-20 overflow-hidden rounded-medium bg-surface-sunken">
            <Sparkline
              data={kpi.spark}
              width={80}
              height={28}
              stroke={tone.stroke}
              fill={tone.fill}
            />
          </div>
        )}
      </div>
      {/* How the number was computed — a rate whose formula only exists in a
          query is a rate nobody on the floor can check. */}
      {kpi.sub && <div className="mt-050 text-body-small text-text-subtlest">{kpi.sub}</div>}
    </div>
  );
}
