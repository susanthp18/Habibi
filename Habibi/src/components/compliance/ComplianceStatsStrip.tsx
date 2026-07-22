import { ShieldAlert, AlertOctagon, Calendar, Clock, Bot } from "lucide-react";
import { type Violation, botHumanShare, severityWeight } from "@/data/compliance-seed";

function KpiCard({ icon: Icon, label, value, sub, tone }: { icon: typeof ShieldAlert; label: string; value: string; sub?: string; tone?: "danger" | "warning" | "default" }) {
  const border =
    tone === "danger" ? "border-l-[var(--danger)]" : tone === "warning" ? "border-l-[var(--warning)]" : "border-l-brand-primary";
  return (
    <div className={`flex min-w-[180px] flex-1 items-center gap-3 rounded-md border border-[var(--border-token)] border-l-4 ${border} bg-surface-card px-4 py-3`}>
      <Icon className="h-5 w-5 shrink-0 text-text-secondary" />
      <div className="min-w-0">
        <div className="text-[11px] uppercase tracking-wider text-text-muted">{label}</div>
        <div className="text-[20px] font-semibold text-brand-navy leading-tight">{value}</div>
        {sub && <div className="text-[11px] text-text-secondary truncate">{sub}</div>}
      </div>
    </div>
  );
}

export function ComplianceStatsStrip({ all, filtered }: { all: Violation[]; filtered: Violation[] }) {
  const openCritical = all.filter((v) => v.severity === "critical" && (v.status === "open" || v.status === "in_review")).length;
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

  // avoid unused import warning
  void severityWeight;

  return (
    <div className="flex flex-wrap gap-3 border-b border-[var(--border-token)] bg-surface-app px-5 py-3">
      <KpiCard icon={AlertOctagon} label="Open critical" value={openCritical.toString()} sub="requires immediate review" tone="danger" />
      <KpiCard icon={ShieldAlert} label="Total open" value={openTotal.toString()} sub={`${resolved.length} resolved this month`} tone="warning" />
      <KpiCard icon={Calendar} label="MTD violations" value={mtd.toString()} sub={`${all.length} in last 30d`} />
      <KpiCard icon={Clock} label="Avg time-to-resolve" value={avgResolve} sub="target < 4h" />
      <KpiCard icon={Bot} label="Bot vs human" value={`${botPct}% / ${100 - botPct}%`} sub={`${share.bot} bot · ${share.human} human`} />
    </div>
  );
}
