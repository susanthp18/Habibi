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
      <div className="mt-050 heading-large font-semibold leading-tight text-text tabular-nums">
        {value}
      </div>
      {sub && <div className="text-body-small text-text-subtle">{sub}</div>}
    </div>
  );
}

export function MetricsStrip({ m }: { m: Metrics }) {
  return (
    <div className="grid grid-cols-2 gap-150 md:grid-cols-3 xl:grid-cols-5">
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
