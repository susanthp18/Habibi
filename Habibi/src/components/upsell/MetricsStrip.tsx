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
    default: "bg-surface border-border",
    brand: "bg-background-brand-subtlest/50 border-border-brand/20",
    amber: "bg-background-warning-subtler border-border-warning-subtle",
    green: "bg-background-success-subtler border-border-success-subtle",
    violet: "bg-background-discovery-subtler border-border-discovery-subtle",
  }[tone];
  const iconTone = {
    default: "text-text-subtle",
    brand: "text-text-brand",
    amber: "text-text-warning",
    green: "text-text-success",
    violet: "text-text-discovery",
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
      <Tile label="Open leads" value={String(m.openLeads)} sub="Interested + Contacted + Qualified" icon={Sparkles} tone="brand" />
      <Tile label="Pipeline value" value={fmtMoney(m.pipelineValue)} sub="Open leads (indicative)" icon={Wallet} tone="violet" />
      <Tile label="Won (7d)" value={String(m.wonWeek)} sub={fmtMoney(m.wonWeekAmount)} icon={Trophy} tone="green" />
      <Tile label="Conversion (30d)" value={`${m.conversionRate}%`} sub="Won / captured" icon={TrendingUp} tone="amber" />
      <Tile label="Avg time-to-close" value={`${m.avgDaysToClose}d`} sub="Won + Lost, all-time" icon={Timer} />
    </div>
  );
}
