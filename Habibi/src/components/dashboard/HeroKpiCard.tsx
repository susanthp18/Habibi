import { Sparkline } from "./Sparkline";
import { DeltaChip } from "./DeltaChip";
import type { HeroKpi } from "@/data/dashboard-seed";
import { Star } from "lucide-react";

export function HeroKpiCard({ kpi }: { kpi: HeroKpi }) {
  return (
    <div className="relative flex flex-col justify-between overflow-hidden rounded-lg border border-brand-primary/40 bg-surface-card p-5 shadow-card">
      <span className="pointer-events-none absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-brand-primary to-brand-primary-dark" />
      <div className="flex items-start justify-between">
        <div>
          <div className="mb-1 flex items-center gap-1.5">
            <Star className="h-3.5 w-3.5 fill-brand-primary text-brand-primary" />
            <span className="text-[11px] font-semibold uppercase tracking-wide text-brand-primary">
              North-Star Metric
            </span>
          </div>
          <div className="text-sm font-medium text-text-secondary">{kpi.label}</div>
        </div>
        <DeltaChip value={kpi.delta} good={kpi.deltaGood} />
      </div>

      <div className="mt-3 flex items-end justify-between">
        <div>
          <div className="text-3xl font-semibold text-brand-navy tabular">{kpi.value}</div>
          <div className="mt-1 text-xs text-text-muted">{kpi.sub}</div>
        </div>
        <Sparkline data={kpi.spark} width={140} height={44} />
      </div>
    </div>
  );
}
