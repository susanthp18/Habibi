import { useState } from "react";
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

  // Guards a double-click: startCall places a real outbound call, and two
  // clicks a moment apart used to fire two of them.
  const [startingCall, setStartingCall] = useState(false);

  const onStartCall = async () => {
    if (!nextCallback || startingCall) return;
    setStartingCall(true);
    try {
      const list = await fetchCallbacks();
      const cb = list.find((c) => c.id === nextCallback.id);
      void navigate({ to: "/callbacks", search: { id: nextCallback.id } });
      if (cb) {
        await startCall(cb);
        toast.success(`Starting call with ${nextCallback.customer}`);
      } else {
        toast.message("Callback no longer available — opening queue");
      }
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Could not start call");
      void navigate({ to: "/callbacks", search: { id: nextCallback.id } });
    } finally {
      setStartingCall(false);
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
    <div className="flex flex-col gap-150">
      {/* Next callback */}
      <div className="rounded-xlarge border border-border bg-surface p-200">
        <div className="flex items-center justify-between gap-100">
          <h3 className="heading-xsmall text-text">Next scheduled callback</h3>
          {nextCallback && (
            <span className="inline-flex shrink-0 items-center rounded-medium border border-border-brand/25 bg-background-brand-subtlest px-100 py-025 text-body-small font-medium text-text-brand">
              {formatInMinutes(nextCallback.inMinutes)}
            </span>
          )}
        </div>
        {nextCallback ? (
          <>
            <div className="mt-150 flex items-start gap-150">
              <div className="grid h-500 w-500 shrink-0 place-items-center rounded-xlarge bg-background-brand-subtlest text-text-brand ring-1 ring-border-brand/15">
                <User className="h-250 w-250" />
              </div>
              <div className="min-w-0">
                <div className="truncate text-body font-medium text-text">
                  {nextCallback.customer}
                </div>
                <div className="font-mono text-body-small text-text-subtlest">
                  {nextCallback.accountId}
                </div>
                <div className="mt-050 line-clamp-2 text-body-small text-text-subtle">
                  {nextCallback.reason}
                </div>
                <div className="mt-075 inline-flex items-center gap-050 rounded-medium bg-surface-sunken px-100 py-025 text-body-small font-medium text-text">
                  <CalendarClock className="h-3.5 w-3.5 text-text-brand" />
                  {nextCallback.time} {nextCallback.timezone}
                </div>
              </div>
            </div>
            <div className="mt-200 flex gap-100">
              <button
                type="button"
                onClick={() => void onStartCall()}
                disabled={startingCall}
                className="inline-flex flex-1 items-center justify-center gap-075 rounded-medium bg-background-brand-bold px-150 py-100 text-body font-medium text-text-inverse transition-colors hover:bg-background-brand-bold-hovered active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Phone className="h-4 w-4" />
                {startingCall ? "Starting…" : "Start call"}
              </button>
              <button
                type="button"
                onClick={() => void navigate({ to: "/callbacks", search: { id: nextCallback.id } })}
                className="rounded-medium border border-border bg-surface px-150 py-100 text-body font-medium text-text hover:bg-surface-sunken"
              >
                Reschedule
              </button>
            </div>
          </>
        ) : (
          <p className="mt-150 text-body-small text-text-subtlest">
            No upcoming callbacks on your queue.
          </p>
        )}
      </div>

      {/* SLA countdowns */}
      <div className="rounded-xlarge border border-border bg-surface p-200">
        <h3 className="heading-xsmall text-text">Personal SLA countdowns</h3>
        {slaCountdowns.length === 0 ? (
          <p className="mt-150 text-body-small text-text-subtlest">No open SLA timers.</p>
        ) : (
          <ul className="mt-150 max-h-[22rem] space-y-100 overflow-y-auto pr-025">
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
                    className="flex w-full items-center gap-150 rounded-large border border-border bg-surface-sunken/80 px-150 py-150 text-left transition-colors hover:border-border-brand/25 hover:bg-background-brand-subtlest/50 disabled:cursor-default disabled:hover:border-border disabled:hover:bg-surface-sunken/80"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-body-small font-medium text-text">
                        {s.label}
                      </div>
                      <div className="font-mono text-body-small text-text-subtlest">{s.id}</div>
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
      <div className="rounded-xlarge border border-border bg-surface p-200">
        <h3 className="heading-xsmall text-text">Quick actions</h3>
        <div className="mt-150 grid grid-cols-2 gap-100">
          {quickActions.map((a) => {
            const Icon = a.icon;
            return (
              <button
                key={a.label}
                type="button"
                onClick={() => {
                  void navigate(a.search ? { to: a.to, search: a.search } : { to: a.to });
                }}
                className="flex items-center gap-100 rounded-large border border-border bg-surface px-150 py-150 text-left text-body-small font-medium text-text transition-colors hover:border-border-brand/30 hover:bg-background-brand-subtlest/60 hover:text-text-brand active:scale-[0.98]"
              >
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-medium bg-background-brand-subtlest text-text-brand">
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
