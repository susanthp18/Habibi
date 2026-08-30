import { Sparkline } from "./Sparkline";
import { DeltaChip } from "./DeltaChip";
import type { HeroKpi } from "@/data/dashboard-seed";
import { Star } from "lucide-react";

export function HeroKpiCard({ kpi }: { kpi: HeroKpi }) {
  return (
    <div className="relative flex flex-col justify-between overflow-hidden rounded-large border border-border-brand/40 bg-surface p-250">
      <span className="pointer-events-none absolute inset-x-0 top-0 h-050 bg-background-brand-bold" />
      <div className="flex items-start justify-between">
        <div>
          <div className="mb-050 flex items-center gap-075">
            <Star className="h-3.5 w-3.5 fill-icon-brand text-text-brand" />
            <span className="text-body-small font-medium text-text-brand">North-star metric</span>
          </div>
          <div className="text-sm font-medium text-text-subtle">{kpi.label}</div>
        </div>
        <DeltaChip value={kpi.delta} good={kpi.deltaGood} />
      </div>

      <div className="mt-150 flex items-end justify-between">
        <div>
          <div className="text-3xl font-semibold text-text tabular">{kpi.value}</div>
          <div className="mt-050 text-xs text-text-subtlest">{kpi.sub}</div>
        </div>
        <div className="w-[8.75rem] overflow-hidden rounded-medium bg-surface-sunken">
          <Sparkline data={kpi.spark} width={140} height={44} />
        </div>
      </div>
    </div>
  );
}
