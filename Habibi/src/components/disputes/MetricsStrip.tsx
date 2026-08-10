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
    default: "bg-surface border-border",
    brand: "bg-background-brand-subtlest/50 border-border-brand/20",
    amber: "bg-background-warning-subtler border-border-warning-subtle",
    red: "bg-background-danger-subtler border-border-danger-subtle",
    green: "bg-background-success-subtler border-border-success-subtle",
  }[tone];
  const iconTone = {
    default: "text-text-subtle",
    brand: "text-text-brand",
    amber: "text-text-warning",
    red: "text-text-danger",
    green: "text-text-success",
  }[tone];
  return (
    <div className={`rounded-large border px-200 py-150 ${toneClass}`}>
      <div className="flex items-center justify-between">
        <div className="text-body-small font-semibold text-text-subtlest">{label}</div>
        <Icon className={`h-4 w-4 ${iconTone}`} />
      </div>
      <div className="mt-050 text-[1.5rem] font-semibold leading-tight text-text tabular-nums">{value}</div>
      {sub && <div className="text-body-small text-text-subtle">{sub}</div>}
    </div>
  );
}

export function MetricsStrip({ m }: { m: Metrics }) {
  return (
    <div className="grid grid-cols-2 gap-150 md:grid-cols-3 xl:grid-cols-5">
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
