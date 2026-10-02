// -----------------------------------------------------------------------------
// My Workspace.
//   GET /work-items        one page of the queue; scope, tab, deadline and search
//                          filters run on the server, so they cover the whole queue
//   GET /workspace/summary my stats, next callback / lead, attention rows, counts
// Shapes are the API's own response models (wire/generated.ts).
// -----------------------------------------------------------------------------

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import type { z } from "zod";

import { apiGet } from "./config";
import type { WorkItemResponse, WorkspaceSummaryResponse } from "./wire/generated";

export type WorkItem = z.infer<typeof WorkItemResponse>;
export type WorkItemEntityType = WorkItem["entityType"];
export type SlaLevel = WorkItem["sla"];
export type WorkspaceSummary = z.infer<typeof WorkspaceSummaryResponse>;

/** ``me``: assigned to me, or unassigned work on customers I own. ``pool``:
 *  unassigned work on unassigned customers. Never switches on its own. */
export type WorkspaceScope = "me" | "pool";
/** ``attention``: overdue or due within two hours, the Needs-attention set. */
export type DueFilter = "attention" | "overdue" | "due_soon" | "later";

export const WORK_PAGE = 50;

/** Operational state goes stale by the minute: refetch on a clock and on focus. */
const LIVE = { staleTime: 15_000, refetchInterval: 60_000, refetchOnWindowFocus: true } as const;

export interface WorkItemQuery {
  scope: WorkspaceScope;
  entityType?: WorkItemEntityType;
  due?: DueFilter;
  q?: string;
  limit?: number;
  offset?: number;
}

export async function fetchWorkItems(query: WorkItemQuery): Promise<WorkItem[]> {
  const params = new URLSearchParams({
    assignee: query.scope,
    limit: String(query.limit ?? WORK_PAGE),
    offset: String(query.offset ?? 0),
  });
  if (query.entityType) params.set("entityType", query.entityType);
  if (query.due) params.set("due", query.due);
  if (query.q?.trim()) params.set("q", query.q.trim());
  return apiGet<WorkItem[]>(`/work-items?${params}`);
}

// No placeholder data on either hook: rows from another scope, tab or filter
// shown while the new read runs are actionable records under the wrong label.

export function useWorkItems(query: WorkItemQuery, opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ["work-items", query],
    queryFn: () => fetchWorkItems(query),
    ...LIVE,
    ...opts,
  });
}

/** The queue a page at a time, by offset. A full page means there may be more. */
export function useWorkItemPages(query: Omit<WorkItemQuery, "limit" | "offset">) {
  return useInfiniteQuery({
    queryKey: ["work-items", "pages", query],
    queryFn: ({ pageParam }) => fetchWorkItems({ ...query, limit: WORK_PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) =>
      last.length === WORK_PAGE ? pages.length * WORK_PAGE : undefined,
    ...LIVE,
  });
}

export function useWorkspaceSummary(scope: WorkspaceScope = "me") {
  return useQuery({
    queryKey: ["workspace-summary", scope],
    queryFn: () => apiGet<WorkspaceSummary>(`/workspace/summary?assignee=${scope}`),
    ...LIVE,
  });
}

/** POSTs that compute and change no record: a prompt lint, a routing or check
 *  dry run, a socket ticket, a treatment decision that is recorded, never enacted. */
const PURE_POSTS =
  /^\/(voice-studio\/(prompt\/lint|routing\/check|checks\/simulate)|studio-api\/_ws-ticket|treatment\/decide)(\/|\?|$)/;

/** Whether a write to ``path`` can change the queue or summary. Every write can,
 *  except the pure computations above: the work_items view draws on many
 *  domains, and an allowlist of them missed the ones that write as a side
 *  effect (an enacted treatment files a follow-up). A wrong guess here costs
 *  one refetch; the other way it cost a stale queue until the next poll. */
export function movesWorkspace(path: string): boolean {
  return !PURE_POSTS.test(path);
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
  const ms = new Date(dueAt).getTime() - now;
  // Rounded away from now: 20 seconds overdue is "Overdue 1m", never "In 0m".
  const span = spanLabel(Math.max(1, Math.ceil(Math.abs(ms) / 60_000)));
  return ms < 0 ? `Overdue ${span}` : `In ${span}`;
}

const RANK: Record<SlaLevel, number> = { ok: 0, warn: 1, breach: 2 };

/** The server's level, raised by the clock between refreshes: the deadline text
 *  counts down locally and its colour must not lag it. Same thresholds as
 *  ``db_workspace._work_item_sla`` (overdue; due within two hours). It only
 *  ever raises, so the server's status-driven levels stand -- except a bounce
 *  awaiting payment, which the server keeps calm whatever its deadline. */
export function liveLevel(
  item: Pick<WorkItem, "sla" | "dueAt" | "entityType" | "status">,
  now: number,
): SlaLevel {
  if (!item.dueAt || (item.entityType === "bounce" && item.status === "in_progress")) {
    return item.sla;
  }
  const left = new Date(item.dueAt).getTime() - now;
  const byClock: SlaLevel = left < 0 ? "breach" : left < 2 * 3_600_000 ? "warn" : "ok";
  return RANK[byClock] > RANK[item.sla] ? byClock : item.sla;
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
