import { toast } from "sonner";
import { Phone, CalendarClock, Plus, FileText, AlertOctagon, User, HandCoins } from "lucide-react";
import { cn } from "@/lib/utils";
import { nextCallback, slaCountdowns } from "@/data/workspace-seed";

const slaStyles = {
  ok: "text-success",
  warn: "text-warning",
  breach: "text-danger",
} as const;

export function RightRail() {
  return (
    <div className="flex flex-col gap-3">
      {/* Next callback */}
      <div className="rounded-[10px] border border-[var(--border-token)] bg-surface-card p-5 shadow-card">
        <div className="flex items-center justify-between">
          <h3 className="text-[13px] font-semibold text-brand-navy">Next scheduled callback</h3>
          <span className="rounded-full bg-brand-tint px-2 py-0.5 text-[11px] font-semibold text-brand-primary-dark">
            in {nextCallback.inMinutes}m
          </span>
        </div>
        <div className="mt-3 flex items-start gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-full bg-brand-tint text-brand-primary">
            <User className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="text-[14px] font-semibold text-text-primary">{nextCallback.customer}</div>
            <div className="font-mono text-[11px] text-text-muted">{nextCallback.accountId}</div>
            <div className="mt-1 text-[12px] text-text-secondary">{nextCallback.reason}</div>
            <div className="mt-1 flex items-center gap-1 text-[12px] font-medium text-brand-navy">
              <CalendarClock className="h-3.5 w-3.5" />
              {nextCallback.time} {nextCallback.timezone}
            </div>
          </div>
        </div>
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => toast(`Starting call with ${nextCallback.customer}`)}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md bg-brand-primary px-3 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-brand-primary-hover active:scale-[0.98]"
          >
            <Phone className="h-4 w-4" />
            Start call
          </button>
          <button
            type="button"
            onClick={() => toast("Reschedule dialog coming soon")}
            className="rounded-md border border-[var(--border-token)] bg-white px-3 py-2 text-[13px] font-medium text-text-primary hover:bg-surface-sunken"
          >
            Reschedule
          </button>
        </div>
      </div>

      {/* SLA countdowns */}
      <div className="rounded-[10px] border border-[var(--border-token)] bg-surface-card p-5 shadow-card">
        <h3 className="text-[13px] font-semibold text-brand-navy">Personal SLA countdowns</h3>
        <ul className="mt-3 space-y-2">
          {slaCountdowns.map((s) => (
            <li
              key={s.id}
              className="flex items-center justify-between rounded-md border border-[var(--border-token)] bg-surface-sunken px-3 py-2"
            >
              <div className="min-w-0">
                <div className="truncate text-[13px] font-medium text-text-primary">{s.label}</div>
                <div className="font-mono text-[11px] text-text-muted">{s.id}</div>
              </div>
              <span className={cn("text-[12px] font-semibold tabular", slaStyles[s.level])}>
                {s.remaining}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {/* Quick links */}
      <div className="rounded-[10px] border border-[var(--border-token)] bg-surface-card p-5 shadow-card">
        <h3 className="text-[13px] font-semibold text-brand-navy">Quick actions</h3>
        <div className="mt-3 grid grid-cols-2 gap-2">
          {[
            { label: "Customer 360", icon: User },
            { label: "Log manual call", icon: Phone },
            { label: "Create PTP", icon: HandCoins },
            { label: "Raise dispute", icon: AlertOctagon },
            { label: "Send statement", icon: FileText },
            { label: "New callback", icon: Plus },
          ].map((a) => {
            const Icon = a.icon;
            return (
              <button
                key={a.label}
                type="button"
                onClick={() => toast(`${a.label} — coming soon`)}
                className="flex items-center gap-2 rounded-md border border-[var(--border-token)] bg-white px-3 py-2 text-[12px] font-medium text-text-primary transition-colors hover:bg-brand-tint hover:text-brand-primary-dark active:scale-[0.98]"
              >
                <Icon className="h-4 w-4 text-brand-primary" />
                {a.label}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
