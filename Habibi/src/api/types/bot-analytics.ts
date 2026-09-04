/**
 * Domain / wire types for the bot-analytics surface.
 *
 * Lived in a `data/*-seed.ts` mock factory. Moved here so live `api/`
 * modules do not import their contract from fixtures (WP-048).
 */

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
