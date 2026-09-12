import { Sparkles, Timer, TrendingUp, Trophy, Wallet } from "lucide-react";
import { MetricsStrip as Strip } from "@/components/records/MetricsStrip";
import { fmtMoney } from "@/lib/upsell";
import type { LeadMetrics } from "@/api/upsell";

function num(value: number | undefined): string {
  return value === undefined ? "—" : String(value);
}

export function MetricsStrip({ m }: { m?: LeadMetrics }) {
  return (
    <Strip
      className="gap-150"
      tiles={[
        {
          label: "Open leads",
          value: num(m?.openLeads),
          sub: "Interested + Contacted + Qualified",
          icon: Sparkles,
          tone: "brand",
        },
        {
          label: "Pipeline value",
          value: m ? fmtMoney(m.pipelineValue) : "—",
          sub: "Open leads (indicative)",
          icon: Wallet,
          tone: "discovery",
        },
        {
          label: "Won (7d)",
          value: num(m?.wonWeek),
          sub: m ? fmtMoney(m.wonWeekAmount) : undefined,
          icon: Trophy,
          tone: "success",
        },
        // A null rate is a zero denominator, not a zero rate. "Nothing was
        // captured this month" and "none of what we captured converted" call
        // for opposite responses, and rendering both as 0% is how a quiet
        // month looks identical to a broken pipeline.
        {
          label: "Conversion (30d)",
          value: m?.conversionRate == null ? "—" : `${m.conversionRate}%`,
          sub: m ? `${m.won30d} won / ${m.captured30d} captured` : "Won / captured",
          icon: TrendingUp,
          tone: "warning",
        },
        {
          label: "Avg time-to-close",
          value: m?.avgDaysToClose == null ? "—" : `${m.avgDaysToClose}d`,
          sub: "Won + Lost, all-time",
          icon: Timer,
        },
      ]}
    />
  );
}
