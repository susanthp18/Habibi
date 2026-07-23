import { useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import { Phone, CalendarClock, Plus, FileText, AlertOctagon, User, HandCoins } from "lucide-react";
import { useWorkspaceSummary } from "@/api/workspace";
import { fetchCallbacks, startCall } from "@/api/callbacks";
import { entityTypeFromSlaLabel, navigateWorkItem } from "@/lib/workspace-nav";
import { SlaPill, formatInMinutes } from "@/components/ui/SlaPill";

export function RightRail() {
  const navigate = useNavigate();
  const { data } = useWorkspaceSummary("me");
  const nextCallback = data?.nextCallback;
  const slaCountdowns = data?.slaCountdowns ?? [];

  const onStartCall = async () => {
    if (!nextCallback) return;
    try {
      const list = await fetchCallbacks();
      const cb = list.find((c) => c.id === nextCallback.id);
      if (cb) await startCall(cb);
      void navigate({ to: "/callbacks", search: { id: nextCallback.id } });
      toast.success(`Starting call with ${nextCallback.customer}`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Could not start call");
      void navigate({ to: "/callbacks", search: { id: nextCallback.id } });
    }
  };

  const quickActions: Array<{
    label: string;
    icon: typeof User;
    to: string;
    search?: Record<string, string | boolean>;
  }> = [
    { label: "Customer 360", icon: User, to: "/customers" },
    { label: "Log manual call", icon: Phone, to: "/floor" },
    { label: "Create PTP", icon: HandCoins, to: "/promises", search: { new: true } },
    { label: "Raise dispute", icon: AlertOctagon, to: "/disputes", search: { new: true } },
    { label: "Send statement", icon: FileText, to: "/documents", search: { new: true } },
    { label: "New callback", icon: Plus, to: "/callbacks", search: { new: true } },
  ];

  return (
    <div className="flex flex-col gap-3">
      {/* Next callback */}
      <div className="rounded-[12px] border border-[var(--border-token)] bg-surface-card p-4 shadow-card">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-[13px] font-semibold tracking-tight text-brand-navy">Next scheduled callback</h3>
          {nextCallback && (
            <span className="inline-flex shrink-0 items-center rounded-md border border-brand-primary/25 bg-brand-tint px-2 py-0.5 text-[11px] font-semibold text-brand-primary-dark">
              {formatInMinutes(nextCallback.inMinutes)}
            </span>
          )}
        </div>
        {nextCallback ? (
          <>
            <div className="mt-3 flex items-start gap-3">
              <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand-tint to-white text-brand-primary ring-1 ring-brand-primary/15">
                <User className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <div className="truncate text-[14px] font-semibold text-text-primary">{nextCallback.customer}</div>
                <div className="font-mono text-[11px] text-text-muted">{nextCallback.accountId}</div>
                <div className="mt-1 line-clamp-2 text-[12px] text-text-secondary">{nextCallback.reason}</div>
                <div className="mt-1.5 inline-flex items-center gap-1 rounded-md bg-surface-sunken px-2 py-0.5 text-[12px] font-medium text-brand-navy">
                  <CalendarClock className="h-3.5 w-3.5 text-brand-primary" />
                  {nextCallback.time} {nextCallback.timezone}
                </div>
              </div>
            </div>
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                onClick={() => void onStartCall()}
                className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md bg-brand-primary px-3 py-2 text-[13px] font-semibold text-white shadow-sm transition-colors hover:bg-brand-primary-hover active:scale-[0.98]"
              >
                <Phone className="h-4 w-4" />
                Start call
              </button>
              <button
                type="button"
                onClick={() => void navigate({ to: "/callbacks", search: { id: nextCallback.id } })}
                className="rounded-md border border-[var(--border-token)] bg-white px-3 py-2 text-[13px] font-medium text-text-primary hover:bg-surface-sunken"
              >
                Reschedule
              </button>
            </div>
          </>
        ) : (
          <p className="mt-3 text-[12px] text-text-muted">No upcoming callbacks on your queue.</p>
        )}
      </div>

      {/* SLA countdowns */}
      <div className="rounded-[12px] border border-[var(--border-token)] bg-surface-card p-4 shadow-card">
        <h3 className="text-[13px] font-semibold tracking-tight text-brand-navy">Personal SLA countdowns</h3>
        {slaCountdowns.length === 0 ? (
          <p className="mt-3 text-[12px] text-text-muted">No open SLA timers.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {slaCountdowns.map((s) => {
              const entityType = entityTypeFromSlaLabel(s.label);
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    disabled={!entityType}
                    onClick={() => {
                      if (!entityType) return;
                      navigateWorkItem(navigate, { id: s.id, entityType });
                    }}
                    className="flex w-full items-center gap-3 rounded-lg border border-[var(--border-token)] bg-surface-sunken/80 px-3 py-2.5 text-left transition-colors hover:border-brand-primary/25 hover:bg-brand-tint/50 disabled:cursor-default disabled:hover:border-[var(--border-token)] disabled:hover:bg-surface-sunken/80"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[12.5px] font-medium text-text-primary">{s.label}</div>
                      <div className="font-mono text-[10.5px] text-text-muted">{s.id}</div>
                    </div>
                    <SlaPill level={s.level} label={s.remaining} className="shrink-0" />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Quick links */}
      <div className="rounded-[12px] border border-[var(--border-token)] bg-surface-card p-4 shadow-card">
        <h3 className="text-[13px] font-semibold tracking-tight text-brand-navy">Quick actions</h3>
        <div className="mt-3 grid grid-cols-2 gap-2">
          {quickActions.map((a) => {
            const Icon = a.icon;
            return (
              <button
                key={a.label}
                type="button"
                onClick={() => {
                  void (navigate as (opts: { to: string; search?: Record<string, unknown> }) => unknown)(
                    a.search ? { to: a.to, search: a.search } : { to: a.to },
                  );
                }}
                className="flex items-center gap-2 rounded-lg border border-[var(--border-token)] bg-white px-3 py-2.5 text-left text-[12px] font-medium text-text-primary shadow-sm transition-colors hover:border-brand-primary/30 hover:bg-brand-tint/60 hover:text-brand-primary-dark active:scale-[0.98]"
              >
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-brand-tint text-brand-primary">
                  <Icon className="h-3.5 w-3.5" />
                </span>
                <span className="leading-tight">{a.label}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
