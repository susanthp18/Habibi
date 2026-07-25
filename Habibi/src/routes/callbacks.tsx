import { useEffect, useMemo, useRef, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarClock, Plus } from "lucide-react";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { MetricsStrip } from "@/components/callbacks/MetricsStrip";
import { FiltersBar } from "@/components/callbacks/FiltersBar";
import { ViewToggle, type CbView } from "@/components/callbacks/ViewToggle";
import { WeekCalendar } from "@/components/callbacks/WeekCalendar";
import { CallbackList } from "@/components/callbacks/CallbackList";
import { MissedLane } from "@/components/callbacks/MissedLane";
import { CallbackSheet } from "@/components/callbacks/CallbackSheet";
import { NewCallbackSheet } from "@/components/callbacks/NewCallbackSheet";
import {
  CURRENT_QUEUE,
  computeMetrics,
  defaultFilters,
  filterCallbacks,
  type Filters,
} from "@/data/callbacks-seed";
import {
  autoMarkMissed,
  cancelCallback,
  rescheduleCallback,
  sendReminder,
  startCall,
  useCallbacks,
} from "@/api/callbacks";
import { useCustomers } from "@/api/customers";
import { humanNames, useStaff } from "@/api/staff";
import { teamNames, useTeams } from "@/api/teams";
import { USE_MOCK } from "@/api/config";
import { parseDeepLinkSearch } from "@/lib/workspace-nav";

const UNASSIGNED_LABEL = "Unassigned";

export const Route = createFileRoute("/callbacks")({
  validateSearch: parseDeepLinkSearch,
  head: () => ({
    meta: [
      { title: "Callback & Scheduling Manager — BigBound AI" },
      {
        name: "description",
        content: "Week calendar and list for customer-requested callbacks — DND-aware scheduling, reminders, assignment, and outcome capture.",
      },
      { property: "og:title", content: "Callback & Scheduling Manager" },
      {
        property: "og:description",
        content: "Schedule and honour callbacks captured by the bot: drag-to-reschedule, DND-safe slots, reminders, and CRM writeback.",
      },
    ],
  }),
  component: CallbacksPage,
});

function CallbacksPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate({ from: Route.fullPath });
  const search = Route.useSearch();
  const { data: callbacksData = [] } = useCallbacks();
  const { data: liveCustomers } = useCustomers();
  const { data: staff = [] } = useStaff();
  const { data: teams = [] } = useTeams();

  const [filters, setFilters] = useState<Filters>(defaultFilters);
  const [openId, setOpenId] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [view, setView] = useState<CbView>("week");
  const [weekAnchor, setWeekAnchor] = useState<Date>(new Date());
  const autoMarked = useRef(false);
  const deepLinkApplied = useRef(false);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["callbacks"] });
  };

  // Live: real DB humans/teams. Mock: seed rosters (includes synthetic agents/queues).
  const assignees = useMemo(() => {
    if (!USE_MOCK) return [UNASSIGNED_LABEL, ...humanNames(staff)];
    return ["Unassigned", "Priya Nair", "Rohan Sethi", "Ananya Iyer", "Kabir Rao", "Sana Kapoor", "Vikram Menon"];
  }, [staff]);

  const queues = useMemo(() => {
    if (!USE_MOCK) return teamNames(teams);
    return ["Retail Collections", "Cards Collections", "Loans Collections", "Escalations"];
  }, [teams]);

  const myQueue = useMemo(() => {
    if (!USE_MOCK && queues.includes("Retail Collections")) return "Retail Collections";
    if (!USE_MOCK && queues[0]) return queues[0];
    return CURRENT_QUEUE;
  }, [queues]);

  const sheetCustomers = useMemo(() => {
    if (USE_MOCK) return undefined;
    return (liveCustomers ?? []).map((c) => ({
      id: c.id,
      name: c.name,
      accountId: c.accountId,
      preferredWindow: c.contact.preferredWindow,
      customerDnd: c.contact.dnd,
      timezone: c.contact.timezone,
    }));
  }, [liveCustomers]);

  // Auto-mark missed once data has loaded (window elapsed). Live writes real PATCHes.
  useEffect(() => {
    if (autoMarked.current || callbacksData.length === 0) return;
    autoMarked.current = true;
    void autoMarkMissed(callbacksData).then((n) => {
      if (n > 0) invalidate();
    });
  }, [callbacksData]);

  const filtered = useMemo(
    () => filterCallbacks(callbacksData, filters, myQueue),
    [filters, callbacksData, myQueue],
  );
  const metrics = useMemo(() => computeMetrics(filtered), [filtered]);
  const missedRows = useMemo(
    () => filtered.filter((c) => c.status === "missed").sort((a, b) => new Date(b.scheduledAt).getTime() - new Date(a.scheduledAt).getTime()),
    [filtered],
  );
  const listRows = useMemo(
    () => [...filtered].sort((a, b) => new Date(a.scheduledAt).getTime() - new Date(b.scheduledAt).getTime()),
    [filtered],
  );

  const openCb = openId ? callbacksData.find((c) => c.id === openId) ?? null : null;

  const patchFilters = (p: Partial<Filters>) => setFilters((f) => ({ ...f, ...p }));

  useEffect(() => {
    if (deepLinkApplied.current) return;
    if (!search.id && !search.new) return;
    deepLinkApplied.current = true;
    if (search.id) {
      setOpenId(search.id);
      setView("list");
    }
    if (search.new) setShowNew(true);
    void navigate({ search: {}, replace: true });
  }, [search.id, search.new, navigate]);

  const rescheduleMutation = useMutation({
    mutationFn: (v: { id: string; iso: string }) => {
      const cb = callbacksData.find((c) => c.id === v.id);
      if (!cb) throw new Error("Callback not found");
      return rescheduleCallback(cb, v.iso);
    },
    onSuccess: () => {
      invalidate();
      toast.success("Rescheduled");
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Reschedule failed"),
  });

  const startMutation = useMutation({
    mutationFn: (id: string) => {
      const cb = callbacksData.find((c) => c.id === id);
      if (!cb) throw new Error("Callback not found");
      return startCall(cb);
    },
    onSuccess: (_r, id) => {
      invalidate();
      setOpenId(id);
      toast("Call started");
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Start failed"),
  });

  const reminderMutation = useMutation({
    mutationFn: (id: string) => {
      const cb = callbacksData.find((c) => c.id === id);
      if (!cb) throw new Error("Callback not found");
      return sendReminder(cb, "whatsapp");
    },
    onSuccess: () => {
      invalidate();
      toast.success("Reminder sent · WhatsApp");
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Reminder failed"),
  });

  const cancelMutation = useMutation({
    mutationFn: (id: string) => {
      const cb = callbacksData.find((c) => c.id === id);
      if (!cb) throw new Error("Callback not found");
      return cancelCallback(cb, "Cancelled by agent");
    },
    onSuccess: () => {
      invalidate();
      toast("Callback cancelled");
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Cancel failed"),
  });

  const handleDrop = (id: string, newISO: string) => {
    rescheduleMutation.mutate({ id, iso: newISO });
  };

  const plusHours = (id: string, hours: number) => {
    const cb = callbacksData.find((c) => c.id === id);
    if (!cb) return;
    const base = cb.status === "missed" ? new Date() : new Date(cb.scheduledAt);
    base.setHours(base.getHours() + hours);
    rescheduleMutation.mutate({ id, iso: base.toISOString() });
  };

  const handleRetry = (id: string) => {
    const d = new Date();
    d.setMinutes(d.getMinutes() + 15);
    rescheduleMutation.mutate({ id, iso: d.toISOString() });
  };

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col gap-2.5 p-3">
        <header className="shrink-0 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <CalendarClock className="h-5 w-5 text-brand-primary" />
            <div>
              <h1 className="text-[16px] font-semibold text-brand-navy leading-none">Callback & Scheduling Manager</h1>
              <p className="text-[11.5px] text-text-secondary">Honour every "call me back" — DND-safe scheduling, reminders, and outcome capture.</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="text-[11px] text-text-muted">Showing {filtered.length} of {callbacksData.length}</div>
            <Button size="sm" className="h-8 text-[12px]" onClick={() => setShowNew(true)}>
              <Plus className="mr-1 h-3.5 w-3.5" /> New callback
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

        <div className="flex shrink-0 items-center gap-2">
          <ViewToggle view={view} onChange={setView} missedCount={missedRows.length} />
        </div>

        {view === "week" && (
          <WeekCalendar
            list={filtered.filter((c) => c.status !== "cancelled")}
            weekAnchor={weekAnchor}
            onPrevWeek={() => setWeekAnchor((d) => { const n = new Date(d); n.setDate(n.getDate() - 7); return n; })}
            onNextWeek={() => setWeekAnchor((d) => { const n = new Date(d); n.setDate(n.getDate() + 7); return n; })}
            onToday={() => setWeekAnchor(new Date())}
            onOpen={(id) => setOpenId(id)}
            onDrop={handleDrop}
          />
        )}
        {view === "list" && (
          <CallbackList
            rows={listRows}
            onOpen={(id) => setOpenId(id)}
            onStart={(id) => startMutation.mutate(id)}
            onSendReminder={(id) => reminderMutation.mutate(id)}
            onReschedulePlus1h={(id) => plusHours(id, 1)}
            onCancel={(id) => cancelMutation.mutate(id)}
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
    </AppShell>
  );
}

