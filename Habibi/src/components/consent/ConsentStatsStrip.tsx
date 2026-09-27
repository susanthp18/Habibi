import { Users, ShieldOff, Ban, CalendarX, AlertTriangle } from "lucide-react";
import type { ConsentStats } from "@/api/consent";
import { MetricsStrip } from "@/components/records/MetricsStrip";

/** Counts over the whole registry (GET /consent/stats), not the loaded page. */
export function ConsentStatsStrip({ stats }: { stats: ConsentStats | undefined }) {
  const n = (v: number | undefined) => (v === undefined ? "—" : v);
  return (
    <MetricsStrip
      className="gap-150 border-b border-border bg-surface px-250 py-150"
      tiles={[
        {
          icon: Users,
          label: "Customers",
          value: n(stats?.customers),
          sub: "in registry",
          tone: "brand",
        },
        {
          icon: ShieldOff,
          label: "DND active",
          value: n(stats?.dnd),
          sub: "registry or channel-level",
          tone: "warning",
        },
        {
          icon: Ban,
          label: "Opt-outs (30d)",
          value: n(stats?.optOuts30d),
          sub: "captured across channels",
          tone: "brand",
        },
        {
          icon: CalendarX,
          label: "Expiring ≤30d",
          value: n(stats?.expiring),
          sub: "renewal required",
          tone: (stats?.expiring ?? 0) > 3 ? "warning" : "brand",
        },
        {
          icon: AlertTriangle,
          label: "Frequency caps hit",
          value: n(stats?.capsHit),
          sub: "paused for the week",
          tone: (stats?.capsHit ?? 0) > 0 ? "danger" : "brand",
        },
      ]}
    />
  );
}
