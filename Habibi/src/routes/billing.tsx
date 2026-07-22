import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/shell/AppShell";
import { BillingHeader } from "@/components/billing/BillingHeader";
import { BillingKpiStrip } from "@/components/billing/BillingKpiStrip";
import { SpendTrendChart } from "@/components/billing/SpendTrendChart";
import { BudgetPanel } from "@/components/billing/BudgetPanel";
import { ServiceCostTable } from "@/components/billing/ServiceCostTable";
import { ServiceDonut } from "@/components/billing/ServiceDonut";
import { ServiceDrawer } from "@/components/billing/ServiceDrawer";
import { TenantTable } from "@/components/billing/TenantTable";
import { InvoiceList } from "@/components/billing/InvoiceList";
import {
  BUDGETS,
  TENANTS,
  forecastEom,
  previousPeriod,
  sliceForPeriod,
  sumRange,
  type BudgetRule,
  type Env,
  type Period,
  type Service,
  type Budget,
} from "@/data/billing-seed";

export const Route = createFileRoute("/billing")({
  head: () => ({
    meta: [
      { title: "Billing & Usage Analytics — Collections Agent" },
      { name: "description", content: "Cloud spend across LLM, voice, messaging and infrastructure with per-tenant unit economics." },
      { property: "og:title", content: "Billing & Usage Analytics" },
      { property: "og:description", content: "Cost per resolved call, budget alerts and per-tenant spend for the collections voice AI stack." },
    ],
  }),
  component: BillingPage,
});

function BillingPage() {
  const [period, setPeriod] = useState<Period>("mtd");
  const [tenantId, setTenantId] = useState<string>("all");
  const [env, setEnv] = useState<Env>("production");
  const [budgets, setBudgets] = useState<Budget[]>(BUDGETS);
  const [drawerService, setDrawerService] = useState<Service | null>(null);

  const rawCurrent = useMemo(() => sliceForPeriod(period), [period]);
  const rawPrevious = useMemo(() => previousPeriod(period), [period]);

  // Tenant scoping — scale down by tenant's spendShare when a single tenant is picked.
  const scale = useMemo(() => {
    if (tenantId === "all") return 1;
    return TENANTS.find((t) => t.id === tenantId)?.spendShare ?? 1;
  }, [tenantId]);

  const envScale = env === "sandbox" ? 0.08 : 1;
  const factor = scale * envScale;

  const current = useMemo(
    () =>
      rawCurrent.map((d) => ({
        date: d.date,
        values: Object.fromEntries(Object.entries(d.values).map(([k, v]) => [k, Math.round(v * factor)])),
      })),
    [rawCurrent, factor],
  );
  const previous = useMemo(
    () =>
      rawPrevious.map((d) => ({
        date: d.date,
        values: Object.fromEntries(Object.entries(d.values).map(([k, v]) => [k, Math.round(v * factor)])),
      })),
    [rawPrevious, factor],
  );

  const spendMtd = sumRange(current);
  const spendPrev = sumRange(previous);
  const forecast = forecastEom(current);

  const totalResolved = tenantId === "all"
    ? TENANTS.reduce((s, t) => s + t.resolvedCalls, 0)
    : TENANTS.find((t) => t.id === tenantId)?.resolvedCalls ?? 1;
  const totalResolvedPrev = totalResolved * 0.93;
  const costPerCall = totalResolved > 0 ? spendMtd / totalResolved : 0;
  const costPerCallPrev = totalResolvedPrev > 0 ? spendPrev / totalResolvedPrev : 0;

  const budgetForEnv = budgets.find((b) => b.env === env) ?? budgets[0];

  const spendByEnv: Record<string, number> = {
    production: env === "production" ? spendMtd : sumRange(rawCurrent) * (tenantId === "all" ? 1 : scale),
    sandbox: env === "sandbox" ? spendMtd : sumRange(rawCurrent) * 0.08 * (tenantId === "all" ? 1 : scale),
  };

  const setRules = (envKey: Env, rules: BudgetRule[]) => {
    setBudgets((prev) => prev.map((b) => (b.env === envKey ? { ...b, rules } : b)));
  };

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <BillingHeader
          period={period}
          onPeriod={setPeriod}
          tenantId={tenantId}
          onTenant={setTenantId}
          env={env}
          onEnv={setEnv}
        />

        <div className="min-h-0 flex-1 overflow-y-auto">
          <BillingKpiStrip
            daily={current}
            spendMtd={spendMtd}
            spendPrev={spendPrev}
            costPerCall={costPerCall}
            costPerCallPrev={costPerCallPrev}
            forecast={forecast}
            budgetCap={budgetForEnv.monthlyCapInr}
          />

          <div className="grid gap-4 px-6 py-4 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <SpendTrendChart data={current} />
            </div>
            <div>
              <BudgetPanel
                budgets={budgets}
                spendByEnv={spendByEnv}
                onChangeRules={setRules}
              />
            </div>
          </div>

          <div className="grid gap-4 px-6 pb-4 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <ServiceCostTable
                current={current}
                previous={previous}
                onRowClick={setDrawerService}
              />
            </div>
            <div>
              <ServiceDonut data={current} />
            </div>
          </div>

          <div className="grid gap-4 px-6 pb-6 lg:grid-cols-2">
            <TenantTable current={current} previous={previous} />
            <InvoiceList />
          </div>
        </div>
      </div>

      <ServiceDrawer
        open={!!drawerService}
        onOpenChange={(v) => !v && setDrawerService(null)}
        service={drawerService}
        current={current}
        previous={previous}
      />
    </AppShell>
  );
}
