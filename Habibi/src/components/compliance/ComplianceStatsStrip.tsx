import { ShieldAlert, AlertOctagon, Calendar, Clock, Bot } from "lucide-react";
import type { Violation } from "@/api/types/compliance";
import { MetricsStrip } from "@/components/records/MetricsStrip";
import { botHumanShare } from "@/lib/compliance";

export function ComplianceStatsStrip({
  all,
  filtered,
}: {
  all: Violation[];
  filtered: Violation[];
}) {
  const openCritical = all.filter(
    (v) => v.severity === "critical" && (v.status === "open" || v.status === "in_review"),
  ).length;
  const openTotal = all.filter((v) => v.status === "open" || v.status === "in_review").length;
  const now = new Date();
  const thisMonth = (iso?: string | null) => {
    if (!iso) return false;
    const d = new Date(iso);
    return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
  };
  const mtd = all.filter((v) => thisMonth(v.occurredAt)).length;
  const last30 = all.filter(
    (v) => now.getTime() - new Date(v.occurredAt).getTime() <= 30 * 86_400_000,
  ).length;
  const resolvedThisMonth = all.filter(
    (v) => v.status === "resolved" && thisMonth(v.resolvedAt),
  ).length;
  // Measured: from when the violation happened to its "resolved" action.
  const hours = all
    .filter((v) => v.status === "resolved" && v.resolvedAt)
    .map((v) => (new Date(v.resolvedAt!).getTime() - new Date(v.occurredAt).getTime()) / 3_600_000)
    .filter((h) => h >= 0);
  const avgResolve = hours.length
    ? `${(hours.reduce((a, b) => a + b, 0) / hours.length).toFixed(1)}h`
    : "—";
  const share = botHumanShare(filtered);
  const total = share.bot + share.human || 1;
  const botPct = Math.round((share.bot / total) * 100);

  return (
    <MetricsStrip
      className="gap-150 border-b border-border bg-surface px-250 py-150"
      tiles={[
        {
          icon: AlertOctagon,
          label: "Open critical",
          value: openCritical,
          sub: "requires immediate review",
          tone: "danger",
        },
        {
          icon: ShieldAlert,
          label: "Total open",
          value: openTotal,
          sub: `${resolvedThisMonth} resolved this month`,
          tone: "warning",
        },
        {
          icon: Calendar,
          label: "MTD violations",
          value: mtd,
          sub: `${last30} in last 30d`,
          tone: "brand",
        },
        {
          icon: Clock,
          label: "Avg time-to-resolve",
          value: avgResolve,
          sub: hours.length ? `over ${hours.length} resolved · target < 4h` : "none resolved yet",
          tone: "brand",
        },
        {
          icon: Bot,
          label: "Bot vs human",
          value: `${botPct}% / ${100 - botPct}%`,
          sub: `${share.bot} bot · ${share.human} human`,
          tone: "brand",
        },
      ]}
    />
  );
}
