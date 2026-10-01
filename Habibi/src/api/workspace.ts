// -----------------------------------------------------------------------------
// My Workspace.
//   GET /work-items        one page of the queue; scope, tab, deadline and search
//                          filters run on the server, so they cover the whole queue
//   GET /workspace/summary my stats, next callback / lead, attention rows, counts
// Shapes are the API's own response models (wire/generated.ts).
// -----------------------------------------------------------------------------

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { z } from "zod";

import { apiGet } from "./config";
import type { WorkItemResponse, WorkspaceSummaryResponse } from "./wire/generated";

export type WorkItem = z.infer<typeof WorkItemResponse>;
export type WorkItemEntityType = WorkItem["entityType"];
export type SlaLevel = WorkItem["sla"];
export type WorkspaceSummary = z.infer<typeof WorkspaceSummaryResponse>;
export type WorkspaceNextCallback = NonNullable<WorkspaceSummary["nextCallback"]>;

/** ``me``: assigned to me, or unassigned work on customers I own. ``pool``:
 *  unassigned work on unassigned customers. Never switches on its own. */
export type WorkspaceScope = "me" | "pool";
export type DueFilter = "overdue" | "due_soon" | "later";

export const WORK_PAGE = 50;

/** Operational state goes stale by the minute: refetch on a clock and on focus. */
const LIVE = { staleTime: 15_000, refetchInterval: 60_000, refetchOnWindowFocus: true } as const;

export interface WorkItemQuery {
  scope: WorkspaceScope;
  entityType?: WorkItemEntityType;
  due?: DueFilter;
  q?: string;
  limit?: number;
}

export async function fetchWorkItems(query: WorkItemQuery): Promise<WorkItem[]> {
  const params = new URLSearchParams({
    assignee: query.scope,
    limit: String(query.limit ?? WORK_PAGE),
  });
  if (query.entityType) params.set("entityType", query.entityType);
  if (query.due) params.set("due", query.due);
  if (query.q?.trim()) params.set("q", query.q.trim());
  return apiGet<WorkItem[]>(`/work-items?${params}`);
}

export function useWorkItems(query: WorkItemQuery, opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ["work-items", query],
    queryFn: () => fetchWorkItems(query),
    placeholderData: keepPreviousData,
    ...LIVE,
    ...opts,
  });
}

export function useWorkspaceSummary(scope: WorkspaceScope = "me") {
  return useQuery({
    queryKey: ["workspace-summary", scope],
    queryFn: () => apiGet<WorkspaceSummary>(`/workspace/summary?assignee=${scope}`),
    placeholderData: keepPreviousData,
    ...LIVE,
  });
}

export function enactedByLabel(value?: string | null): string | null {
  if (!value) return null;
  if (value === "clerk_agent") return "Clerk";
  if (value === "treatment_executor") return "Treatment";
  if (value === "human") return "Human";
  if (value === "tuner") return "Tuner";
  return value.replace(/_/g, " ");
}

/** "Overdue 3d 4h" / "In 45m" from a due time, against ``now``. */
export function dueLabel(dueAt: string, now: number): string {
  const mins = Math.round((new Date(dueAt).getTime() - now) / 60_000);
  const span = spanLabel(Math.abs(mins));
  return mins < 0 ? `Overdue ${span}` : `In ${span}`;
}

/** 3d 4h · 5h 10m · 25m */
export function spanLabel(totalMins: number): string {
  const d = Math.floor(totalMins / 1440);
  const h = Math.floor((totalMins % 1440) / 60);
  const m = totalMins % 60;
  if (d) return h ? `${d}d ${h}h` : `${d}d`;
  if (h) return m ? `${h}h ${m}m` : `${h}h`;
  return `${m}m`;
}
