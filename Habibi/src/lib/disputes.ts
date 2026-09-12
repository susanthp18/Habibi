import type {
  DisputeStatus,
  DisputeType,
  DisputeSource,
  DisputePriority,
  ResolutionCode,
  DisputeEvent,
  Evidence,
  DisputeRecord,
  Dispute,
  DisputeFilters,
} from "@/api/types/disputes";

export const STATUS_ORDER: DisputeStatus[] = [
  "new",
  "under_review",
  "awaiting_customer",
  "resolved",
  "rejected",
];

export const STATUS_LABELS: Record<DisputeStatus, string> = {
  new: "New",
  under_review: "Under Review",
  awaiting_customer: "Awaiting Customer",
  resolved: "Resolved",
  rejected: "Rejected",
};

export const TYPE_LABELS: Record<DisputeType, string> = {
  paid_already: "Paid already",
  wrong_amount: "Wrong amount",
  not_my_account: "Not my account",
  fee_waiver: "Fee waiver request",
  duplicate_charge: "Duplicate charge",
  fraud: "Fraud / unauthorised",
};

export const SOURCE_LABELS: Record<DisputeSource, string> = {
  bot_voice: "Bot · Voice",
  bot_chat: "Bot · Chat",
  agent: "Agent",
};

export const RESOLUTION_LABELS: Record<ResolutionCode, string> = {
  valid_waive_fee: "Valid — waive fee",
  valid_reverse_charge: "Valid — reverse charge",
  invalid_no_action: "Invalid — no action",
  duplicate: "Duplicate dispute",
  needs_more_info: "Needs more information",
};

// ---- helpers ----
const now = new Date();

export const defaultFilters: DisputeFilters = {
  search: "",
  types: [],
  sources: [],
  assignee: "all",
  sla: "all",
  amount: "any",
  myQueue: false,
};

export function filterDisputes(
  list: Dispute[],
  f: DisputeFilters,
  me: string | undefined,
): Dispute[] {
  return list.filter((d) => {
    if (f.myQueue && d.assignee !== me) return false;
    if (f.assignee !== "all" && d.assignee !== f.assignee) return false;
    if (f.types.length > 0 && !f.types.includes(d.type)) return false;
    if (f.sources.length > 0 && !f.sources.includes(d.source)) return false;
    if (f.search) {
      const q = f.search.toLowerCase();
      const hay = `${d.customerName} ${d.accountId} ${d.id} ${d.transcriptSnippet}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    if (f.amount !== "any") {
      const a = d.disputedAmount;
      if (f.amount === "lt5" && a >= 5000) return false;
      if (f.amount === "5to25" && (a < 5000 || a > 25000)) return false;
      if (f.amount === "gt25" && a <= 25000) return false;
    }
    if (f.sla !== "all") {
      if (f.sla === "at_risk" && d.sla !== "warn") return false;
      if (f.sla === "breached" && d.sla !== "breach") return false;
    }
    return true;
  });
}

// ---- Metrics ----
export function computeMetrics(list: Dispute[]) {
  const open = list.filter((d) => d.status !== "resolved" && d.status !== "rejected");
  const breaching = open.filter((d) => d.sla === "breach");
  const ages = open.map((d) => (Date.now() - new Date(d.capturedAt).getTime()) / 3600000);
  const avgAgeHrs =
    ages.length === 0 ? 0 : Math.round(ages.reduce((a, b) => a + b, 0) / ages.length);
  const dayAgo = Date.now() - 86400000;
  const resolvedToday = list.filter(
    (d) =>
      d.status === "resolved" &&
      new Date(d.events[d.events.length - 1]?.at ?? d.capturedAt).getTime() >= dayAgo,
  ).length;
  const weekAgo = Date.now() - 7 * 86400000;
  const closedLast7 = list.filter(
    (d) =>
      (d.status === "resolved" || d.status === "rejected") &&
      new Date(d.events[d.events.length - 1]?.at ?? d.capturedAt).getTime() >= weekAgo,
  );
  const resolvedLast7 = closedLast7.filter((d) => d.status === "resolved").length;
  const resolutionRate =
    closedLast7.length === 0 ? 0 : Math.round((resolvedLast7 / closedLast7.length) * 100);

  const counts: Record<DisputeStatus, number> = {
    new: 0,
    under_review: 0,
    awaiting_customer: 0,
    resolved: 0,
    rejected: 0,
  };
  const subtotals: Record<DisputeStatus, number> = { ...counts };
  list.forEach((d) => {
    counts[d.status] += 1;
    subtotals[d.status] += d.disputedAmount;
  });

  return {
    openCount: open.length,
    openAmt: open.reduce((s, d) => s + d.disputedAmount, 0),
    breachingCount: breaching.length,
    avgAgeHrs,
    resolvedToday,
    resolutionRate,
    counts,
    subtotals,
  };
}
