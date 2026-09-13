import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { BillingHeader } from "@/components/billing/BillingHeader";
import { BillingKpiStrip } from "@/components/billing/BillingKpiStrip";
import { SpendTrendChart } from "@/components/billing/SpendTrendChart";
import { BudgetPanel } from "@/components/billing/BudgetPanel";
import { ModelCostTable } from "@/components/billing/ModelCostTable";
import { ServiceCostTable } from "@/components/billing/ServiceCostTable";
import { ServiceDonut } from "@/components/billing/ServiceDonut";
import { ServiceDrawer } from "@/components/billing/ServiceDrawer";
import { TenantTable } from "@/components/billing/TenantTable";
import { InvoiceList } from "@/components/billing/InvoiceList";
import {
  billingExportUrl,
  useBilling,
  useBudgetRuleMutations,
  type BillingBudget,
} from "@/api/billing";
import type { BudgetRule, Env, Period, Service } from "@/api/types/billing";
import { toast } from "sonner";
import { LoadingState } from "@/components/ui/loading-state";

export const Route = createFileRoute("/_app/billing")({
  head: () => ({
    meta: [
      { title: "Billing & Usage Analytics — BigBound AI" },
      {
        name: "description",
        content: "Metered Azure OpenAI and Speech spend with per-tenant unit economics.",
      },
      { property: "og:title", content: "Billing & Usage Analytics" },
      {
        property: "og:description",
        content:
          "Cost per resolved call, budget alerts and per-tenant spend for the collections voice AI stack.",
      },
    ],
  }),
  component: BillingPage,
});

function BillingPage() {
  const [period, setPeriod] = useState<Period>("mtd");
  const [env, setEnv] = useState<Env>("production");
  const [drawerService, setDrawerService] = useState<Service | null>(null);

  const { data, isLoading, isError, error, refetch, isFetching } = useBilling(period, env);
  const { save, remove } = useBudgetRuleMutations();

  const services = data?.services ?? [];
  const tenants = data?.tenants ?? [];
  const budgets: BillingBudget[] = data?.budgets ?? [];

  const handleSaveRule = async (
    budgetId: string,
    rule: {
      id?: string;
      threshold: number;
      channels: string[];
      action: string;
      severity: BudgetRule["severity"];
    },
  ) => {
    try {
      await save.mutateAsync({ budgetId, rule });
      toast.success(rule.id ? "Budget rule updated" : "Budget rule added");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save rule");
      throw e;
    }
  };

  const handleDeleteRule = async (budgetId: string, ruleId: string) => {
    try {
      await remove.mutateAsync({ budgetId, ruleId });
      toast.info("Budget rule removed");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete rule");
      throw e;
    }
  };

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        <BillingHeader
          period={period}
          onPeriod={setPeriod}
          env={env}
          onEnv={setEnv}
          onExportCsv={() => {
            if (!data) return;
            window.open(billingExportUrl(period, env), "_blank");
            toast.success("CSV export started");
          }}
          refreshing={isFetching}
        />

        {isLoading && !data ? (
          <div className="flex flex-1 items-center justify-center">
            <LoadingState label="Loading billing data" />
          </div>
        ) : isError && !data ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-100 text-body text-text-subtle">
            <p>Couldn’t load billing data.</p>
            <p className="text-body-small text-text-danger">
              {error instanceof Error ? error.message : "Unknown error"}
            </p>
            <button
              type="button"
              className="rounded-medium bg-background-brand-bold px-150 py-075 text-body-small font-medium text-text-inverse"
              onClick={() => void refetch()}
            >
              Retry
            </button>
          </div>
        ) : data ? (
          <div className="min-h-0 flex-1 overflow-y-auto bg-surface px-250 py-200">
            <div className="grid gap-200">
              <BillingKpiStrip
                daily={data.daily}
                spendMtd={data.spend}
                spendPrev={data.spendPrev}
                costPerCall={data.costPerCall}
                costPerCallPrev={data.costPerCallPrev}
                attributedCostPerCall={data.attributedCostPerCall}
                attributedCalls={data.attributedCalls}
                forecast={data.forecast}
                budgetCap={data.budgetCap}
              />

              <div className="grid items-stretch gap-200 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                <div className="min-h-[20rem]">
                  <SpendTrendChart data={data.daily} services={services} />
                </div>
                <div className="min-h-[20rem] max-h-[26.25rem]">
                  <BudgetPanel
                    budgets={budgets}
                    spendByEnv={data.spendByEnv}
                    alerts={data.alerts}
                    onSaveRule={handleSaveRule}
                    onDeleteRule={handleDeleteRule}
                    saving={save.isPending || remove.isPending}
                  />
                </div>
              </div>

              <div className="grid items-stretch gap-200 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                <ServiceCostTable
                  services={services}
                  current={data.daily}
                  previous={data.previousDaily}
                  onRowClick={setDrawerService}
                  isLoading={isLoading}
                  isError={isError}
                  error={error}
                />
                <ServiceDonut data={data.daily} services={services} />
              </div>

              <ModelCostTable
                rows={data.modelSpend}
                isLoading={isLoading}
                isError={isError}
                error={error}
              />

              <div className="grid gap-200 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
                <TenantTable
                  rows={data.tenantBreakdown}
                  isLoading={isLoading}
                  isError={isError}
                  error={error}
                />
                <InvoiceList
                  invoices={data.invoices}
                  isLoading={isLoading}
                  isError={isError}
                  error={error}
                />
              </div>
            </div>
          </div>
        ) : null}
      </div>

      <ServiceDrawer
        open={!!drawerService}
        onOpenChange={(v) => !v && setDrawerService(null)}
        service={drawerService}
        current={data?.daily ?? []}
        previous={data?.previousDaily ?? []}
        tenants={tenants}
        serviceTenantSpend={drawerService ? (data?.serviceTenantSpend[drawerService.id] ?? {}) : {}}
      />
    </>
  );
}
