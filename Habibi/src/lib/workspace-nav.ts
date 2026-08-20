import type { WorkItem, WorkItemEntityType } from "@/api/workspace";

/** Route + search for opening a work-item entity in its domain page. */
export function workItemDestination(
  entityType: WorkItemEntityType | string,
  id: string,
  customerId?: string | null,
): { to: string; search?: Record<string, string | boolean>; params?: Record<string, string> } {
  switch (entityType) {
    case "dispute":
      return { to: "/disputes", search: { id } };
    case "callback":
      return { to: "/callbacks", search: { id } };
    case "document_request":
      return { to: "/documents", search: { id } };
    case "promise":
      return { to: "/promises", search: { id } };
    case "lead":
      return { to: "/upsell", search: { id } };
    case "followup":
      // Follow-ups are promise/lead chase items — land on Promises (broken PTP home).
      return { to: "/promises" };
    case "bounce":
      if (customerId) {
        return { to: "/customers/$customerId", params: { customerId } };
      }
      return { to: "/customers" };
    default:
      return { to: "/" };
  }
}

type NavigateFn = (opts: {
  to: string;
  search?: Record<string, unknown>;
  params?: Record<string, string>;
  replace?: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
}) => unknown;

export function navigateWorkItem(
  // Accept router navigate without fighting TanStack's branded search types.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  navigate: (opts: any) => unknown,
  item: Pick<WorkItem, "id" | "entityType" | "customerId"> | { id: string; entityType: string; customerId?: string | null },
): void {
  const dest = workItemDestination(item.entityType, item.id, item.customerId);
  void navigate({ to: dest.to, search: dest.search, params: dest.params });
}

/** Infer entity type from SLA countdown label prefixes produced by workspace_summary. */
export function entityTypeFromSlaLabel(label: string): WorkItemEntityType | null {
  const head = label.split("·")[0]?.trim().toLowerCase() ?? "";
  if (head.startsWith("dispute")) return "dispute";
  if (head.startsWith("broken ptp") || head.startsWith("promise") || head.startsWith("ptp")) return "promise";
  if (head.startsWith("doc")) return "document_request";
  if (head.startsWith("callback")) return "callback";
  if (head.startsWith("follow")) return "followup";
  if (head.startsWith("bounce") || head.startsWith("emi bounce")) return "bounce";
  if (head.startsWith("lead")) return "lead";
  return null;
}

export type DeepLinkSearch = { id?: string; new?: boolean };

export function parseDeepLinkSearch(search: Record<string, unknown>): DeepLinkSearch {
  const id = typeof search.id === "string" && search.id.length > 0 ? search.id : undefined;
  const rawNew = search.new;
  const isNew =
    rawNew === true || rawNew === "1" || rawNew === "true" || rawNew === 1 ? true : undefined;
  return { id, new: isNew };
}
