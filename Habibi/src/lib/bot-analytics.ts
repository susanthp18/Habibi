import type {
  ChannelKey,
  RangeKey,
  IntentAgg,
  DailyPoint,
  EscalationReason,
  UnansweredQuestion,
  TurnsBucket,
  Kpis,
} from "@/api/types/bot-analytics";

export const VOICE_TTFA_SLO_MS = 800;

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
