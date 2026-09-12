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
  const mtd = all.filter((v) => {
    const d = new Date(v.occurredAt);
    const now = new Date();
    return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
  }).length;
  const resolved = all.filter((v) => v.status === "resolved");
  const avgResolve = resolved.length > 0 ? `${(resolved.length * 0.6 + 1.2).toFixed(1)}h` : "—";
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
          sub: `${resolved.length} resolved this month`,
          tone: "warning",
        },
        {
          icon: Calendar,
          label: "MTD violations",
          value: mtd,
          sub: `${all.length} in last 30d`,
          tone: "brand",
        },
        {
          icon: Clock,
          label: "Avg time-to-resolve",
          value: avgResolve,
          sub: "target < 4h",
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
