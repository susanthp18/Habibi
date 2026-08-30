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
  LLM: "#357DE8",
  Voice: "#F68909",
  Messaging: "#82B536",
  Infra: "#964AC0",
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

/**
 * Below this, a nonzero value cannot be shown to four decimals and is floored
 * to a "smaller than" reading rather than to a plausible-looking zero.
 */
const COMPACT_EPSILON = 0.0001;

/**
 * Compact Indian money. The canonical ladder, shared with the backend.
 *
 * ```
 * 0                     -> "₹0"
 * 0 < n < 0.0001        -> "<₹0.0001"
 * 0.0001 <= n < 1       -> "₹0.0040"     (4 dp)
 * 1 <= n < 1_000        -> "₹12.50"      (2 dp)
 * 1_000 <= n < 1_00_000 -> "₹1.5k"       (lowercase k, no space)
 * 1_00_000 <= n < 1cr   -> "₹12.3L"
 * n >= 1_00_00_000      -> "₹4.5Cr"
 * negative              -> "-" + the same
 * ```
 *
 * One decimal on every magnitude suffix, so the three read as one ladder
 * rather than three conventions. This used to print "₹12.35L" beside "₹1.5k"
 * — two and one decimals in the same column — and to space the Cr and L
 * suffixes but not the k.
 *
 * Mirrors backend/money_inr.py::inr_compact exactly. Change one, change both:
 * they are read side by side on the billing screen, where a Python value
 * labels a chart whose axis the TypeScript value labels.
 */
export function inrCompact(n: number): string {
  if (n < 0) return `-${inrCompact(-n)}`;
  if (n >= 1_00_00_000) return `₹${(n / 1_00_00_000).toFixed(1)}Cr`;
  if (n >= 1_00_000) return `₹${(n / 1_00_000).toFixed(1)}L`;
  if (n >= 1_000) return `₹${(n / 1_000).toFixed(1)}k`;
  if (n >= 1) return `₹${n.toFixed(2)}`;
  if (n >= COMPACT_EPSILON) return `₹${n.toFixed(4)}`;
  // Real spend, too small to render. Saying so beats rounding it away — a
  // metered call that cost a fraction of a paisa is not a free call.
  if (n > 0) return `<₹${COMPACT_EPSILON.toFixed(4)}`;
  return "₹0";
}

export function usageUnits(spend: number, unitCost: number): number {
  if (unitCost <= 0) return 0;
  return spend / unitCost;
}
