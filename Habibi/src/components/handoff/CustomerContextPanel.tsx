import { AlertOctagon, CalendarClock, HandCoins, ShieldCheck, User2 } from "lucide-react";
import type { ActiveCall, CustomerContext } from "@/api/handoff";
import { Lozenge } from "@/components/ui/lozenge";

export function CustomerContextPanel({
  call: activeCall,
  context: c,
}: {
  call: ActiveCall;
  context: CustomerContext;
}) {
  const money = (n: number) => `${c.currency}${n.toLocaleString("en-IN")}`;
  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-150 py-100">
        <div className="flex items-center gap-075 text-body-small font-semibold text-text">
          <User2 className="h-3.5 w-3.5 text-text-brand" />
          Customer context
        </div>
        <Lozenge tone="danger">{c.risk} risk</Lozenge>
      </div>

      <div className="px-150 py-150">
        <div className="text-body-small text-text-subtlest">Outstanding</div>
        <div className="tabular text-[1.5rem] font-semibold text-text">
          {money(c.outstanding)}
        </div>
        <div className="text-body-small text-text-subtle">
          {c.product} · tenure {c.tenureMonths}m
        </div>
      </div>

      <ul className="divide-y divide-border border-t border-border">
        <Row
          icon={<HandCoins className="h-3.5 w-3.5 text-text-warning" />}
          label="Last promise"
          value={`${money(c.lastPromise.amount)} · ${c.lastPromise.date}`}
          badge={{ text: "Broken", tone: "danger" }}
        />
        <Row
          icon={<CalendarClock className="h-3.5 w-3.5 text-text-brand" />}
          label="Next EMI"
          value={`${money(c.nextEmi.amount)} · due ${c.nextEmi.dueDate}`}
          badge={{ text: `${c.nextEmi.daysOverdue}d overdue`, tone: "warning" }}
        />
        <Row
          icon={<AlertOctagon className="h-3.5 w-3.5 text-text-danger" />}
          label="Open disputes"
          value={`${c.openDisputes} active`}
          badge={{ text: "This call", tone: "info" }}
        />
        <Row
          icon={<ShieldCheck className="h-3.5 w-3.5 text-text-success" />}
          label="Consent / DND"
          value={`${c.dnd.window} · ${c.dnd.channels.join(", ")}`}
          badge={{ text: c.dnd.allowed ? "Contactable" : "Blocked", tone: c.dnd.allowed ? "success" : "danger" }}
        />
      </ul>

      <div className="border-t border-border px-150 py-100 text-body-small text-text-subtlest">
        Escalation: <span className="text-text-subtle">{activeCall.escalationReason}</span>
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
    danger: "danger",
    warning: "warning",
    success: "success",
    info: "selected",
  } as const;
  return (
    <li className="flex items-start gap-100 px-150 py-100">
      <span className="mt-025">{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="text-body-small text-text-subtlest">{label}</div>
        <div className="truncate text-body-small text-text">{value}</div>
      </div>
      <Lozenge tone={toneMap[badge.tone]} className="shrink-0">
        {badge.text}
      </Lozenge>
    </li>
  );
}
