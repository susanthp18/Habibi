import type { UseNavigateResult } from "@tanstack/react-router";
import type { WorkItem, WorkItemEntityType } from "@/api/workspace";

/** Route + search for opening a work-item entity in its domain page. */
export function workItemDestination(
  entityType: WorkItemEntityType | (string & {}),
  id: string,
  customerId?: string | null,
) {
  switch (entityType) {
    case "dispute":
      return { to: "/disputes", search: { id } } as const;
    case "callback":
      return { to: "/callbacks", search: { id } } as const;
    case "document_request":
      return { to: "/documents", search: { id } } as const;
    case "promise":
      return { to: "/promises", search: { id } } as const;
    case "lead":
      return { to: "/upsell", search: { id } } as const;
    case "followup":
      // Follow-ups are promise/lead chase items — land on Promises (broken PTP home).
      return { to: "/promises" } as const;
    case "bounce":
      if (customerId) {
        return { to: "/customers/$customerId", params: { customerId } } as const;
      }
      return { to: "/customers" } as const;
    default:
      return { to: "/" } as const;
  }
}

export function navigateWorkItem(
  navigate: UseNavigateResult<string>,
  item:
    | Pick<WorkItem, "id" | "entityType" | "customerId">
    | { id: string; entityType: string; customerId?: string | null },
): void {
  void navigate(workItemDestination(item.entityType, item.id, item.customerId));
}

/** Infer entity type from SLA countdown label prefixes produced by workspace_summary. */
export function entityTypeFromSlaLabel(label: string): WorkItemEntityType | null {
  const head = label.split("·")[0]?.trim().toLowerCase() ?? "";
  if (head.startsWith("dispute")) return "dispute";
  if (head.startsWith("broken ptp") || head.startsWith("promise") || head.startsWith("ptp"))
    return "promise";
  if (head.startsWith("doc")) return "document_request";
  if (head.startsWith("callback")) return "callback";
  if (head.startsWith("follow")) return "followup";
  if (head.startsWith("bounce") || head.startsWith("emi bounce")) return "bounce";
  if (head.startsWith("lead")) return "lead";
  return null;
}

export type DeepLinkSearch = { id?: string; new?: boolean; customerId?: string; plan?: boolean };

export function parseDeepLinkSearch(search: Record<string, unknown>): DeepLinkSearch {
  const id = typeof search.id === "string" && search.id.length > 0 ? search.id : undefined;
  const rawNew = search.new;
  const isNew =
    rawNew === true || rawNew === "1" || rawNew === "true" || rawNew === 1 ? true : undefined;
  const customerId =
    typeof search.customerId === "string" && search.customerId.length > 0
      ? search.customerId
      : undefined;
  const rawPlan = search.plan;
  const isPlan =
    rawPlan === true || rawPlan === "1" || rawPlan === "true" || rawPlan === 1 ? true : undefined;
  return { id, new: isNew, customerId, plan: isPlan };
}
