import type { DayPoint, ServiceCategory } from "@/api/types/billing";

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

export function usageUnits(spend: number, unitCost: number): number {
  if (unitCost <= 0) return 0;
  return spend / unitCost;
}
