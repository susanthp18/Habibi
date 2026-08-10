// -----------------------------------------------------------------------------
// Billing & Usage Analytics — live API only (no mock branch).
//   useBilling(period, tenantId, env) → GET /billing
//   Budget rule mutations → POST/PATCH/DELETE /billing/budgets/.../rules
// -----------------------------------------------------------------------------

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  AlertEvent,
  Budget,
  BudgetRule,
  DayPoint,
  Env,
  Invoice,
  Period,
  Service,
  Tenant,
} from "@/data/billing-seed";
import { apiDelete, apiGet, apiPatch, apiPost, API_BASE_URL } from "./config";

export type BillingTenantBreakdown = {
  id: string;
  name: string;
  resolvedCalls: number;
  ahtSec: number;
  budgetInr: number;
  spend: number;
  spendPrev: number;
  costPerCall: number;
  budgetPct: number;
};

export type BillingBudget = Budget & { id: string; month: string };

/**
 * Spend for one (service, model) pair. billing_services has a single blended
 * `llm_chat` row, so this is the only place a gpt-5 turn can be distinguished
 * from a gpt-4o-mini one — they price roughly 8x apart.
 */
export type BillingModelSpend = {
  serviceId: string;
  serviceName: string;
  unit: string;
  color: string;
  model: string;
  units: number;
  costInr: number;
  calls: number;
};

export type BillingOverview = {
  asOf: string;
  period: Period;
  env: Env;
  tenantId: string;
  services: Service[];
  tenants: Tenant[];
  daily: DayPoint[];
  previousDaily: DayPoint[];
  spend: number;
  spendPrev: number;
  forecast: number;
  costPerCall: number;
  costPerCallPrev: number;
  resolvedCalls: number;
  budgetCap: number;
  spendByEnv: Record<string, number>;
  budgets: BillingBudget[];
  alerts: AlertEvent[];
  invoices: Invoice[];
  tenantBreakdown: BillingTenantBreakdown[];
  serviceTenantSpend: Record<string, Record<string, number>>;
  /**
   * Measured cost per call, averaged over calls carrying attributed usage.
   * Distinct from `costPerCall`, which divides all spend by resolved calls —
   * an allocation. 0 with `attributedCalls === 0` means the window predates
   * metering, not that calls were free.
   */
  attributedCostPerCall: number;
  attributedCalls: number;
  modelSpend: BillingModelSpend[];
};

export async function fetchBilling(
  period: Period,
  tenantId: string,
  env: Env,
): Promise<BillingOverview> {
  const qs = new URLSearchParams({ period, tenantId, env });
  return apiGet<BillingOverview>(`/billing?${qs.toString()}`);
}

export function useBilling(period: Period, tenantId: string, env: Env) {
  return useQuery({
    queryKey: ["billing", period, tenantId, env],
    queryFn: () => fetchBilling(period, tenantId, env),
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  });
}

export type BudgetRuleInput = Omit<BudgetRule, "id"> & { id?: string };

export async function saveBudgetRule(
  budgetId: string,
  rule: BudgetRuleInput,
): Promise<BudgetRule> {
  const body = {
    threshold: rule.threshold,
    channels: rule.channels,
    action: rule.action,
    severity: rule.severity,
  };
  if (rule.id) {
    return apiPatch<BudgetRule>(`/billing/budgets/${budgetId}/rules/${rule.id}`, body);
  }
  return apiPost<BudgetRule>(`/billing/budgets/${budgetId}/rules`, body);
}

export async function deleteBudgetRule(budgetId: string, ruleId: string): Promise<void> {
  await apiDelete(`/billing/budgets/${budgetId}/rules/${ruleId}`);
}

export function useBudgetRuleMutations() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["billing"] });

  const save = useMutation({
    mutationFn: ({ budgetId, rule }: { budgetId: string; rule: BudgetRuleInput }) =>
      saveBudgetRule(budgetId, rule),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: ({ budgetId, ruleId }: { budgetId: string; ruleId: string }) =>
      deleteBudgetRule(budgetId, ruleId),
    onSuccess: invalidate,
  });
  return { save, remove };
}

export function billingExportUrl(period: Period, tenantId: string, env: Env): string {
  const qs = new URLSearchParams({ period, tenantId, env });
  return `${API_BASE_URL}/billing/export.csv?${qs.toString()}`;
}

export { changePct, inr, inrCompact, sumRange, usageUnits } from "@/data/billing-seed";
