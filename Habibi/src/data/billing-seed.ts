export type Env = "production" | "sandbox";
export type Period = "mtd" | "7d" | "30d" | "quarter";
export type ServiceCategory = "LLM" | "Voice" | "Messaging" | "Infra";

export type Service = {
  id: string;
  name: string;
  provider: string;
  category: ServiceCategory;
  unit: string;
  unitCostInr: number;
  color: string;
};

export type DayPoint = {
  date: string;
  values: Record<string, number>;
};

export type Tenant = {
  id: string;
  name: string;
  resolvedCalls: number;
  ahtSec: number;
  budgetInr: number;
  spendShare: number;
};

export type Invoice = {
  id: string;
  month: string;
  status: "paid" | "pending" | "draft";
  amountInr: number;
  issuedAt: string;
};

export type BudgetRule = {
  id: string;
  threshold: number;
  channels: string[];
  action: string;
  severity: "info" | "warn" | "critical";
};

export type Budget = {
  env: Env;
  monthlyCapInr: number;
  rules: BudgetRule[];
};

export type AlertEvent = {
  id: string;
  when: string;
  ruleId: string;
  env: Env;
  message: string;
};

export const CATEGORY_COLORS: Record<ServiceCategory, string> = {
  LLM: "#3b82f6",
  Voice: "#f97316",
  Messaging: "#22c55e",
  Infra: "#64748b",
};

export function sumRange(rows: DayPoint[], serviceId?: string): number {
  return rows.reduce((s, r) => {
    if (serviceId) return s + (r.values[serviceId] ?? 0);
    return s + Object.values(r.values).reduce((a, b) => a + b, 0);
  }, 0);
}

export function changePct(current: number, previous: number): number {
  if (previous === 0) return current === 0 ? 0 : 100;
  return ((current - previous) / previous) * 100;
}

export function inr(n: number): string {
  return "₹" + Math.round(n).toLocaleString("en-IN");
}

export function inrCompact(n: number): string {
  if (n < 0) return `-${inrCompact(-n)}`;
  if (n >= 1_00_00_000) return `₹${(n / 1_00_00_000).toFixed(2)} Cr`;
  if (n >= 1_00_000) return `₹${(n / 1_00_000).toFixed(2)} L`;
  if (n >= 1_000) return `₹${(n / 1_000).toFixed(1)}k`;
  if (n >= 1) return `₹${n.toFixed(2)}`;
  if (n > 0) return `₹${n.toFixed(4)}`;
  return "₹0";
}

export function usageUnits(spend: number, unitCost: number): number {
  if (unitCost <= 0) return 0;
  return spend / unitCost;
}
