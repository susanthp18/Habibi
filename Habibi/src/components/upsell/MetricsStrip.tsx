import { Sparkles, Wallet, Trophy, TrendingUp, Timer } from "lucide-react";
import { fmtMoney, type Metrics } from "@/data/upsell-seed";

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
  tone?: "default" | "brand" | "amber" | "green" | "violet";
}) {
  const toneClass = {
    default: "bg-surface-card border-[var(--border-token)]",
    brand: "bg-brand-tint/50 border-brand-primary/20",
    amber: "bg-amber-50 border-amber-200",
    green: "bg-emerald-50 border-emerald-200",
    violet: "bg-violet-50 border-violet-200",
  }[tone];
  const iconTone = {
    default: "text-text-secondary",
    brand: "text-brand-primary",
    amber: "text-amber-600",
    green: "text-emerald-600",
    violet: "text-violet-600",
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
      <Tile label="Open leads" value={String(m.openLeads)} sub="Interested + Contacted + Qualified" icon={Sparkles} tone="brand" />
      <Tile label="Pipeline value" value={fmtMoney(m.pipelineValue)} sub="Open leads (indicative)" icon={Wallet} tone="violet" />
      <Tile label="Won (7d)" value={String(m.wonWeek)} sub={fmtMoney(m.wonWeekAmount)} icon={Trophy} tone="green" />
      <Tile label="Conversion (30d)" value={`${m.conversionRate}%`} sub="Won / captured" icon={TrendingUp} tone="amber" />
      <Tile label="Avg time-to-close" value={`${m.avgDaysToClose}d`} sub="Won + Lost, all-time" icon={Timer} />
    </div>
  );
}
