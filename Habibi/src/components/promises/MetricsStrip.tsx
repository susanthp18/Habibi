import { AlertTriangle, Clock, HandCoins, Timer, TrendingUp } from "lucide-react";
import { MetricsStrip as Strip } from "@/components/records/MetricsStrip";
import { fmtMoney } from "@/lib/format";

interface Metrics {
  keptRate: number;
  activeCount: number;
  activeAmt: number;
  dueTodayCount: number;
  dueTodayAmt: number;
  atRiskAmt: number;
  avgDays: number;
}

export function MetricsStrip({ m }: { m: Metrics }) {
  return (
    <Strip
      className="gap-150"
      tiles={[
        {
          label: "Promise-kept rate",
          value: `${m.keptRate}%`,
          sub: "30-day rolling",
          icon: TrendingUp,
          tone: "brand",
        },
        {
          label: "Active promises",
          value: fmtMoney(m.activeAmt),
          sub: `${m.activeCount} open`,
          icon: HandCoins,
        },
        {
          label: "Due today",
          value: fmtMoney(m.dueTodayAmt),
          sub: `${m.dueTodayCount} promise${m.dueTodayCount === 1 ? "" : "s"}`,
          icon: Clock,
          tone: "warning",
        },
        {
          label: "At-risk",
          value: fmtMoney(m.atRiskAmt),
          sub: "Broken + partial balance",
          icon: AlertTriangle,
          tone: "danger",
        },
        {
          label: "Avg days-to-keep",
          value: `${m.avgDays}d`,
          sub: "From capture → payment",
          icon: Timer,
          tone: "success",
        },
      ]}
    />
  );
}
