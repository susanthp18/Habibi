import { Users, ShieldOff, Ban, CalendarX, AlertTriangle } from "lucide-react";
import type { ConsentRecord } from "@/api/types/consent";
import { MetricsStrip } from "@/components/records/MetricsStrip";
import { daysUntil } from "@/lib/consent";

export function ConsentStatsStrip({ all }: { all: ConsentRecord[] }) {
  const total = all.length;
  const dnd = all.filter(
    (r) => r.onDndRegistry || r.channels.some((c) => c.status === "dnd"),
  ).length;
  const optOuts30d = all.reduce(
    (n, r) =>
      n + r.optOutLog.filter((e) => Date.now() - new Date(e.at).getTime() < 30 * 86400000).length,
    0,
  );
  const expiring = all.filter((r) => {
    const d = daysUntil(r.consentExpiresAt);
    return d <= 30;
  }).length;
  const capBreach = all.filter((r) =>
    r.channels.some((c) => c.usedThisWeek >= c.frequencyCapPerWeek && c.status === "opted_in"),
  ).length;

  return (
    <MetricsStrip
      className="gap-150 border-b border-border bg-surface px-250 py-150"
      tiles={[
        { icon: Users, label: "Customers", value: total, sub: "in registry", tone: "brand" },
        {
          icon: ShieldOff,
          label: "DND active",
          value: dnd,
          sub: "registry or channel-level",
          tone: "warning",
        },
        {
          icon: Ban,
          label: "Opt-outs (30d)",
          value: optOuts30d,
          sub: "captured across channels",
          tone: "brand",
        },
        {
          icon: CalendarX,
          label: "Expiring ≤30d",
          value: expiring,
          sub: "renewal required",
          tone: expiring > 3 ? "warning" : "brand",
        },
        {
          icon: AlertTriangle,
          label: "Frequency caps hit",
          value: capBreach,
          sub: "paused for the week",
          tone: capBreach > 0 ? "danger" : "brand",
        },
      ]}
    />
  );
}
