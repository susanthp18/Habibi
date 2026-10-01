import type { UseNavigateResult } from "@tanstack/react-router";
import type { WorkItem } from "@/api/workspace";

type WorkItemTarget = Pick<WorkItem, "id" | "entityType"> &
  Partial<Pick<WorkItem, "customerId" | "relatedId">>;

/** Route + search for opening a work item in its domain page. */
export function workItemDestination(item: WorkItemTarget) {
  const { id, customerId, relatedId } = item;
  const customer360 = customerId
    ? ({ to: "/customers/$customerId", params: { customerId } } as const)
    : ({ to: "/customers" } as const);
  switch (item.entityType) {
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
      // A promise follow-up opens the promise it chases; any other is the
      // customer's (lead follow-ups are folded into their lead row).
      return relatedId ? ({ to: "/promises", search: { id: relatedId } } as const) : customer360;
    case "bounce":
      return customer360;
  }
}

export function navigateWorkItem(navigate: UseNavigateResult<string>, item: WorkItemTarget): void {
  void navigate(workItemDestination(item));
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
