/**
 * Domain / wire types for the billing surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
 */

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
