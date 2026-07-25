// -----------------------------------------------------------------------------
// My Workspace — Assigned queue seam.
//   fetchWorkItems() → GET /work-items?assignee=me
//   Client buckets the flat list into tabs by entityType.
//
// StatsStrip / RightRail now read GET /workspace/summary (rolling 7d window).
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  brokenPtps,
  callbacks,
  disputes,
  docRequests,
  nextCallback as seedNextCallback,
  slaCountdowns as seedSlaCountdowns,
  stats as seedStats,
  type QueueRow,
  type SlaLevel,
} from "@/data/workspace-seed";
import { apiGet, mockDelay, USE_MOCK } from "./config";

export type WorkItemEntityType =
  | "dispute"
  | "callback"
  | "document_request"
  | "promise"
  | "followup"
  | "lead";

export interface WorkItem extends QueueRow {
  entityType: WorkItemEntityType;
  status?: string | null;
  assigneeUserId?: string | null;
}

interface WorkItemApi {
  id: string;
  customer: string;
  accountId: string;
  type: string;
  detail: string;
  amount?: number | null;
  ageHours: number;
  sla: SlaLevel;
  slaLabel: string;
  entityType: WorkItemEntityType;
  status?: string | null;
  assigneeUserId?: string | null;
}

function mapWorkItem(row: WorkItemApi): WorkItem {
  const amount =
    row.amount === null || row.amount === undefined ? undefined : Number(row.amount);
  return {
    id: row.id,
    customer: row.customer ?? "Unknown",
    accountId: row.accountId ?? "",
    type: row.type ?? "",
    detail: row.detail ?? "",
    amount: Number.isFinite(amount as number) ? amount : undefined,
    ageHours: Number(row.ageHours) || 0,
    sla: row.sla,
    slaLabel: row.slaLabel ?? "",
    entityType: row.entityType,
    status: row.status ?? null,
    assigneeUserId: row.assigneeUserId ?? null,
  };
}

/** Mock: stitch the four seed arrays (no followups/leads in the seed tabs). */
function mockWorkItems(): WorkItem[] {
  return [
    ...disputes.map((r) => ({ ...r, entityType: "dispute" as const })),
    ...callbacks.map((r) => ({ ...r, entityType: "callback" as const })),
    ...docRequests.map((r) => ({ ...r, entityType: "document_request" as const })),
    ...brokenPtps.map((r) => ({ ...r, entityType: "promise" as const })),
  ];
}

export async function fetchWorkItems(assignee: "me" | "all" = "me"): Promise<WorkItem[]> {
  if (USE_MOCK) return mockDelay(mockWorkItems());
  const q = assignee === "all" ? "all" : "me";
  const rows = await apiGet<WorkItemApi[]>(`/work-items?assignee=${q}`);
  return rows.map(mapWorkItem);
}

export function useWorkItems(assignee: "me" | "all" = "me") {
  return useQuery({
    queryKey: ["work-items", assignee],
    queryFn: () => fetchWorkItems(assignee),
    staleTime: 15_000,
  });
}

/** Tab buckets used by AssignedQueue. Leads are intentionally omitted (Upsell). */
export function bucketWorkItems(items: WorkItem[]) {
  const disputesRows = items.filter((i) => i.entityType === "dispute");
  const callbacksRows = items.filter((i) => i.entityType === "callback");
  const docsRows = items.filter((i) => i.entityType === "document_request");
  // View already excludes pending; broken/partial (+ due_today if present).
  const ptpsRows = items.filter((i) => {
    if (i.entityType !== "promise") return false;
    const status = (i.status ?? "").toLowerCase();
    // Prefer broken/partial; include due_today as chase-worthy; never pending.
    if (!status) return true;
    return status === "broken" || status === "partial" || status === "due_today";
  });
  const followupsRows = items.filter((i) => i.entityType === "followup");
  return {
    disputes: disputesRows,
    callbacks: callbacksRows,
    docs: docsRows,
    ptps: ptpsRows,
    followups: followupsRows,
  };
}

export interface WorkspaceStats {
  callsHandled: number;
  callsHandledDelta: string;
  aht: string;
  ahtDelta: string;
  resolutions: number;
  resolutionRate: string;
  promisesCount: number;
  promisesAmount: number;
  windowLabel: string;
}

export interface WorkspaceNextCallback {
  id: string;
  customer: string;
  accountId: string;
  reason: string;
  time: string;
  timezone: string;
  inMinutes: number;
}

export interface WorkspaceSlaCountdown {
  id: string;
  label: string;
  remaining: string;
  level: SlaLevel;
}

export interface WorkspaceSummary {
  stats: WorkspaceStats;
  nextCallback: WorkspaceNextCallback | null;
  slaCountdowns: WorkspaceSlaCountdown[];
  outsideWindowCount: number;
}

export async function fetchWorkspaceSummary(
  assignee: "me" | "all" = "me",
): Promise<WorkspaceSummary> {
  if (USE_MOCK) {
    return mockDelay({
      stats: { ...seedStats, windowLabel: "Seed day" },
      nextCallback: { id: "CB-seed", ...seedNextCallback },
      slaCountdowns: seedSlaCountdowns,
      outsideWindowCount: 1,
    });
  }
  const q = assignee === "all" ? "all" : "me";
  return apiGet<WorkspaceSummary>(`/workspace/summary?assignee=${q}`);
}

export function useWorkspaceSummary(assignee: "me" | "all" = "me") {
  return useQuery({
    queryKey: ["workspace-summary", assignee],
    queryFn: () => fetchWorkspaceSummary(assignee),
    staleTime: 30_000,
  });
}
