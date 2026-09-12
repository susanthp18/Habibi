import { AlertOctagon, CheckCircle2, Timer, TimerReset, TrendingUp } from "lucide-react";
import { MetricsStrip as Strip } from "@/components/records/MetricsStrip";
import { fmtMoney } from "@/lib/format";

interface Metrics {
  openCount: number;
  openAmt: number;
  breachingCount: number;
  avgAgeHrs: number;
  resolvedToday: number;
  resolutionRate: number;
}

export function MetricsStrip({ m }: { m: Metrics }) {
  return (
    <Strip
      className="gap-150"
      tiles={[
        {
          label: "Open disputes",
          value: String(m.openCount),
          sub: fmtMoney(m.openAmt),
          icon: AlertOctagon,
          tone: "brand",
        },
        {
          label: "Breaching SLA",
          value: String(m.breachingCount),
          sub: "Past due window",
          icon: TimerReset,
          tone: "danger",
        },
        {
          label: "Avg age",
          value: `${m.avgAgeHrs}h`,
          sub: "Open dispute age",
          icon: Timer,
          tone: "warning",
        },
        {
          label: "Resolved today",
          value: String(m.resolvedToday),
          sub: "Rolling 24h",
          icon: CheckCircle2,
          tone: "success",
        },
        {
          label: "Resolution rate",
          value: `${m.resolutionRate}%`,
          sub: "Last 7 days",
          icon: TrendingUp,
        },
      ]}
    />
  );
}
