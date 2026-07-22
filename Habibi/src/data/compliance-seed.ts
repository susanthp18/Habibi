// Compliance Risk — rule-hit violations derived from audit call records.
import { calls, type CallRecord, type TranscriptTurn } from "./audit-seed";

export type Severity = "critical" | "high" | "medium" | "low";
export type ViolationStatus = "open" | "in_review" | "acknowledged" | "resolved";
export type ActorKind = "bot" | "human";
export type RuleCategory = "disclosure" | "prohibited-language" | "consent" | "verification" | "sentiment";

export interface ComplianceRule {
  id: string;
  code: string;
  label: string;
  category: RuleCategory;
  severity: Severity;
  description: string;
}

export interface ViolationNote {
  at: string;
  author: string;
  text: string;
}

export interface Violation {
  id: string;
  callId: string;
  customerName: string;
  ruleId: string;
  severity: Severity;
  occurredAt: string;
  atSec: number;
  actor: { kind: ActorKind; name: string };
  evidence: {
    snippet: string;
    preceding?: TranscriptTurn;
    offending: TranscriptTurn;
    following?: TranscriptTurn;
  };
  status: ViolationStatus;
  assignee?: string;
  notes: ViolationNote[];
}

export const RULES: ComplianceRule[] = [
  { id: "r-rec", code: "RBI-DISC-01", label: "Missed call recording notice", category: "disclosure", severity: "high", description: "Agent/bot must announce the call is recorded within the first 15 seconds." },
  { id: "r-mm", code: "RBI-DISC-02", label: "Missed Mini-Miranda disclosure", category: "disclosure", severity: "critical", description: "Debt collection identification is mandatory on every outbound collections call." },
  { id: "r-dnd-disc", code: "RBI-DISC-03", label: "Missed DND / opt-out reminder", category: "disclosure", severity: "medium", description: "Customer must be reminded of the DND / opt-out channel on every substantive interaction." },
  { id: "r-disp", code: "RBI-DISC-04", label: "Missed right-to-dispute notice", category: "disclosure", severity: "medium", description: "Customer must be informed of their right to dispute the debt." },
  { id: "r-threat", code: "PROH-LANG-01", label: "Threatening language", category: "prohibited-language", severity: "critical", description: "Any language implying arrest, harm, or unlawful consequence is prohibited." },
  { id: "r-abuse", code: "PROH-LANG-02", label: "Abusive / disrespectful tone", category: "prohibited-language", severity: "high", description: "Profanity, insults, or demeaning language toward the customer." },
  { id: "r-false", code: "PROH-LANG-03", label: "False legal claim", category: "prohibited-language", severity: "critical", description: "Misrepresenting legal status, court action, or credit-bureau consequences." },
  { id: "r-guarantee", code: "PROH-LANG-04", label: "Guarantee-of-outcome claim", category: "prohibited-language", severity: "medium", description: "Promising waivers, settlements, or approvals without authority." },
  { id: "r-dnd-win", code: "CONSENT-01", label: "Contact outside DND window", category: "consent", severity: "high", description: "Outbound attempt made during customer's declared quiet hours." },
  { id: "r-verify", code: "VERIFY-01", label: "Skipped identity verification", category: "verification", severity: "high", description: "Account details disclosed before verifying the caller's identity." },
  { id: "r-distress", code: "SENT-01", label: "Customer distress not addressed", category: "sentiment", severity: "medium", description: "Sentiment dropped sharply without agent empathy or de-escalation." },
];

export const RULES_BY_ID: Record<string, ComplianceRule> = Object.fromEntries(RULES.map((r) => [r.id, r]));

// Deterministic PRNG for reproducibility.
function rng(seed: string) {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return () => {
    h += 0x6d2b79f5;
    let t = h;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Synthetic prohibited-language snippets attached to select calls.
const PROHIBITED_SNIPPETS: Record<string, { rule: string; text: string }[]> = {
  threat: [
    { rule: "r-threat", text: "If you don't pay by tomorrow, we'll send police to your home address." },
    { rule: "r-threat", text: "You'll be arrested if this stays unpaid — I'm warning you." },
  ],
  abuse: [
    { rule: "r-abuse", text: "This is the third call — are you even listening to me? Stop being difficult." },
    { rule: "r-abuse", text: "You people never pay on time, honestly." },
  ],
  false: [
    { rule: "r-false", text: "A court notice has already been issued in your name — I'm just informing you." },
    { rule: "r-false", text: "Your CIBIL score is now zero. It cannot be recovered." },
  ],
  guarantee: [
    { rule: "r-guarantee", text: "I can guarantee a 100% waiver if you pay ₹5,000 in the next hour." },
  ],
};

function actorFrom(call: CallRecord): { kind: ActorKind; name: string } {
  if (call.handledBy.kind === "bot") return { kind: "bot", name: call.handledBy.bot ?? "Kaia v2.4" };
  if (call.handledBy.agent) return { kind: "human", name: call.handledBy.agent };
  return { kind: "bot", name: call.handledBy.bot ?? "Kaia v2.4" };
}

function pickTurn(call: CallRecord, rand: () => number): TranscriptTurn | null {
  const speakerTurns = call.transcript.filter((t) => t.speaker === "bot" || t.speaker === "agent");
  if (speakerTurns.length === 0) return null;
  return speakerTurns[Math.floor(rand() * speakerTurns.length)]!;
}

function evidenceFrom(call: CallRecord, offending: TranscriptTurn) {
  const idx = call.transcript.findIndex((t) => t.id === offending.id);
  return {
    snippet: offending.text,
    preceding: idx > 0 ? call.transcript[idx - 1] : undefined,
    offending,
    following: idx >= 0 && idx < call.transcript.length - 1 ? call.transcript[idx + 1] : undefined,
  };
}

function makeStatus(rand: () => number): ViolationStatus {
  const r = rand();
  if (r < 0.55) return "open";
  if (r < 0.75) return "in_review";
  if (r < 0.88) return "acknowledged";
  return "resolved";
}

const REVIEWERS = ["Meera Joshi", "Rohit Verma", "Sara Khan", "Compliance Ops"];

function build(): Violation[] {
  const out: Violation[] = [];
  let n = 0;

  for (const call of calls) {
    const rand = rng(`v-${call.id}`);

    // 1) Disclosure misses — one per missed template item.
    for (const d of call.disclosures) {
      if (d.read) continue;
      const ruleId =
        d.id === "recording" ? "r-rec" :
        d.id === "mini-miranda" ? "r-mm" :
        d.id === "dnd" ? "r-dnd-disc" :
        "r-disp";
      const rule = RULES_BY_ID[ruleId]!;
      const offending = pickTurn(call, rand);
      if (!offending) continue;
      // Only emit for substantive calls, not DND/NoAnswer/Voicemail.
      if (call.disposition === "No Answer" || call.disposition === "Voicemail" || call.disposition === "DND — Not Contacted") continue;
      const status = makeStatus(rand);
      out.push({
        id: `V-${(20000 + n++).toString()}`,
        callId: call.id,
        customerName: call.customerName,
        ruleId,
        severity: rule.severity,
        occurredAt: call.startedAt,
        atSec: offending.t,
        actor: actorFrom(call),
        evidence: {
          snippet: `Disclosure "${rule.label.replace("Missed ", "")}" was not read to the customer during the call.`,
          preceding: undefined,
          offending,
          following: undefined,
        },
        status,
        assignee: status !== "open" ? REVIEWERS[Math.floor(rand() * REVIEWERS.length)] : undefined,
        notes: status === "resolved"
          ? [{ at: call.startedAt, author: REVIEWERS[0]!, text: "Coached agent; disclosure script re-issued." }]
          : [],
      });
    }

    // 2) Prohibited language — for abuse/escalation-flagged calls.
    if (call.flags.includes("abuse-detected") || call.flags.includes("escalation")) {
      const bucket = call.flags.includes("abuse-detected") ? "abuse" : rand() < 0.4 ? "threat" : "false";
      const options = PROHIBITED_SNIPPETS[bucket]!;
      const snip = options[Math.floor(rand() * options.length)]!;
      const rule = RULES_BY_ID[snip.rule]!;
      const speakerTurns = call.transcript.filter((t) => t.speaker === "agent" || t.speaker === "bot");
      const anchor = speakerTurns[Math.min(2, speakerTurns.length - 1)] ?? call.transcript[0];
      if (!anchor) continue;
      const synthetic: TranscriptTurn = { id: `${anchor.id}-syn`, t: anchor.t + 4, speaker: anchor.speaker, text: snip.text };
      const status = makeStatus(rand);
      out.push({
        id: `V-${(20000 + n++).toString()}`,
        callId: call.id,
        customerName: call.customerName,
        ruleId: rule.id,
        severity: rule.severity,
        occurredAt: call.startedAt,
        atSec: synthetic.t,
        actor: actorFrom(call),
        evidence: evidenceFrom(call, synthetic),
        status,
        assignee: status !== "open" ? REVIEWERS[Math.floor(rand() * REVIEWERS.length)] : undefined,
        notes: [],
      });
    }

    // 3) Sentiment distress unaddressed.
    if (call.flags.includes("sentiment-drop") && rand() < 0.6) {
      const rule = RULES_BY_ID["r-distress"]!;
      const offending = pickTurn(call, rand);
      if (offending) {
        const status = makeStatus(rand);
        out.push({
          id: `V-${(20000 + n++).toString()}`,
          callId: call.id,
          customerName: call.customerName,
          ruleId: rule.id,
          severity: rule.severity,
          occurredAt: call.startedAt,
          atSec: offending.t,
          actor: actorFrom(call),
          evidence: evidenceFrom(call, offending),
          status,
          assignee: status !== "open" ? REVIEWERS[Math.floor(rand() * REVIEWERS.length)] : undefined,
          notes: [],
        });
      }
    }
  }

  return out.sort((a, b) => {
    const w = severityWeight(b.severity) - severityWeight(a.severity);
    if (w !== 0) return w;
    return new Date(b.occurredAt).getTime() - new Date(a.occurredAt).getTime();
  });
}

export const violations: Violation[] = build();

export function severityWeight(s: Severity): number {
  return s === "critical" ? 4 : s === "high" ? 3 : s === "medium" ? 2 : 1;
}

export function severityColor(s: Severity): string {
  switch (s) {
    case "critical": return "var(--danger)";
    case "high": return "var(--warning)";
    case "medium": return "var(--sentiment-neutral)";
    case "low": return "var(--text-muted)";
  }
}

export function severityBg(s: Severity): string {
  switch (s) {
    case "critical": return "var(--danger-bg)";
    case "high": return "var(--warning-bg)";
    case "medium": return "var(--warning-bg)";
    case "low": return "var(--surface-sunken)";
  }
}

export function statusLabel(s: ViolationStatus): string {
  return s === "open" ? "Open" : s === "in_review" ? "In review" : s === "acknowledged" ? "Acknowledged" : "Resolved";
}

// ---------- filters ----------
export type CompDateRange = "today" | "7d" | "30d" | "all";

export interface ComplianceFilterState {
  q: string;
  dateRange: CompDateRange;
  severities: Set<Severity>;
  ruleId: "all" | string;
  actor: "all" | ActorKind;
  agent: "all" | string;
  status: "all" | ViolationStatus;
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
    f.dateRange === "today" ? now - 86400_000 :
    f.dateRange === "7d" ? now - 7 * 86400_000 :
    f.dateRange === "30d" ? now - 30 * 86400_000 : 0;
  const q = f.q.trim().toLowerCase();
  return all.filter((v) => {
    if (cutoff && new Date(v.occurredAt).getTime() < cutoff) return false;
    if (f.severities.size > 0 && !f.severities.has(v.severity)) return false;
    if (f.ruleId !== "all" && v.ruleId !== f.ruleId) return false;
    if (f.actor !== "all" && v.actor.kind !== f.actor) return false;
    if (f.agent !== "all" && v.actor.name !== f.agent) return false;
    if (f.status !== "all" && v.status !== f.status) return false;
    if (q) {
      const hay = `${v.id} ${v.callId} ${v.customerName} ${v.actor.name} ${v.evidence.snippet} ${v.evidence.offending.text}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

export function trendByDay(all: Violation[], days = 30): Array<{ day: string; critical: number; high: number; medium: number; low: number; total: number }> {
  const buckets: Record<string, { critical: number; high: number; medium: number; low: number }> = {};
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

export function groupByRule(all: Violation[]): Array<{ rule: ComplianceRule; count: number; open: number }> {
  const map = new Map<string, { count: number; open: number }>();
  for (const v of all) {
    const cur = map.get(v.ruleId) ?? { count: 0, open: 0 };
    cur.count++;
    if (v.status === "open" || v.status === "in_review") cur.open++;
    map.set(v.ruleId, cur);
  }
  return Array.from(map.entries())
    .map(([id, m]) => ({ rule: RULES_BY_ID[id]!, ...m }))
    .filter((x) => x.rule)
    .sort((a, b) => b.open - a.open || b.count - a.count);
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

export function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function formatAt(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
