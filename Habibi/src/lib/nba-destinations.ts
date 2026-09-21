import type { NbaItem } from "@/api/types/customer-insights";

export type TreatmentOpsTab = "mandates" | "field" | "legal" | "cases";

export type NbaDestination =
  | { kind: "none" }
  | { kind: "view_decision"; tab: "cases"; customerId: string }
  | { kind: "callbacks"; customerId: string }
  | { kind: "emi"; customerId: string }
  | { kind: "plan"; customerId: string }
  | { kind: "inbox_or_sheet"; customerId: string }
  | { kind: "place_call"; customerId: string }
  | { kind: "ops"; tab: TreatmentOpsTab; customerId: string }
  | { kind: "ptp" }
  | { kind: "dispute" }
  | { kind: "statement" }
  | { kind: "review" }
  | { kind: "offer"; leadId?: string | null };

/**
 * Where Take action lands. `schedule` is EMI date change, not a callback.
 * Shadow/advisory recommendations are view-only.
 */
export function nbaDestination(item: NbaItem, customerId: string): NbaDestination {
  if (item.action === "wait") return { kind: "none" };
  if (item.advisory) return { kind: "view_decision", tab: "cases", customerId };
  switch (item.action) {
    case "callback":
      return { kind: "callbacks", customerId };
    case "schedule":
      return { kind: "emi", customerId };
    case "plan":
      return { kind: "plan", customerId };
    case "message":
      return { kind: "inbox_or_sheet", customerId };
    case "call":
      return { kind: "place_call", customerId };
    case "mandate":
      return { kind: "ops", tab: "mandates", customerId };
    case "field":
      return { kind: "ops", tab: "field", customerId };
    case "legal":
      return { kind: "ops", tab: "legal", customerId };
    case "ptp":
      return { kind: "ptp" };
    case "dispute":
      return { kind: "dispute" };
    case "statement":
      return { kind: "statement" };
    case "review":
      return { kind: "review" };
    case "offer":
      return { kind: "offer", leadId: item.leadId };
    default:
      return { kind: "view_decision", tab: "cases", customerId };
  }
}

export function nbaPrimaryLabel(item: NbaItem): string | null {
  if (item.action === "wait") return null;
  if (item.advisory) return "View decision";
  return "Take action";
}
