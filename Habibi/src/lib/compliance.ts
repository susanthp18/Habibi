import type {
  ComplianceFilterState,
  Severity,
  Violation,
  ViolationStatus,
} from "@/api/types/compliance";

export function severityWeight(s: Severity): number {
  return s === "critical" ? 4 : s === "high" ? 3 : s === "medium" ? 2 : 1;
}

export function severityColor(s: Severity): string {
  switch (s) {
    case "critical":
      return "var(--danger)";
    case "high":
      return "var(--warning)";
    case "medium":
      return "var(--sentiment-neutral)";
    case "low":
      return "var(--text-muted)";
  }
}

export function severityBg(s: Severity): string {
  switch (s) {
    case "critical":
      return "var(--danger-bg)";
    case "high":
      return "var(--warning-bg)";
    case "medium":
      return "var(--warning-bg)";
    case "low":
      return "var(--surface-sunken)";
  }
}

export function statusLabel(s: ViolationStatus): string {
  return s === "open"
    ? "Open"
    : s === "in_review"
      ? "In review"
      : s === "acknowledged"
        ? "Acknowledged"
        : "Resolved";
}

export const defaultCompFilters: ComplianceFilterState = {
  q: "",
  dateRange: "30d",
  severities: new Set<Severity>(),
  ruleId: "all",
  actor: "all",
  agent: "all",
  status: "all",
};

export function filterViolations(all: Violation[], f: ComplianceFilterState): Violation[] {
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
  return all.filter((v) => {
    if (cutoff && new Date(v.occurredAt).getTime() < cutoff) return false;
    if (f.severities.size > 0 && !f.severities.has(v.severity)) return false;
    if (f.ruleId !== "all" && v.ruleId !== f.ruleId) return false;
    if (f.actor !== "all" && v.actor.kind !== f.actor) return false;
    if (f.agent !== "all" && v.actor.name !== f.agent) return false;
    if (f.status !== "all" && v.status !== f.status) return false;
    if (q) {
      const hay =
        `${v.id} ${v.callId} ${v.customerName} ${v.actor.name} ${v.evidence.snippet} ${v.evidence.offending.text}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

export function trendByDay(
  all: Violation[],
  days = 30,
): Array<{
  day: string;
  critical: number;
  high: number;
  medium: number;
  low: number;
  total: number;
}> {
  const buckets: Record<string, { critical: number; high: number; medium: number; low: number }> =
    {};
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now.getTime() - i * 86400_000);
    buckets[d.toISOString().slice(0, 10)] = { critical: 0, high: 0, medium: 0, low: 0 };
  }
  for (const v of all) {
    const key = v.occurredAt.slice(0, 10);
    const b = buckets[key];
    if (b) b[v.severity]++;
  }
  return Object.entries(buckets).map(([day, b]) => ({
    day: day.slice(5),
    ...b,
    total: b.critical + b.high + b.medium + b.low,
  }));
}

export interface RuleHits {
  ruleId: string;
  code: string;
  label: string;
  severity: Severity;
  count: number;
  open: number;
}

/** Violations grouped by the rule they name, most open first. */
export function groupByRule(all: Violation[]): RuleHits[] {
  const map = new Map<string, RuleHits>();
  for (const v of all) {
    const cur = map.get(v.ruleId) ?? {
      ruleId: v.ruleId,
      code: v.ruleCode,
      label: v.ruleLabel,
      severity: v.severity,
      count: 0,
      open: 0,
    };
    cur.count++;
    if (v.status === "open" || v.status === "in_review") cur.open++;
    map.set(v.ruleId, cur);
  }
  return Array.from(map.values()).sort((a, b) => b.open - a.open || b.count - a.count);
}

export function listActorNames(all: Violation[]): string[] {
  return Array.from(new Set(all.map((v) => v.actor.name))).sort();
}

export function botHumanShare(all: Violation[]): { bot: number; human: number } {
  return all.reduce(
    (acc, v) => {
      acc[v.actor.kind]++;
      return acc;
    },
    { bot: 0, human: 0 },
  );
}
