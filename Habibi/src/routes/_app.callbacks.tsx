import { useEffect, useMemo, useRef, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarClock, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MetricsStrip } from "@/components/callbacks/MetricsStrip";
import { FiltersBar } from "@/components/callbacks/FiltersBar";
import { ViewToggle, type CbView } from "@/components/callbacks/ViewToggle";
import { WeekCalendar } from "@/components/callbacks/WeekCalendar";
import { CallbackList } from "@/components/callbacks/CallbackList";
import { MissedLane } from "@/components/callbacks/MissedLane";
import { CallbackSheet } from "@/components/callbacks/CallbackSheet";
import { NewCallbackSheet } from "@/components/callbacks/NewCallbackSheet";
import type { CallbackFilters } from "@/api/types/callbacks";
import { computeMetrics, defaultFilters, filterCallbacks } from "@/lib/callbacks";
import {
  autoMarkMissed,
  callbackAssigneeOptions,
  callbackQueueOptions,
  callbackSheetCustomers,
  defaultCallbackQueue,
  useCallbacks,
  useRescheduleCallback,
  useStartCallback,
  useSendCallbackReminder,
  useCancelCallback,
} from "@/api/callbacks";
import { useCustomers } from "@/api/customers";
import { useStaff } from "@/api/staff";
import { useTeams } from "@/api/teams";
import { parseDeepLinkSearch } from "@/lib/workspace-nav";

export const Route = createFileRoute("/_app/callbacks")({
  validateSearch: parseDeepLinkSearch,
  head: () => ({
    meta: [
      { title: "Callback & Scheduling Manager — BigBound AI" },
      {
        name: "description",
        content:
          "Week calendar and list for customer-requested callbacks — DND-aware scheduling, reminders, assignment, and outcome capture.",
      },
      { property: "og:title", content: "Callback & Scheduling Manager" },
      {
        property: "og:description",
        content:
          "Schedule and honour callbacks captured by the bot: drag-to-reschedule, DND-safe slots, reminders, and CRM writeback.",
      },
    ],
  }),
  component: CallbacksPage,
});

function CallbacksPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate({ from: Route.fullPath });
  const search = Route.useSearch();
  const {
    data: callbacksData = [],
    isPending: callbacksPending,
    isError: callbacksError,
    error: callbacksErr,
  } = useCallbacks();
  const { data: liveCustomers } = useCustomers();
  const { data: staff = [] } = useStaff();
  const { data: teams = [] } = useTeams();

  const [filters, setFilters] = useState<CallbackFilters>(defaultFilters);
  const [openId, setOpenId] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [view, setView] = useState<CbView>("week");
  const [weekAnchor, setWeekAnchor] = useState<Date>(new Date());
  const autoMarked = useRef(false);
  const deepLinkKey = useRef<string | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["callbacks"] });
  };

  // Live: real DB humans/teams. Mock: seed rosters (includes synthetic agents/queues).
  const assignees = useMemo(
    () =>
      callbackAssigneeOptions(
        staff,
        callbacksData.map((c) => c.assignee),
      ),
    [staff, callbacksData],
  );

  const queues = useMemo(() => callbackQueueOptions(teams), [teams]);

  const myQueue = useMemo(() => defaultCallbackQueue(queues), [queues]);

  const sheetCustomers = useMemo(
    () => callbackSheetCustomers(liveCustomers ?? []),
    [liveCustomers],
  );

  // Auto-mark missed once data has loaded (window elapsed). Live writes real PATCHes.
  useEffect(() => {
    if (autoMarked.current || callbacksData.length === 0) return;
    autoMarked.current = true;
    autoMarkMissed(callbacksData)
      .then((n) => {
        if (n > 0) invalidate();
      })
      .catch((e: unknown) =>
        toast.error(e instanceof Error ? e.message : "Could not mark missed callbacks"),
      );
  }, [callbacksData]);

  const filtered = useMemo(
    () => filterCallbacks(callbacksData, filters, myQueue),
    [filters, callbacksData, myQueue],
  );
  const metrics = useMemo(() => computeMetrics(filtered), [filtered]);
  const missedRows = useMemo(
    () =>
      filtered
        .filter((c) => c.status === "missed")
        .sort((a, b) => new Date(b.scheduledAt).getTime() - new Date(a.scheduledAt).getTime()),
    [filtered],
  );
  const listRows = useMemo(
    () =>
      [...filtered].sort(
        (a, b) => new Date(a.scheduledAt).getTime() - new Date(b.scheduledAt).getTime(),
      ),
    [filtered],
  );

  const openCb = openId ? (callbacksData.find((c) => c.id === openId) ?? null) : null;

  const patchFilters = (p: Partial<CallbackFilters>) => setFilters((f) => ({ ...f, ...p }));

  useEffect(() => {
    if (!search.id && !search.new) return;
    const key = `${search.id ?? ""}|${search.new ? "1" : "0"}`;
    if (deepLinkKey.current === key) return;
    deepLinkKey.current = key;
    if (search.id) {
      setOpenId(search.id);
      setView("list");
    }
    if (search.new) setShowNew(true);
    void navigate({ search: {}, replace: true });
  }, [search.id, search.new, navigate]);

  const rescheduleMutation = useRescheduleCallback();
  const startMutation = useStartCallback();
  const reminderMutation = useSendCallbackReminder();
  const cancelMutation = useCancelCallback();
  const byId = (id: string) => {
    const cb = callbacksData.find((c) => c.id === id);
    if (!cb) toast.error("Callback not found");
    return cb;
  };
  const reschedule = (id: string, iso: string) => {
    const cb = byId(id);
    if (cb) rescheduleMutation.mutate({ cb, iso });
  };

  const handleDrop = (id: string, newISO: string) => {
    reschedule(id, newISO);
  };

  const plusHours = (id: string, hours: number) => {
    const cb = callbacksData.find((c) => c.id === id);
    if (!cb) return;
    const base = cb.status === "missed" ? new Date() : new Date(cb.scheduledAt);
    base.setHours(base.getHours() + hours);
    reschedule(id, base.toISOString());
  };

  const handleRetry = (id: string) => {
    const d = new Date();
    d.setMinutes(d.getMinutes() + 15);
    reschedule(id, d.toISOString());
  };

  return (
    <>
      <div className="flex h-full min-h-0 flex-col gap-150 p-150">
        <header className="shrink-0 flex items-center justify-between gap-100">
          <div className="flex items-center gap-100">
            <CalendarClock className="h-250 w-250 text-text-brand" />
            <div>
              <h1 className="heading-small font-semibold text-text leading-none">
                Callback & scheduling manager
              </h1>
              <p className="text-body-small text-text-subtle">
                Honour every "call me back" — DND-safe scheduling, reminders, and outcome capture.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-100">
            <div className="text-body-small text-text-subtlest">
              Showing {filtered.length} of {callbacksData.length}
            </div>
            <Button size="sm" className="h-400 text-body-small" onClick={() => setShowNew(true)}>
              <Plus className="mr-050 h-3.5 w-3.5" /> New callback
            </Button>
          </div>
        </header>

        <MetricsStrip m={metrics} />
        <FiltersBar
          filters={filters}
          onPatch={patchFilters}
          onReset={() => setFilters(defaultFilters)}
          assignees={assignees}
          queues={queues}
          myQueue={myQueue}
        />

        <div className="flex shrink-0 items-center gap-100">
          <ViewToggle view={view} onChange={setView} missedCount={missedRows.length} />
        </div>

        {view === "week" && (
          <WeekCalendar
            list={filtered.filter((c) => c.status !== "cancelled")}
            weekAnchor={weekAnchor}
            onPrevWeek={() =>
              setWeekAnchor((d) => {
                const n = new Date(d);
                n.setDate(n.getDate() - 7);
                return n;
              })
            }
            onNextWeek={() =>
              setWeekAnchor((d) => {
                const n = new Date(d);
                n.setDate(n.getDate() + 7);
                return n;
              })
            }
            onToday={() => setWeekAnchor(new Date())}
            onOpen={(id) => setOpenId(id)}
            onDrop={handleDrop}
          />
        )}
        {view === "list" && (
          <CallbackList
            rows={listRows}
            onOpen={(id) => setOpenId(id)}
            onStart={(id) => {
              const cb = byId(id);
              if (cb) startMutation.mutate(cb, { onSuccess: () => setOpenId(id) });
            }}
            onSendReminder={(id) => {
              const cb = byId(id);
              if (cb) reminderMutation.mutate({ cb, channel: "whatsapp" });
            }}
            onReschedulePlus1h={(id) => plusHours(id, 1)}
            onCancel={(id) => {
              const cb = byId(id);
              if (cb) cancelMutation.mutate({ cb, reason: "Cancelled by agent" });
            }}
            isLoading={callbacksPending}
            isError={callbacksError}
            error={callbacksErr}
          />
        )}
        {view === "missed" && (
          <MissedLane
            rows={missedRows}
            onOpen={(id) => setOpenId(id)}
            onRetry={handleRetry}
            onReschedulePlus1h={(id) => plusHours(id, 1)}
            onReschedulePlus1d={(id) => plusHours(id, 24)}
          />
        )}

        {openCb && (
          <CallbackSheet
            cb={openCb}
            onClose={() => setOpenId(null)}
            onMutate={invalidate}
            assignees={assignees}
            queues={queues}
          />
        )}
        {showNew && (
          <NewCallbackSheet
            onClose={() => setShowNew(false)}
            onCreated={invalidate}
            customers={sheetCustomers}
            assignees={assignees}
            queues={queues}
          />
        )}
      </div>
    </>
  );
}
