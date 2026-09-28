// -----------------------------------------------------------------------------
// My Workspace — Assigned queue seam.
//   fetchWorkItems() → GET /work-items?assignee=me
//   Client buckets the flat list into tabs by entityType.
//
// StatsStrip / NeedsAttention read GET /workspace/summary (rolling 7d window).
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import type { QueueRow, SlaLevel } from "@/api/types/workspace";
import { apiGet } from "./config";

export type WorkItemEntityType =
  "dispute" | "callback" | "document_request" | "promise" | "followup" | "lead" | "bounce";

export interface WorkItem extends QueueRow {
  entityType: WorkItemEntityType;
  status?: string | null;
  assigneeUserId?: string | null;
  customerId?: string | null;
  enactedBy?: string | null;
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
  customerId?: string | null;
  enactedBy?: string | null;
}

function mapWorkItem(row: WorkItemApi): WorkItem {
  const amount = row.amount === null || row.amount === undefined ? undefined : Number(row.amount);
  return {
    id: row.id,
    customer: row.customer ?? "Unknown",
    accountId: row.accountId ?? "",
    type: row.type ?? "",
    detail: row.detail ?? "",
    amount: amount !== undefined && Number.isFinite(amount) ? amount : undefined,
    ageHours: Number(row.ageHours) || 0,
    sla: row.sla,
    slaLabel: row.slaLabel ?? "",
    entityType: row.entityType,
    status: row.status ?? null,
    assigneeUserId: row.assigneeUserId ?? null,
    customerId: row.customerId ?? null,
    enactedBy: row.enactedBy ?? null,
  };
}

export async function fetchWorkItems(assignee: "me" | "all" = "me"): Promise<WorkItem[]> {
  const q = assignee === "all" ? "all" : "me";
  const rows = await apiGet<WorkItemApi[]>(`/work-items?assignee=${q}`);
  return rows.map(mapWorkItem);
}

export function useWorkItems(assignee: "me" | "all" = "me") {
  return useQuery({
    queryKey: ["work-items", assignee],
    queryFn: () => fetchWorkItems(assignee),
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
  const leadsRows = items.filter((i) => i.entityType === "lead");
  const bouncesRows = items.filter((i) => i.entityType === "bounce");
  return {
    disputes: disputesRows,
    callbacks: callbacksRows,
    docs: docsRows,
    ptps: ptpsRows,
    followups: followupsRows,
    leads: leadsRows,
    bounces: bouncesRows,
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

export interface WorkspaceNextLead {
  id: string;
  customer: string;
  accountId: string;
  productName: string;
  amount: number | null;
  stage: string;
  window: string | null;
  reason: string;
}

export interface WorkspaceSlaCountdown {
  id: string;
  label: string;
  remaining: string;
  level: SlaLevel;
  enactedBy?: string | null;
}

export interface WorkspaceSummary {
  stats: WorkspaceStats;
  nextCallback: WorkspaceNextCallback | null;
  nextLead: WorkspaceNextLead | null;
  slaCountdowns: WorkspaceSlaCountdown[];
  outsideWindowCount: number;
}

export async function fetchWorkspaceSummary(
  assignee: "me" | "all" = "me",
): Promise<WorkspaceSummary> {
  const q = assignee === "all" ? "all" : "me";
  return apiGet<WorkspaceSummary>(`/workspace/summary?assignee=${q}`);
}

export function enactedByLabel(value?: string | null): string | null {
  if (!value) return null;
  if (value === "clerk_agent") return "Clerk";
  if (value === "treatment_executor") return "Treatment";
  if (value === "human") return "Human";
  if (value === "tuner") return "Tuner";
  return value.replace(/_/g, " ");
}

export function useWorkspaceSummary(assignee: "me" | "all" = "me") {
  return useQuery({
    queryKey: ["workspace-summary", assignee],
    queryFn: () => fetchWorkspaceSummary(assignee),
    staleTime: 30_000,
  });
}
