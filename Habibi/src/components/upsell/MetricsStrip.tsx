import { Sparkles, Wallet, Trophy, TrendingUp, Timer } from "lucide-react";
import { fmtMoney } from "@/data/upsell-seed";
import type { LeadMetrics } from "@/api/upsell";

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

export function MetricsStrip({ m }: { m?: LeadMetrics }) {
  return (
    <div className="grid shrink-0 grid-cols-2 gap-150 md:grid-cols-3 xl:grid-cols-5">
      <Tile label="Open leads" value={num(m?.openLeads)} sub="Interested + Contacted + Qualified" icon={Sparkles} tone="brand" />
      <Tile
        label="Pipeline value"
        value={m ? fmtMoney(m.pipelineValue) : "—"}
        sub="Open leads (indicative)"
        icon={Wallet}
        tone="violet"
      />
      <Tile
        label="Won (7d)"
        value={num(m?.wonWeek)}
        sub={m ? fmtMoney(m.wonWeekAmount) : undefined}
        icon={Trophy}
        tone="green"
      />
      {/* A null rate is a zero denominator, not a zero rate. "Nothing was
          captured this month" and "none of what we captured converted" call
          for opposite responses, and rendering both as 0% is how a quiet
          month looks identical to a broken pipeline. */}
      <Tile
        label="Conversion (30d)"
        value={m?.conversionRate == null ? "—" : `${m.conversionRate}%`}
        sub={m ? `${m.won30d} won / ${m.captured30d} captured` : "Won / captured"}
        icon={TrendingUp}
        tone="amber"
      />
      <Tile
        label="Avg time-to-close"
        value={m?.avgDaysToClose == null ? "—" : `${m.avgDaysToClose}d`}
        sub="Won + Lost, all-time"
        icon={Timer}
      />
    </div>
  );
}

function num(value: number | undefined): string {
  return value === undefined ? "—" : String(value);
}
