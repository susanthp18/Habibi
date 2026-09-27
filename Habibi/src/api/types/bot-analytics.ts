/**
 * Domain / wire types for the bot-analytics surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
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
  /** Bot-handled sessions, and those never handed to a human. */
  botSessions?: number;
  botContained?: number;
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
  /** % of bot sessions never handed to a human; null with no bot sessions. */
  containment: number | null;
  /** % of inbound bot sessions resolved, never handed off, and not followed by
   *  a repeat contact within repeatContactDays; null when none is old enough. */
  deflection: number | null;
  deflectionEligible: number;
  repeatContactDays: number;
  escalation: number; // %
  abandonment: number; // %
  avgTurns: number;
  /** True percentiles over the calls in range (ms); null without latency data. */
  latencyP50: number | null;
  latencyP90: number | null;
  avgSentiment: number;
  /** Mean per call of last minus first customer sentiment (-2..2); null without signals. */
  sentimentLift: number | null;
  sentimentLiftCalls: number;
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
