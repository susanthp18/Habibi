import { TrendingUp, Clock, AlertTriangle, HandCoins, Timer } from "lucide-react";
import { fmtMoney } from "@/data/promises-seed";

interface Metrics {
  keptRate: number;
  activeCount: number;
  activeAmt: number;
  dueTodayCount: number;
  dueTodayAmt: number;
  atRiskAmt: number;
  avgDays: number;
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
        label="Promise-kept rate"
        value={`${m.keptRate}%`}
        sub="30-day rolling"
        icon={TrendingUp}
        tone="brand"
      />
      <Tile
        label="Active promises"
        value={fmtMoney(m.activeAmt)}
        sub={`${m.activeCount} open`}
        icon={HandCoins}
      />
      <Tile
        label="Due today"
        value={fmtMoney(m.dueTodayAmt)}
        sub={`${m.dueTodayCount} promise${m.dueTodayCount === 1 ? "" : "s"}`}
        icon={Clock}
        tone="amber"
      />
      <Tile
        label="At-risk"
        value={fmtMoney(m.atRiskAmt)}
        sub="Broken + partial balance"
        icon={AlertTriangle}
        tone="red"
      />
      <Tile
        label="Avg days-to-keep"
        value={`${m.avgDays}d`}
        sub="From capture → payment"
        icon={Timer}
        tone="green"
      />
    </div>
  );
}
