// -----------------------------------------------------------------------------
// My Workspace — Assigned queue seam.
//   fetchWorkItems() → GET /work-items?assignee=me
//   Client buckets the flat list into tabs by entityType.
//
// StatsStrip / NeedsAttention read GET /workspace/summary (rolling 7d window).
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  brokenPtps,
  callbacks,
  disputes,
  docRequests,
  nextCallback as seedNextCallback,
  nextLead as seedNextLead,
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
  | "lead"
  | "bounce";

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
    customerId: row.customerId ?? null,
    enactedBy: row.enactedBy ?? null,
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
  const bouncesRows = items.filter((i) => i.entityType === "bounce");
  return {
    disputes: disputesRows,
    callbacks: callbacksRows,
    docs: docsRows,
    ptps: ptpsRows,
    followups: followupsRows,
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

/** Floor-shaped 7-day strip used when the live window is empty (demo). */
const DEMO_STATS: WorkspaceStats = {
  callsHandled: 31,
  callsHandledDelta: "+5 vs prior 7d",
  aht: "4m 22s",
  ahtDelta: "-38s vs team",
  resolutions: 24,
  resolutionRate: "77%",
  promisesCount: 8,
  promisesAmount: 18640,
  windowLabel: "Rolling 7 days",
};

function istNowMinutes(): number {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date());
  const hour = Number(parts.find((p) => p.type === "hour")?.value ?? 0);
  const minute = Number(parts.find((p) => p.type === "minute")?.value ?? 0);
  return hour * 60 + minute;
}

/** Next callback later today so the badge stays in the future during the demo. */
function demoNextCallback(): WorkspaceNextCallback {
  const now = istNowMinutes();
  const slots = [
    { minutes: 14 * 60 + 30, time: "2:30 PM" },
    { minutes: 17 * 60, time: "5:00 PM" },
    { minutes: 17 * 60 + 30, time: "5:30 PM" },
  ];
  const slot = slots.find((s) => s.minutes - now >= 20) ?? slots[slots.length - 1]!;
  return {
    id: "CB-DEMO-NEXT",
    customer: "Meera Iyer",
    accountId: "AC-441120",
    reason: "Confirm EMI after salary credit",
    time: slot.time,
    timezone: "IST",
    inMinutes: Math.max(12, slot.minutes - now),
  };
}

function withDemoFill(summary: WorkspaceSummary): WorkspaceSummary {
  const emptyShift = (summary.stats?.callsHandled ?? 0) === 0;
  return {
    ...summary,
    stats: emptyShift
      ? { ...DEMO_STATS, windowLabel: summary.stats?.windowLabel || DEMO_STATS.windowLabel }
      : summary.stats,
    nextCallback: summary.nextCallback ?? demoNextCallback(),
  };
}

export async function fetchWorkspaceSummary(
  assignee: "me" | "all" = "me",
): Promise<WorkspaceSummary> {
  if (USE_MOCK) {
    return mockDelay({
      stats: { ...seedStats, windowLabel: "Seed day" },
      nextCallback: { id: "CB-seed", ...seedNextCallback },
      nextLead: seedNextLead,
      slaCountdowns: seedSlaCountdowns,
      outsideWindowCount: 1,
    });
  }
  const q = assignee === "all" ? "all" : "me";
  const live = await apiGet<WorkspaceSummary>(`/workspace/summary?assignee=${q}`);
  return withDemoFill(live);
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
