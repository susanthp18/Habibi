import { AlertOctagon, TimerReset, Timer, CheckCircle2, TrendingUp } from "lucide-react";
import { fmtMoney } from "@/data/disputes-seed";

interface Metrics {
  openCount: number;
  openAmt: number;
  breachingCount: number;
  avgAgeHrs: number;
  resolvedToday: number;
  resolutionRate: number;
}

function Tile({
  label,
  value,
  sub,
  icon: Icon,
  tone = "default",
}: {
  label: string;
  value: string;
  sub?: string;
  icon: React.ComponentType<{ className?: string }>;
  tone?: "default" | "amber" | "red" | "brand" | "green";
}) {
  const toneClass = {
    default: "bg-surface-card border-[var(--border-token)]",
    brand: "bg-brand-tint/50 border-brand-primary/20",
    amber: "bg-amber-50 border-amber-200",
    red: "bg-red-50 border-red-200",
    green: "bg-emerald-50 border-emerald-200",
  }[tone];
  const iconTone = {
    default: "text-text-secondary",
    brand: "text-brand-primary",
    amber: "text-amber-600",
    red: "text-red-600",
    green: "text-emerald-600",
  }[tone];
  return (
    <div className={`rounded-lg border px-4 py-3 ${toneClass}`}>
      <div className="flex items-center justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">{label}</div>
        <Icon className={`h-4 w-4 ${iconTone}`} />
      </div>
      <div className="mt-1 text-[22px] font-semibold leading-tight text-brand-navy tabular-nums">{value}</div>
      {sub && <div className="text-[11px] text-text-secondary">{sub}</div>}
    </div>
  );
}

export function MetricsStrip({ m }: { m: Metrics }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      <Tile
        label="Open disputes"
        value={String(m.openCount)}
        sub={fmtMoney(m.openAmt)}
        icon={AlertOctagon}
        tone="brand"
      />
      <Tile
        label="Breaching SLA"
        value={String(m.breachingCount)}
        sub="Past due window"
        icon={TimerReset}
        tone="red"
      />
      <Tile
        label="Avg age"
        value={`${m.avgAgeHrs}h`}
        sub="Open dispute age"
        icon={Timer}
        tone="amber"
      />
      <Tile
        label="Resolved today"
        value={String(m.resolvedToday)}
        sub="Rolling 24h"
        icon={CheckCircle2}
        tone="green"
      />
      <Tile
        label="Resolution rate"
        value={`${m.resolutionRate}%`}
        sub="Last 7 days"
        icon={TrendingUp}
      />
    </div>
  );
}
