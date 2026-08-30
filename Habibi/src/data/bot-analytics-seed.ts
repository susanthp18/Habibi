// Bot Analytics — synthetic conversation intelligence data.

/** Voice production budget: user-stop → first audio (Pipecat 2026 practice). */
export const VOICE_TTFA_SLO_MS = 800;

export type ChannelKey = "all" | "voice" | "whatsapp" | "sms";
export type RangeKey = "7d" | "30d" | "90d";

export interface IntentAgg {
  id: string;
  label: string;
  sessions: number;
  contained: number; // resolved by bot without escalation
  escalated: number;
  abandoned: number;
  avgTurns: number;
  avgLatencyMs: number;
  sentiment: { positive: number; neutral: number; negative: number };
}

export interface DailyPoint {
  date: string; // YYYY-MM-DD
  sessions: number;
  contained: number;
  escalated: number;
  abandoned: number;
  avgTurns: number;
  latencyP50: number;
  latencyP90: number;
  latencyP99: number;
  sentiment: number; // -1..1
  /** Sessions where an upsell was presented (voice + WhatsApp). */
  upsellPresented?: number;
  /** Sessions that captured a promise-to-pay. */
  ptpCaptured?: number;
}

export interface EscalationReason {
  id: string;
  label: string;
  count: number;
  trendDelta: number; // % change vs prior period
}

export interface UnansweredQuestion {
  id: string;
  text: string;
  hits: number;
  lastSeen: string;
  topIntent: string;
  hasKbDoc: boolean;
  suggestedFix: "kb" | "prompt" | "both";
}

export interface TurnsBucket {
  label: string;
  min: number;
  max: number;
  count: number;
}

// deterministic rng
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

export const INTENTS: Array<{ id: string; label: string; base: number; containRate: number }> = [
  { id: "balance", label: "Balance / Dues query", base: 480, containRate: 0.92 },
  { id: "emi", label: "EMI schedule", base: 360, containRate: 0.88 },
  { id: "payment-confirm", label: "Payment confirmation", base: 320, containRate: 0.94 },
  { id: "statement", label: "Statement request", base: 260, containRate: 0.95 },
  { id: "late-fee", label: "Late fee / waiver", base: 210, containRate: 0.62 },
  { id: "dispute", label: "Dispute raise", base: 180, containRate: 0.48 },
  { id: "callback", label: "Callback / reschedule", base: 170, containRate: 0.9 },
  { id: "topup", label: "Top-up / upsell interest", base: 140, containRate: 0.55 },
  { id: "dnd", label: "DND / opt-out", base: 110, containRate: 0.98 },
  { id: "language", label: "Language switch", base: 90, containRate: 0.85 },
  { id: "escalate-human", label: "Ask for human", base: 130, containRate: 0.05 },
  { id: "other", label: "Other / unrecognised", base: 100, containRate: 0.3 },
];

function todayIso(offsetDays: number): string {
  const d = new Date();
  d.setDate(d.getDate() - offsetDays);
  return d.toISOString().slice(0, 10);
}

export const dailySeries: DailyPoint[] = Array.from({ length: 90 }, (_, i) => {
  const day = 89 - i;
  const r = rng("day-" + day);
  const weekend = [0, 6].includes(new Date(todayIso(day)).getDay());
  const base = weekend ? 950 : 1400;
  const sessions = Math.round(base + (r() - 0.5) * 250);
  const contained = Math.round(sessions * (0.78 + (r() - 0.5) * 0.08));
  const escalated = Math.round(sessions * (0.14 + (r() - 0.5) * 0.04));
  const abandoned = Math.max(0, sessions - contained - escalated);
  return {
    date: todayIso(day),
    sessions,
    contained,
    escalated,
    abandoned,
    avgTurns: 4.2 + (r() - 0.5) * 1.5,
    latencyP50: 620 + (r() - 0.5) * 120,
    latencyP90: 1350 + (r() - 0.5) * 280,
    latencyP99: 2400 + (r() - 0.5) * 500,
    sentiment: 0.25 + (r() - 0.5) * 0.35,
    upsellPresented: Math.round(sessions * (0.08 + (r() - 0.5) * 0.03)),
    ptpCaptured: Math.round(sessions * (0.18 + (r() - 0.5) * 0.05)),
  };
});

export const intentAggs: IntentAgg[] = INTENTS.map((intent, i) => {
  const r = rng("intent-" + intent.id);
  const sessions = intent.base * 3 + Math.round((r() - 0.5) * 60);
  const contained = Math.round(sessions * intent.containRate);
  const escalated = Math.round(sessions * (1 - intent.containRate) * 0.75);
  const abandoned = Math.max(0, sessions - contained - escalated);
  const negBias = 1 - intent.containRate;
  return {
    id: intent.id,
    label: intent.label,
    sessions,
    contained,
    escalated,
    abandoned,
    avgTurns: 3 + i * 0.3 + (r() - 0.5),
    avgLatencyMs: 700 + i * 40 + (r() - 0.5) * 120,
    sentiment: {
      positive: Math.round(sessions * (0.55 - negBias * 0.35)),
      neutral: Math.round(sessions * (0.3 + negBias * 0.1)),
      negative: Math.round(sessions * (0.15 + negBias * 0.4)),
    },
  };
}).sort((a, b) => b.sessions - a.sessions);

export const escalationReasons: EscalationReason[] = [
  { id: "rag-miss", label: "RAG miss / no confident answer", count: 412, trendDelta: 6 },
  { id: "user-asked", label: "User asked for human", count: 338, trendDelta: -2 },
  { id: "sentiment-drop", label: "Sentiment drop (negative)", count: 221, trendDelta: 12 },
  { id: "verify-fail", label: "Verification failed", count: 164, trendDelta: -4 },
  { id: "repeat-loop", label: "Repeat / loop detected", count: 118, trendDelta: 3 },
  { id: "sensitive", label: "Sensitive topic (dispute/legal)", count: 92, trendDelta: 1 },
  { id: "silence", label: "Long silence / no input", count: 74, trendDelta: -8 },
];

export const unansweredQuestions: UnansweredQuestion[] = [
  {
    id: "u1",
    text: "Can I pay in three instalments after due date without CIBIL hit?",
    hits: 84,
    lastSeen: todayIso(0),
    topIntent: "late-fee",
    hasKbDoc: false,
    suggestedFix: "kb",
  },
  {
    id: "u2",
    text: "What's the interest rate if I only pay minimum?",
    hits: 71,
    lastSeen: todayIso(0),
    topIntent: "emi",
    hasKbDoc: true,
    suggestedFix: "prompt",
  },
  {
    id: "u3",
    text: "How do I get a NOC after full closure?",
    hits: 63,
    lastSeen: todayIso(1),
    topIntent: "statement",
    hasKbDoc: false,
    suggestedFix: "kb",
  },
  {
    id: "u4",
    text: "Can waiver be given if job loss proof provided?",
    hits: 58,
    lastSeen: todayIso(0),
    topIntent: "late-fee",
    hasKbDoc: false,
    suggestedFix: "both",
  },
  {
    id: "u5",
    text: "Explain foreclosure charges for personal loan",
    hits: 52,
    lastSeen: todayIso(2),
    topIntent: "emi",
    hasKbDoc: true,
    suggestedFix: "prompt",
  },
  {
    id: "u6",
    text: "How to change EMI debit date?",
    hits: 47,
    lastSeen: todayIso(1),
    topIntent: "emi",
    hasKbDoc: false,
    suggestedFix: "kb",
  },
  {
    id: "u7",
    text: "Is there a moratorium option for medical emergency?",
    hits: 41,
    lastSeen: todayIso(3),
    topIntent: "late-fee",
    hasKbDoc: false,
    suggestedFix: "kb",
  },
  {
    id: "u8",
    text: "Why was late fee ₹599 vs standard ₹450?",
    hits: 39,
    lastSeen: todayIso(0),
    topIntent: "dispute",
    hasKbDoc: true,
    suggestedFix: "prompt",
  },
  {
    id: "u9",
    text: "Can I convert overdue balance to EMI?",
    hits: 34,
    lastSeen: todayIso(2),
    topIntent: "topup",
    hasKbDoc: false,
    suggestedFix: "both",
  },
  {
    id: "u10",
    text: "What documents needed for top-up on existing loan?",
    hits: 31,
    lastSeen: todayIso(1),
    topIntent: "topup",
    hasKbDoc: false,
    suggestedFix: "kb",
  },
  {
    id: "u11",
    text: "Language switch to Tamil not working mid-call",
    hits: 27,
    lastSeen: todayIso(0),
    topIntent: "language",
    hasKbDoc: false,
    suggestedFix: "prompt",
  },
  {
    id: "u12",
    text: "Bot repeats verification after I already verified",
    hits: 24,
    lastSeen: todayIso(1),
    topIntent: "other",
    hasKbDoc: false,
    suggestedFix: "prompt",
  },
];

export const turnsHistogram: TurnsBucket[] = [
  { label: "1–2", min: 1, max: 2, count: 1820 },
  { label: "3–4", min: 3, max: 4, count: 4210 },
  { label: "5–7", min: 5, max: 7, count: 2380 },
  { label: "8–12", min: 8, max: 12, count: 940 },
  { label: "13+", min: 13, max: 99, count: 260 },
];

// ----- helpers -----

export function filterByRange(range: RangeKey, series: DailyPoint[] = dailySeries): DailyPoint[] {
  const days = range === "7d" ? 7 : range === "30d" ? 30 : 90;
  return series.slice(-days);
}

export interface Kpis {
  sessions: number;
  containment: number; // %
  deflection: number; // % (contained / total received queries) — same as containment for PoC
  escalation: number; // %
  abandonment: number; // %
  avgTurns: number;
  latencyP50: number;
  latencyP90: number;
  avgSentiment: number;
  csatProxy: number; // derived
  upsellRate: number; // % of sessions with upsell presented
  ptpRate: number; // % of sessions with PTP captured
  containmentSpark: number[];
  latencySpark: number[];
  turnsSpark: number[];
  sentimentSpark: number[];
  escalationSpark: number[];
  sessionsSpark: number[];
  upsellSpark: number[];
  ptpSpark: number[];
}

export function computeKpis(points: DailyPoint[]): Kpis {
  const sessions = points.reduce((a, p) => a + p.sessions, 0);
  const contained = points.reduce((a, p) => a + p.contained, 0);
  const escalated = points.reduce((a, p) => a + p.escalated, 0);
  const abandoned = points.reduce((a, p) => a + p.abandoned, 0);
  const upsellPresented = points.reduce((a, p) => a + (p.upsellPresented ?? 0), 0);
  const ptpCaptured = points.reduce((a, p) => a + (p.ptpCaptured ?? 0), 0);
  const avgTurns = points.reduce((a, p) => a + p.avgTurns, 0) / (points.length || 1);
  const latencyP50 = points.reduce((a, p) => a + p.latencyP50, 0) / (points.length || 1);
  const latencyP90 = points.reduce((a, p) => a + p.latencyP90, 0) / (points.length || 1);
  const avgSentiment = points.reduce((a, p) => a + p.sentiment, 0) / (points.length || 1);
  return {
    sessions,
    containment: (contained / (sessions || 1)) * 100,
    deflection: (contained / (sessions || 1)) * 100,
    escalation: (escalated / (sessions || 1)) * 100,
    abandonment: (abandoned / (sessions || 1)) * 100,
    avgTurns,
    latencyP50,
    latencyP90,
    avgSentiment,
    csatProxy: Math.max(0, Math.min(100, 60 + avgSentiment * 40)),
    upsellRate: (upsellPresented / (sessions || 1)) * 100,
    ptpRate: (ptpCaptured / (sessions || 1)) * 100,
    containmentSpark: points.map((p) => (p.contained / (p.sessions || 1)) * 100),
    latencySpark: points.map((p) => p.latencyP90),
    turnsSpark: points.map((p) => p.avgTurns),
    sentimentSpark: points.map((p) => p.sentiment),
    escalationSpark: points.map((p) => (p.escalated / (p.sessions || 1)) * 100),
    sessionsSpark: points.map((p) => p.sessions),
    upsellSpark: points.map((p) => ((p.upsellPresented ?? 0) / (p.sessions || 1)) * 100),
    ptpSpark: points.map((p) => ((p.ptpCaptured ?? 0) / (p.sessions || 1)) * 100),
  };
}

export const funnelStages: Array<{ id: string; label: string; count: number }> = [
  { id: "landed", label: "Session landed", count: 12480 },
  { id: "verified", label: "Verified identity", count: 11210 },
  { id: "intent", label: "Intent captured", count: 10430 },
  { id: "answered", label: "Answer delivered", count: 9280 },
  { id: "confirmed", label: "Confirmed resolution", count: 8340 },
];
