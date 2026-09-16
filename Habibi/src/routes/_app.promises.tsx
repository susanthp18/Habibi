import { useEffect, useMemo, useRef, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import { HandCoins, Plus, CalendarClock, Inbox } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/use-confirm";
import { MetricsStrip } from "@/components/promises/MetricsStrip";
import { FiltersBar } from "@/components/promises/FiltersBar";
import { PromisePipeline } from "@/components/promises/PromisePipeline";
import { PaymentPlansTable } from "@/components/promises/PaymentPlansTable";
import { PlanDetailDrawer } from "@/components/promises/PlanDetailDrawer";
import { CreatePromiseSheet, PromiseDetailSheet } from "@/components/promises/PromiseSheet";
import { PlanBuilderSheet } from "@/components/promises/PlanBuilderSheet";
import type {
  CreateInput,
  PlanInput,
  PromiseFilters,
  PromiseRevisionReason,
  ReviseInput,
  PaymentPlan,
  Promise as Ptp,
  PromiseStatus,
} from "@/api/types/promises";
import { computeMetrics, defaultFilters, filterPromises } from "@/lib/promises";
import {
  promiseOwnerOptions,
  promiseSheetCustomers,
  usePaymentPlans,
  usePromises,
  useMovePromise,
  useRevisePromise,
  useCancelPromise,
  useCreatePromise,
  useCreatePaymentPlan,
  useResendPromiseConfirm,
} from "@/api/promises";
import { useCustomers } from "@/api/customers";
import { useStaff } from "@/api/staff";
import { parseDeepLinkSearch } from "@/lib/workspace-nav";

export const Route = createFileRoute("/_app/promises")({
  validateSearch: parseDeepLinkSearch,
  head: () => ({
    meta: [
      { title: "Promise-to-Pay & Payment Plans — PayInt" },
      {
        name: "description",
        content:
          "Capture, track, and follow up on payment commitments across bot and agent channels — the beating heart of collections.",
      },
      { property: "og:title", content: "Promise-to-Pay & Payment Plans" },
      {
        property: "og:description",
        content:
          "Pipeline of upcoming, due, kept, broken, and partial promises with installment plans.",
      },
    ],
  }),
  component: PromisesPage,
});

function PromisesPage() {
  const navigate = useNavigate({ from: Route.fullPath });
  const search = Route.useSearch();
  const { data: promisesData = [] } = usePromises();
  const {
    data: plansData = [],
    isPending: plansPending,
    isError: plansError,
    error: plansErr,
  } = usePaymentPlans();
  const { data: liveCustomers } = useCustomers();

  const [filters, setFilters] = useState<PromiseFilters>(defaultFilters);

  const [createOpen, setCreateOpen] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const { confirm, confirmDialog } = useConfirm();
  const [planDetail, setPlanDetail] = useState<PaymentPlan | null>(null);
  const deepLinkKey = useRef<string | null>(null);

  const sheetCustomers = useMemo(() => promiseSheetCustomers(liveCustomers ?? []), [liveCustomers]);

  // Live: the full roster (promises can be bot-owned) unioned with owners already
  // present, so the picker can assign anyone real. Mock: derive from seed rows.
  const { data: staff = [] } = useStaff();
  const owners = useMemo(
    () =>
      promiseOwnerOptions(
        staff,
        promisesData.map((p) => p.owner),
      ),
    [promisesData, staff],
  );

  const filtered = useMemo(() => filterPromises(promisesData, filters), [filters, promisesData]);
  const metrics = useMemo(() => computeMetrics(filtered), [filtered]);
  const totalMetrics = useMemo(() => computeMetrics(promisesData), [promisesData]);

  const patchFilters = (patch: Partial<PromiseFilters>) => setFilters((f) => ({ ...f, ...patch }));

  const markMutation = useMovePromise();
  const reviseMutation = useRevisePromise();
  const cancelMutation = useCancelPromise();
  const createMutation = useCreatePromise();
  const planMutation = useCreatePaymentPlan();
  const resendMutation = useResendPromiseConfirm();

  const handleMark = (p: Ptp, status: PromiseStatus, opts?: { paidAmount?: number }) => {
    if (status === "kept" && !(p.paidAmount && p.paidAmount > 0)) {
      toast.error("Kept requires a recorded payment on the ledger");
      return;
    }
    markMutation.mutate({ p, status, opts });
    if (detailId === p.id) setDetailId(null);
  };

  const handleRevise = (p: Ptp, input: ReviseInput) => {
    reviseMutation.mutate({ p, input });
    if (detailId === p.id) setDetailId(null);
  };
  const handleCancelPromise = async (
    p: Ptp,
    input: { reason: PromiseRevisionReason; note?: string },
  ) => {
    if (
      !(await confirm({
        title: `Cancel ${p.id}?`,
        description:
          "The commitment is withdrawn with the reason shown; its reminders and pay link stop, and the account is free for a new promise.",
        confirmLabel: "Cancel promise",
      }))
    )
      return;
    cancelMutation.mutate({ p, input });
    if (detailId === p.id) setDetailId(null);
  };

  const handleDropStatus = (id: string, status: PromiseStatus) => {
    const p = promisesData.find((x) => x.id === id);
    if (!p || p.status === status) return;
    if (status === "kept" && !(p.paidAmount && p.paidAmount > 0)) {
      toast.error("Kept requires a recorded payment on the ledger");
      return;
    }
    handleMark(p, status);
  };

  const handleResend = (p: Ptp) => resendMutation.mutate(p);

  const handleCreate = (input: CreateInput) =>
    createMutation.mutate(input, {
      onError: (e) => toast.error(e instanceof Error ? e.message : "Capture failed"),
    });
  const handleCreatePlan = (input: PlanInput) => planMutation.mutate(input);

  const detail = detailId ? (promisesData.find((p) => p.id === detailId) ?? null) : null;

  useEffect(() => {
    if (!search.id && !search.new) return;
    const key = `${search.id ?? ""}|${search.new ? "1" : "0"}`;
    if (deepLinkKey.current === key) return;
    deepLinkKey.current = key;
    if (search.id) setDetailId(search.id);
    if (search.new) setCreateOpen(true);
    void navigate({ search: {}, replace: true });
  }, [search.id, search.new, navigate]);

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        {/* Header */}
        <div className="flex items-center justify-between gap-150 border-b border-border bg-surface px-300 py-150">
          <div className="flex items-center gap-150">
            <div className="grid h-9 w-9 place-items-center rounded-medium bg-background-brand-subtlest text-text-brand">
              <HandCoins className="h-4 w-4" />
            </div>
            <div>
              <h1 className="text-body font-semibold text-text">Promises & payment plans</h1>
              <p className="text-body-small text-text-subtle">
                {totalMetrics.activeCount} active · {totalMetrics.keptRate}% kept-rate
              </p>
            </div>
          </div>
          <div className="flex items-center gap-100">
            <Button variant="outline" size="sm" onClick={() => setPlanOpen(true)}>
              <CalendarClock className="mr-050 h-4 w-4" /> Payment plan
            </Button>
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="mr-050 h-4 w-4" /> New promise
            </Button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-150">
          <div className="space-y-200">
            <MetricsStrip m={metrics} />
            <FiltersBar
              filters={filters}
              onChange={patchFilters}
              owners={owners}
              counts={metrics.counts}
            />

            <PromisePipeline
              promises={filtered}
              counts={metrics.counts}
              subtotals={metrics.subtotals}
              onOpen={(p) => setDetailId(p.id)}
              onMark={handleMark}
              onDropStatus={handleDropStatus}
              onResend={handleResend}
            />

            <PaymentPlansTable
              plans={plansData}
              onOpen={setPlanDetail}
              isLoading={plansPending}
              isError={plansError}
              error={plansErr}
            />
          </div>
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
      {confirmDialog}
      <PromiseDetailSheet
        promise={detail}
        onOpenChange={(v) => !v && setDetailId(null)}
        onMark={handleMark}
        onRevise={handleRevise}
        onCancelPromise={handleCancelPromise}
        onResend={handleResend}
      />
      <PlanDetailDrawer plan={planDetail} onOpenChange={(v) => !v && setPlanDetail(null)} />
    </>
  );
}
