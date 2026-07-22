import { AlertOctagon, CalendarClock, HandCoins, ShieldCheck, User2 } from "lucide-react";
import type { ActiveCall, CustomerContext } from "@/api/handoff";

export function CustomerContextPanel({
  call: activeCall,
  context: c,
}: {
  call: ActiveCall;
  context: CustomerContext;
}) {
  const money = (n: number) => `${c.currency}${n.toLocaleString("en-IN")}`;
  return (
    <div className="rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="flex items-center justify-between border-b border-[var(--border-token)] px-3 py-2">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold text-brand-navy">
          <User2 className="h-3.5 w-3.5 text-brand-primary" />
          Customer context
        </div>
        <span className="rounded-full bg-danger-bg px-1.5 py-0.5 text-[10px] font-semibold text-danger">
          {c.risk} risk
        </span>
      </div>

      <div className="px-3 py-3">
        <div className="text-[11px] uppercase tracking-wide text-text-muted">Outstanding</div>
        <div className="tabular text-[22px] font-semibold text-brand-navy">
          {money(c.outstanding)}
        </div>
        <div className="text-[11px] text-text-secondary">
          {c.product} · tenure {c.tenureMonths}m
        </div>
      </div>

      <ul className="divide-y divide-[var(--border-token)] border-t border-[var(--border-token)]">
        <Row
          icon={<HandCoins className="h-3.5 w-3.5 text-warning" />}
          label="Last promise"
          value={`${money(c.lastPromise.amount)} · ${c.lastPromise.date}`}
          badge={{ text: "Broken", tone: "danger" }}
        />
        <Row
          icon={<CalendarClock className="h-3.5 w-3.5 text-brand-primary" />}
          label="Next EMI"
          value={`${money(c.nextEmi.amount)} · due ${c.nextEmi.dueDate}`}
          badge={{ text: `${c.nextEmi.daysOverdue}d overdue`, tone: "warning" }}
        />
        <Row
          icon={<AlertOctagon className="h-3.5 w-3.5 text-danger" />}
          label="Open disputes"
          value={`${c.openDisputes} active`}
          badge={{ text: "This call", tone: "info" }}
        />
        <Row
          icon={<ShieldCheck className="h-3.5 w-3.5 text-success" />}
          label="Consent / DND"
          value={`${c.dnd.window} · ${c.dnd.channels.join(", ")}`}
          badge={{ text: c.dnd.allowed ? "Contactable" : "Blocked", tone: c.dnd.allowed ? "success" : "danger" }}
        />
      </ul>

      <div className="border-t border-[var(--border-token)] px-3 py-2 text-[11px] text-text-muted">
        Escalation: <span className="text-text-secondary">{activeCall.escalationReason}</span>
      </div>
    </div>
  );
}

function Row({
  icon,
  label,
  value,
  badge,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  badge: { text: string; tone: "danger" | "warning" | "success" | "info" };
}) {
  const toneMap = {
    danger: "bg-danger-bg text-danger",
    warning: "bg-warning-bg text-warning",
    success: "bg-success-bg text-success",
    info: "bg-brand-tint text-brand-primary-dark",
  };
  return (
    <li className="flex items-start gap-2 px-3 py-2">
      <span className="mt-0.5">{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="text-[11px] text-text-muted">{label}</div>
        <div className="truncate text-[12px] text-text-primary">{value}</div>
      </div>
      <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${toneMap[badge.tone]}`}>
        {badge.text}
      </span>
    </li>
  );
}
