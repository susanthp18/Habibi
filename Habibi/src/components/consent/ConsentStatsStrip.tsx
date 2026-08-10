import { Users, ShieldOff, Ban, CalendarX, AlertTriangle, type LucideIcon } from "lucide-react";
import { contactableSummary, type ConsentRecord, daysUntil } from "@/data/consent-seed";

function KpiCard({ icon: Icon, label, value, sub, tone }: { icon: LucideIcon; label: string; value: string; sub?: string; tone?: "danger" | "warning" | "default" }) {
  const border =
    tone === "danger" ? "border-l-[var(--danger)]" : tone === "warning" ? "border-l-[var(--warning)]" : "border-l-border-brand";
  return (
    <div className={`flex min-w-[10.625rem] flex-1 items-center gap-150 rounded-medium border border-border border-l-4 ${border} bg-surface px-200 py-150`}>
      <Icon className="h-250 w-250 shrink-0 text-text-subtle" />
      <div className="min-w-0">
        <div className="text-body-small text-text-subtlest">{label}</div>
        <div className="text-[1.25rem] font-semibold text-text leading-tight">{value}</div>
        {sub && <div className="text-body-small text-text-subtle truncate">{sub}</div>}
      </div>
    </div>
  );
}

export function ConsentStatsStrip({ all }: { all: ConsentRecord[] }) {
  const total = all.length;
  const dnd = all.filter((r) => r.onDndRegistry || r.channels.some((c) => c.status === "dnd")).length;
  const optOuts30d = all.reduce(
    (n, r) => n + r.optOutLog.filter((e) => Date.now() - new Date(e.at).getTime() < 30 * 86400000).length,
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
    <div className="flex flex-wrap gap-150 border-b border-border bg-surface px-250 py-150">
      <KpiCard icon={Users} label="Customers" value={total.toString()} sub="in registry" />
      <KpiCard icon={ShieldOff} label="DND active" value={dnd.toString()} sub="registry or channel-level" tone="warning" />
      <KpiCard icon={Ban} label="Opt-outs (30d)" value={optOuts30d.toString()} sub="captured across channels" />
      <KpiCard icon={CalendarX} label="Expiring ≤30d" value={expiring.toString()} sub="renewal required" tone={expiring > 3 ? "warning" : "default"} />
      <KpiCard icon={AlertTriangle} label="Frequency caps hit" value={capBreach.toString()} sub="paused for the week" tone={capBreach > 0 ? "danger" : "default"} />
    </div>
  );
}
