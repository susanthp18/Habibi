import type { AuditFilterState, CallRecord, Disposition, SentimentBucket } from "@/api/types/audit";

/** Runtime `interactions.disposition` values — the Audit filter must match these. */
export const DISPOSITIONS: Disposition[] = [
  "ptp_captured",
  "upsell_interest",
  "query_handled",
  "completed",
  "escalated",
  "crm_degraded",
  "voicemail",
  "no_answer",
  "no_upsell",
];

export const DISPOSITION_LABELS: Record<Disposition, string> = {
  ptp_captured: "PTP captured",
  upsell_interest: "Upsell interest",
  query_handled: "Query handled",
  completed: "Completed",
  escalated: "Escalated",
  crm_degraded: "CRM degraded",
  voicemail: "Voicemail",
  no_answer: "No answer",
  no_upsell: "No upsell",
};

export function dispositionLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return DISPOSITION_LABELS[value as Disposition] ?? value;
}

// ---------- filters ----------

export const defaultFilters: AuditFilterState = {
  q: "",
  dateRange: "30d",
  channel: "all",
  handler: "all",
  agent: "all",
  disposition: "all",
  sentiment: "all",
  flaggedOnly: false,
};

export function sentimentBucket(v: number): SentimentBucket {
  if (v >= 0.2) return "positive";
  if (v <= -0.2) return "negative";
  return "neutral";
}

/** The agents on the calls in scope, for the filter dropdown. */
export function listAgents(calls: CallRecord[]): string[] {
  const s = new Set<string>();
  for (const c of calls) if (c.handledBy.agent) s.add(c.handledBy.agent);
  return Array.from(s).sort();
}

export function filterCalls(all: CallRecord[], f: AuditFilterState): CallRecord[] {
  const now = Date.now();
  const cutoff =
    f.dateRange === "today"
      ? now - 86400_000
      : f.dateRange === "7d"
        ? now - 7 * 86400_000
        : f.dateRange === "30d"
          ? now - 30 * 86400_000
          : 0;
  const q = f.q.trim().toLowerCase();
  return all.filter((c) => {
    if (cutoff && (!c.startedAt || new Date(c.startedAt).getTime() < cutoff)) return false;
    if (f.channel !== "all" && c.channel !== f.channel) return false;
    if (f.handler !== "all" && c.handledBy.kind !== f.handler) return false;
    if (f.agent !== "all" && c.handledBy.agent !== f.agent) return false;
    if (f.disposition !== "all" && c.disposition !== f.disposition) return false;
    if (f.sentiment !== "all") {
      if (c.avgSentiment == null) return false;
      if (sentimentBucket(c.avgSentiment) !== f.sentiment) return false;
    }
    if (f.flaggedOnly && c.flags.length === 0) return false;
    if (q) {
      const hay =
        `${c.id} ${c.customerName} ${c.phoneMasked} ${c.accountId ?? ""} ${c.disposition ?? ""} ${c.summary ?? ""} ${c.transcript.map((t) => t.text).join(" ")}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

export function sentimentColor(v: number): string {
  if (v >= 0.2) return "var(--sentiment-positive)";
  if (v <= -0.2) return "var(--sentiment-negative)";
  return "var(--sentiment-neutral)";
}
