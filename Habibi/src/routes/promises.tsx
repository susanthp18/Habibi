import { useEffect, useMemo, useRef, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { HandCoins, Plus, CalendarClock, Inbox } from "lucide-react";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { MetricsStrip } from "@/components/promises/MetricsStrip";
import { FiltersBar } from "@/components/promises/FiltersBar";
import { PromisePipeline } from "@/components/promises/PromisePipeline";
import { PaymentPlansTable } from "@/components/promises/PaymentPlansTable";
import { PlanDetailDrawer } from "@/components/promises/PlanDetailDrawer";
import { CreatePromiseSheet, PromiseDetailSheet, type CreateInput, type CustomerOption } from "@/components/promises/PromiseSheet";
import { PlanBuilderSheet, type PlanInput } from "@/components/promises/PlanBuilderSheet";
import {
  computeMetrics,
  defaultFilters,
  filterPromises,
  followUps,
  type Filters,
  type PaymentPlan,
  type Promise as Ptp,
  type PromiseStatus,
} from "@/data/promises-seed";
import {
  createPlan,
  createPromise,
  movePromise,
  reschedulePromise,
  usePaymentPlans,
  usePromises,
} from "@/api/promises";
import { useCustomers } from "@/api/customers";
import { useStaff } from "@/api/staff";
import { USE_MOCK } from "@/api/config";
import { parseDeepLinkSearch } from "@/lib/workspace-nav";

export const Route = createFileRoute("/promises")({
  validateSearch: parseDeepLinkSearch,
  head: () => ({
    meta: [
      { title: "Promise-to-Pay & Payment Plans — BigBound AI" },
      { name: "description", content: "Capture, track, and follow up on payment commitments across bot and agent channels — the beating heart of collections." },
      { property: "og:title", content: "Promise-to-Pay & Payment Plans" },
      { property: "og:description", content: "Pipeline of upcoming, due, kept, broken, and partial promises with installment plans." },
    ],
  }),
  component: PromisesPage,
});

function PromisesPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate({ from: Route.fullPath });
  const search = Route.useSearch();
  const { data: promisesData = [] } = usePromises();
  const { data: plansData = [] } = usePaymentPlans();
  const { data: liveCustomers } = useCustomers();

  const [filters, setFilters] = useState<Filters>(defaultFilters);

  const [createOpen, setCreateOpen] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [planDetail, setPlanDetail] = useState<PaymentPlan | null>(null);
  const deepLinkApplied = useRef(false);

  // Live mode: pick real customers for the create/plan sheets. Mock mode: let the
  // sheets fall back to their seed roster (pass undefined).
  const sheetCustomers = useMemo<CustomerOption[] | undefined>(() => {
    if (USE_MOCK) return undefined;
    return (liveCustomers ?? []).map((c) => ({
      id: c.id,
      name: c.name,
      accountId: c.accountId,
      outstanding: c.outstanding,
    }));
  }, [liveCustomers]);

  // Live: the full roster (promises can be bot-owned) unioned with owners already
  // present, so the picker can assign anyone real. Mock: derive from seed rows.
  const { data: staff = [] } = useStaff();
  const owners = useMemo(() => {
    const set = new Set<string>();
    promisesData.forEach((p) => set.add(p.owner));
    if (!USE_MOCK) staff.forEach((s) => set.add(s.name));
    return Array.from(set).sort();
  }, [promisesData, staff]);

  const filtered = useMemo(() => filterPromises(promisesData, filters), [filters, promisesData]);
  const metrics = useMemo(() => computeMetrics(filtered), [filtered]);
  const totalMetrics = useMemo(() => computeMetrics(promisesData), [promisesData]);

  const patchFilters = (patch: Partial<Filters>) => setFilters((f) => ({ ...f, ...patch }));

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["promises"] });
    queryClient.invalidateQueries({ queryKey: ["payment-plans"] });
  };

  const markMutation = useMutation({
    mutationFn: (v: { p: Ptp; status: PromiseStatus; opts?: { paidAmount?: number } }) =>
      movePromise(v.p, v.status, v.opts),
    onSuccess: (_r, v) => {
      invalidate();
      if (v.status === "kept") toast.success(`Marked kept · ${v.p.customerName}`);
      else if (v.status === "partial") toast.warning(`Partial payment logged · ${v.p.customerName}`);
      else if (v.status === "broken") toast.error(`Broken promise · ${v.p.customerName} routed to follow-up`);
      else toast(`Updated to ${v.status.replace("_", " ")}`);
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Update failed"),
  });

  const rescheduleMutation = useMutation({
    mutationFn: (v: { p: Ptp; newDate: string }) => reschedulePromise(v.p, v.newDate),
    onSuccess: (_r, v) => {
      invalidate();
      toast.success(`Rescheduled ${v.p.id}`);
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Reschedule failed"),
  });

  const createMutation = useMutation({
    mutationFn: (input: CreateInput) => createPromise(input),
    onSuccess: (res) => {
      invalidate();
      toast.success(`Promise captured · ${res.id}`);
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Capture failed"),
  });

  const planMutation = useMutation({
    mutationFn: (input: PlanInput) => createPlan(input),
    onSuccess: (res) => {
      invalidate();
      toast.success(`Plan ${res.id} created · first installment scheduled`);
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Plan creation failed"),
  });

  const handleMark = (p: Ptp, status: PromiseStatus, opts?: { paidAmount?: number }) => {
    markMutation.mutate({ p, status, opts });
    if (detailId === p.id) setDetailId(null);
  };

  const handleReschedule = (p: Ptp, newDate: string) => {
    rescheduleMutation.mutate({ p, newDate });
    if (detailId === p.id) setDetailId(null);
  };

  const handleDropStatus = (id: string, status: PromiseStatus) => {
    const p = promisesData.find((x) => x.id === id);
    if (!p || p.status === status) return;
    handleMark(p, status);
  };

  const handleCreate = (input: CreateInput) => createMutation.mutate(input);
  const handleCreatePlan = (input: PlanInput) => planMutation.mutate(input);

  const detail = detailId ? promisesData.find((p) => p.id === detailId) ?? null : null;

  useEffect(() => {
    if (deepLinkApplied.current) return;
    if (!search.id && !search.new) return;
    deepLinkApplied.current = true;
    if (search.id) setDetailId(search.id);
    if (search.new) setCreateOpen(true);
    void navigate({ search: {}, replace: true });
  }, [search.id, search.new, navigate]);

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        {/* Header */}
        <div className="flex items-center justify-between gap-3 border-b border-[var(--border-token)] bg-surface-card px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="grid h-9 w-9 place-items-center rounded-md bg-brand-tint text-brand-primary">
              <HandCoins className="h-4 w-4" />
            </div>
            <div>
              <h1 className="text-[15px] font-semibold text-brand-navy">Promises & Payment Plans</h1>
              <p className="text-[12px] text-text-secondary">
                {totalMetrics.activeCount} active · {totalMetrics.keptRate}% kept-rate · {followUps.length} follow-up
                {followUps.length === 1 ? "" : "s"} created this session
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => setPlanOpen(true)}>
              <CalendarClock className="mr-1 h-4 w-4" /> Payment plan
            </Button>
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="mr-1 h-4 w-4" /> New promise
            </Button>
          </div>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 space-y-4 overflow-y-auto px-6 py-4">
          <MetricsStrip m={metrics} />
          <FiltersBar
            filters={filters}
            onChange={patchFilters}
            owners={owners}
            counts={metrics.counts}
          />

          {followUps.length > 0 && (
            <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50/60 px-3 py-2 text-[12px]">
              <Inbox className="mt-0.5 h-4 w-4 text-red-600" />
              <div className="flex-1">
                <div className="font-semibold text-red-800">Broken promises routed to Follow-up Queue</div>
                <div className="text-red-700/80">
                  {followUps.slice(0, 3).map((f) => `${f.customerName} · ${f.promiseId}`).join(" · ")}
                  {followUps.length > 3 && ` · +${followUps.length - 3} more`}
                </div>
              </div>
            </div>
          )}

          <PromisePipeline
            promises={filtered}
            counts={metrics.counts}
            subtotals={metrics.subtotals}
            onOpen={(p) => setDetailId(p.id)}
            onMark={handleMark}
            onDropStatus={handleDropStatus}
          />

          <PaymentPlansTable plans={plansData} onOpen={setPlanDetail} />
        </div>
      </div>

      <CreatePromiseSheet
        open={createOpen}
        onOpenChange={setCreateOpen}
        onSubmit={handleCreate}
        owners={owners}
        customers={sheetCustomers}
      />
      <PlanBuilderSheet
        open={planOpen}
        onOpenChange={setPlanOpen}
        onSubmit={handleCreatePlan}
        owners={owners}
        customers={sheetCustomers}
      />
      <PromiseDetailSheet
        promise={detail}
        onOpenChange={(v) => !v && setDetailId(null)}
        onMark={handleMark}
        onReschedule={handleReschedule}
      />
      <PlanDetailDrawer plan={planDetail} onOpenChange={(v) => !v && setPlanDetail(null)} />
    </AppShell>
  );
}
