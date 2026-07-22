// QA Scorecards & Coaching — synthetic rubric + graded interactions.
import { calls as auditCalls, type CallRecord } from "./audit-seed";

export type ScoreBand = "green" | "amber" | "red";
export type ScorecardStatus = "unscored" | "ai_draft" | "final";
export type CoachingStatus = "assigned" | "in_progress" | "done";

export interface RubricCriterion {
  id: string;
  label: string;
  description: string;
  weight: number; // relative within section, %
  critical?: boolean;
}

export interface RubricSection {
  id: string;
  label: string;
  weight: number; // % of total, sections should sum to 100
  criteria: RubricCriterion[];
}

export interface Rubric {
  id: string;
  name: string;
  version: string;
  sections: RubricSection[];
}

export interface ScorecardEntry {
  criterionId: string;
  aiSuggested: number; // 0..5
  score: number; // 0..5 (final)
  note?: string;
  accepted?: boolean;
}

export interface Scorecard {
  id: string;
  callId: string;
  customerName: string;
  disposition: string;
  handledBy: { kind: "bot" | "human" | "handoff"; label: string };
  agentId: string; // reviewed subject (bot key or agent name)
  reviewer?: string;
  status: ScorecardStatus;
  entries: ScorecardEntry[];
  scoredAt?: string;
  createdAt: string;
}

export interface CoachingAction {
  id: string;
  agentId: string;
  title: string;
  category: string;
  scorecardId?: string;
  callId?: string;
  dueAt: string;
  status: CoachingStatus;
  notes: Array<{ at: string; author: string; text: string }>;
  createdAt: string;
}

export interface CalibrationReviewerScore {
  reviewer: string;
  entries: ScorecardEntry[];
}

export interface CalibrationSession {
  id: string;
  name: string;
  callId: string;
  customerName: string;
  target: ScorecardEntry[]; // target scores
  reviewers: CalibrationReviewerScore[];
  status: "active" | "closed";
  createdAt: string;
}

// ---------- default rubric ----------

export const defaultRubric: Rubric = {
  id: "rubric-v1",
  name: "Collections Interaction Rubric",
  version: "v1.0",
  sections: [
    {
      id: "empathy",
      label: "Empathy & Tone",
      weight: 20,
      criteria: [
        { id: "emp-acknowledge", label: "Acknowledged customer situation", description: "Reflected feeling before pushing agenda.", weight: 50 },
        { id: "emp-tone", label: "Calm, respectful tone maintained", description: "No sarcasm, no raised voice, no interruption.", weight: 50 },
      ],
    },
    {
      id: "resolution",
      label: "Resolution & Accuracy",
      weight: 30,
      criteria: [
        { id: "res-identify", label: "Correctly identified customer need", description: "Root need captured within 2 turns.", weight: 30 },
        { id: "res-answer", label: "Accurate answer / next-step", description: "Dues, EMI, dispute path stated correctly.", weight: 40 },
        { id: "res-close", label: "Confirmed resolution before closing", description: "Summarised action + expectation.", weight: 30 },
      ],
    },
    {
      id: "compliance",
      label: "Compliance",
      weight: 25,
      criteria: [
        { id: "cmp-recording", label: "Recording notice given", description: "Within first 20 seconds.", weight: 25, critical: true },
        { id: "cmp-miranda", label: "Mini-Miranda debt disclosure", description: "Read verbatim before dues discussion.", weight: 30, critical: true },
        { id: "cmp-dnd", label: "DND / opt-out honoured", description: "No contact outside allowed window; opt-out respected.", weight: 25, critical: true },
        { id: "cmp-language", label: "No prohibited language", description: "No threats, no third-party disclosure.", weight: 20, critical: true },
      ],
    },
    {
      id: "script",
      label: "Script Adherence",
      weight: 15,
      criteria: [
        { id: "scr-verify", label: "Identity verification followed", description: "DOB / OTP as per SOP.", weight: 50 },
        { id: "scr-closing", label: "Approved closing script used", description: "Includes ticket ID + next step.", weight: 50 },
      ],
    },
    {
      id: "upsell",
      label: "Upsell & Value",
      weight: 10,
      criteria: [
        { id: "ups-eligibility", label: "Checked eligibility before pitch", description: "Only pitched if flags green.", weight: 50 },
        { id: "ups-pitch", label: "Contextual, non-pushy pitch", description: "Tied to customer's stated need.", weight: 50 },
      ],
    },
  ],
};

// ---------- helpers ----------

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

export function allCriteria(rubric: Rubric): RubricCriterion[] {
  return rubric.sections.flatMap((s) => s.criteria);
}

export function sectionTotal(section: RubricSection, entries: ScorecardEntry[]): number {
  const weightSum = section.criteria.reduce((a, c) => a + c.weight, 0) || 1;
  let acc = 0;
  for (const c of section.criteria) {
    const e = entries.find((x) => x.criterionId === c.id);
    const score = e?.score ?? 0;
    acc += (score / 5) * (c.weight / weightSum);
  }
  return acc * 100; // 0..100 within section
}

export function computeTotal(sc: Scorecard, rubric: Rubric): number {
  // Critical-fail: any critical criterion with score 0 caps total at 40.
  const hasCriticalZero = rubric.sections.some((s) =>
    s.criteria.some(
      (c) => c.critical && (sc.entries.find((e) => e.criterionId === c.id)?.score ?? 0) === 0,
    ),
  );
  const weightSum = rubric.sections.reduce((a, s) => a + s.weight, 0) || 1;
  const total = rubric.sections.reduce(
    (acc, s) => acc + (sectionTotal(s, sc.entries) * s.weight) / weightSum,
    0,
  );
  return hasCriticalZero ? Math.min(total, 40) : total;
}

export function bandFor(total: number): ScoreBand {
  if (total >= 85) return "green";
  if (total >= 70) return "amber";
  return "red";
}

export function bandColor(band: ScoreBand): { text: string; bg: string; border: string } {
  if (band === "green") return { text: "text-emerald-700", bg: "bg-emerald-50", border: "border-emerald-200" };
  if (band === "amber") return { text: "text-amber-700", bg: "bg-amber-50", border: "border-amber-200" };
  return { text: "text-red-700", bg: "bg-red-50", border: "border-red-200" };
}

// ---------- seed generation ----------

const AGENTS = ["Aarav K.", "Priya Nair", "Arjun Mehta", "Sara Khan", "Rohit Verma", "Meera Joshi"];
const BOTS = ["Kaia v2.4"];

function makeEntries(
  rand: () => number,
  rubric: Rubric,
  bias: number, // 0..1, higher = better
  isFinal: boolean,
): ScorecardEntry[] {
  return allCriteria(rubric).map((c) => {
    // AI suggestion around 3 + bias*2; jitter ±1
    const rawAi = 3 + bias * 2 + (rand() - 0.5) * 1.6;
    const ai = Math.max(0, Math.min(5, Math.round(rawAi)));
    // Human either equals AI (accepted) or nudges ±1
    const nudge = isFinal ? Math.round((rand() - 0.5) * 1.4) : 0;
    const score = isFinal ? Math.max(0, Math.min(5, ai + nudge)) : ai;
    return {
      criterionId: c.id,
      aiSuggested: ai,
      score,
      accepted: isFinal ? nudge === 0 : undefined,
      note: isFinal && rand() > 0.75 ? "Coach reviewed — see comments." : undefined,
    };
  });
}

function seedFrom(calls: CallRecord[]): Scorecard[] {
  const list: Scorecard[] = [];
  for (let i = 0; i < Math.min(28, calls.length); i++) {
    const call = calls[i]!;
    const rand = rng(call.id + "-qa");
    const kind = call.handledBy.kind;
    const label = kind === "bot" ? call.handledBy.bot ?? BOTS[0]! : call.handledBy.agent ?? AGENTS[i % AGENTS.length]!;
    const agentId = kind === "bot" ? BOTS[0]! : AGENTS[i % AGENTS.length]!;
    const status: ScorecardStatus = i < 6 ? "unscored" : i < 16 ? "ai_draft" : "final";
    // bias derives from avgSentiment + flags
    const flagPenalty = call.flags.length * 0.08;
    const bias = Math.max(0.1, Math.min(0.95, 0.55 + call.avgSentiment * 0.35 - flagPenalty));
    const entries = status === "unscored" ? makeEntries(rand, defaultRubric, bias, false).map((e) => ({ ...e, score: 0 })) : makeEntries(rand, defaultRubric, bias, status === "final");
    list.push({
      id: `qa-${call.id}`,
      callId: call.id,
      customerName: call.customerName,
      disposition: call.disposition,
      handledBy: { kind, label },
      agentId,
      reviewer: status === "final" ? "Meera Joshi" : status === "ai_draft" ? "Kaia QA" : undefined,
      status,
      entries,
      scoredAt: status === "final" ? new Date(Date.parse(call.startedAt) + 3600_000).toISOString() : undefined,
      createdAt: call.startedAt,
    });
  }
  return list;
}

export const scorecards: Scorecard[] = seedFrom(auditCalls);

// ---------- agent stats ----------

export interface AgentQaStat {
  agentId: string;
  isBot: boolean;
  scored: number;
  avg: number;
  delta7d: number;
  band: ScoreBand;
  weakestSection: string;
  openCoaching: number;
  trend: number[]; // last 7 avg points
  sectionScores: Array<{ section: string; value: number }>;
}

export function agentStats(all: Scorecard[], rubric: Rubric, coaching: CoachingAction[]): AgentQaStat[] {
  const byAgent = new Map<string, Scorecard[]>();
  for (const s of all) {
    if (s.status === "unscored") continue;
    const arr = byAgent.get(s.agentId) ?? [];
    arr.push(s);
    byAgent.set(s.agentId, arr);
  }
  const out: AgentQaStat[] = [];
  for (const [agentId, cards] of byAgent.entries()) {
    const totals = cards.map((c) => computeTotal(c, rubric));
    const avg = totals.reduce((a, b) => a + b, 0) / (totals.length || 1);
    const half = Math.max(1, Math.floor(cards.length / 2));
    const recent = totals.slice(0, half).reduce((a, b) => a + b, 0) / half;
    const prior = totals.slice(half).reduce((a, b) => a + b, 0) / Math.max(1, totals.length - half);
    const sectionScores = rubric.sections.map((s) => {
      const vals = cards.map((c) => sectionTotal(s, c.entries));
      return { section: s.label, value: vals.reduce((a, b) => a + b, 0) / (vals.length || 1) };
    });
    const weakest = sectionScores.slice().sort((a, b) => a.value - b.value)[0]?.section ?? "—";
    const rand = rng(agentId + "-trend");
    const trend = Array.from({ length: 7 }, (_, i) => Math.max(40, Math.min(100, avg + (rand() - 0.5) * 10 - i)));
    out.push({
      agentId,
      isBot: agentId === BOTS[0],
      scored: cards.length,
      avg,
      delta7d: recent - prior,
      band: bandFor(avg),
      weakestSection: weakest,
      openCoaching: coaching.filter((c) => c.agentId === agentId && c.status !== "done").length,
      trend: trend.reverse(),
      sectionScores,
    });
  }
  return out.sort((a, b) => b.avg - a.avg);
}

// ---------- coaching seed ----------

export const initialCoaching: CoachingAction[] = [
  {
    id: "coach-1",
    agentId: "Aarav K.",
    title: "Read mini-Miranda before discussing dues",
    category: "Compliance",
    callId: auditCalls[3]?.id,
    scorecardId: `qa-${auditCalls[3]?.id ?? ""}`,
    dueAt: new Date(Date.now() + 2 * 86400_000).toISOString(),
    status: "assigned",
    notes: [{ at: new Date().toISOString(), author: "Meera Joshi", text: "Missed on 3 of last 10 calls." }],
    createdAt: new Date(Date.now() - 86400_000).toISOString(),
  },
  {
    id: "coach-2",
    agentId: "Priya Nair",
    title: "Slow down on EMI recalculation explanation",
    category: "Resolution",
    callId: auditCalls[7]?.id,
    dueAt: new Date(Date.now() + 5 * 86400_000).toISOString(),
    status: "in_progress",
    notes: [{ at: new Date().toISOString(), author: "Meera Joshi", text: "Customer confused twice — walk through worked example." }],
    createdAt: new Date(Date.now() - 3 * 86400_000).toISOString(),
  },
  {
    id: "coach-3",
    agentId: "Rohit Verma",
    title: "Confirm PTP date + amount before wrap-up",
    category: "Script Adherence",
    dueAt: new Date(Date.now() + 3 * 86400_000).toISOString(),
    status: "assigned",
    notes: [],
    createdAt: new Date(Date.now() - 2 * 86400_000).toISOString(),
  },
  {
    id: "coach-4",
    agentId: "Sara Khan",
    title: "Acknowledge frustration before pitching top-up",
    category: "Empathy",
    dueAt: new Date(Date.now() + 7 * 86400_000).toISOString(),
    status: "in_progress",
    notes: [{ at: new Date().toISOString(), author: "Meera Joshi", text: "Role-play scheduled Thursday." }],
    createdAt: new Date(Date.now() - 4 * 86400_000).toISOString(),
  },
  {
    id: "coach-5",
    agentId: "Arjun Mehta",
    title: "Upsell only after resolving primary query",
    category: "Upsell",
    dueAt: new Date(Date.now() - 86400_000).toISOString(),
    status: "done",
    notes: [{ at: new Date().toISOString(), author: "Meera Joshi", text: "Signed off — improvement visible on last 8 calls." }],
    createdAt: new Date(Date.now() - 10 * 86400_000).toISOString(),
  },
  {
    id: "coach-6",
    agentId: "Kaia v2.4",
    title: "Prompt tune: reduce over-apology in dispute flow",
    category: "Empathy",
    dueAt: new Date(Date.now() + 4 * 86400_000).toISOString(),
    status: "assigned",
    notes: [{ at: new Date().toISOString(), author: "Bot Ops", text: "Route to Prompt Studio owner." }],
    createdAt: new Date().toISOString(),
  },
];

// ---------- calibration seed ----------

function calibrationEntries(rubric: Rubric, base: number, jitter: number, seed: string): ScorecardEntry[] {
  const rand = rng(seed);
  return allCriteria(rubric).map((c) => {
    const s = Math.max(0, Math.min(5, Math.round(base + (rand() - 0.5) * jitter)));
    return { criterionId: c.id, aiSuggested: s, score: s };
  });
}

export const initialCalibrations: CalibrationSession[] = [
  {
    id: "cal-1",
    name: "Weekly calibration — Dispute flow",
    callId: auditCalls[5]?.id ?? "",
    customerName: auditCalls[5]?.customerName ?? "—",
    target: calibrationEntries(defaultRubric, 4, 0.6, "cal1-target"),
    reviewers: [
      { reviewer: "Meera Joshi", entries: calibrationEntries(defaultRubric, 4, 1.2, "cal1-r1") },
      { reviewer: "Aarav K.", entries: calibrationEntries(defaultRubric, 3.4, 1.6, "cal1-r2") },
      { reviewer: "Priya Nair", entries: calibrationEntries(defaultRubric, 4.2, 1.0, "cal1-r3") },
    ],
    status: "active",
    createdAt: new Date(Date.now() - 86400_000).toISOString(),
  },
  {
    id: "cal-2",
    name: "Bot-vs-Human upsell handoff",
    callId: auditCalls[9]?.id ?? "",
    customerName: auditCalls[9]?.customerName ?? "—",
    target: calibrationEntries(defaultRubric, 3.6, 0.8, "cal2-target"),
    reviewers: [
      { reviewer: "Meera Joshi", entries: calibrationEntries(defaultRubric, 3.6, 1.4, "cal2-r1") },
      { reviewer: "Bot Ops", entries: calibrationEntries(defaultRubric, 4.1, 1.6, "cal2-r2") },
    ],
    status: "active",
    createdAt: new Date(Date.now() - 3 * 86400_000).toISOString(),
  },
];

export function findCall(callId: string): CallRecord | undefined {
  return auditCalls.find((c) => c.id === callId);
}

export const AGENT_POOL = [...AGENTS, ...BOTS];
