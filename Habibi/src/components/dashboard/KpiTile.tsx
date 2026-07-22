import { Sparkline } from "./Sparkline";
import { DeltaChip } from "./DeltaChip";
import type { Kpi } from "@/data/dashboard-seed";
import { cn } from "@/lib/utils";

const toneMap: Record<NonNullable<Kpi["tone"]>, { stroke: string; fill: string; accent: string }> = {
  default: { stroke: "var(--brand-primary)", fill: "rgba(24,119,242,0.10)", accent: "text-brand-navy" },
  brand: { stroke: "var(--brand-primary)", fill: "rgba(24,119,242,0.14)", accent: "text-brand-primary" },
  success: { stroke: "var(--success)", fill: "rgba(46,125,50,0.12)", accent: "text-success" },
  warning: { stroke: "var(--warning)", fill: "rgba(249,168,37,0.14)", accent: "text-warning" },
};

export function KpiTile({ kpi }: { kpi: Kpi }) {
  const tone = toneMap[kpi.tone ?? "default"];
  return (
    <div className="flex flex-col justify-between rounded-lg border border-border bg-surface-card p-4 shadow-card">
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-medium text-text-secondary">{kpi.label}</span>
        <DeltaChip value={kpi.delta} good={kpi.deltaGood} />
      </div>
      <div className="mt-2 flex items-end justify-between gap-2">
        <span className={cn("text-2xl font-semibold tabular", tone.accent)}>{kpi.value}</span>
        <Sparkline data={kpi.spark} width={80} height={28} stroke={tone.stroke} fill={tone.fill} />
      </div>
    </div>
  );
}
