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
import type { BotAnalyticsFilters, BotAnalyticsSummary } from "@/api/bot-analytics";
import { row } from "@/lib/dashboard-export";

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

/**
 * Screen KPIs. Counts and rates come from the daily rows; containment,
 * deflection, latency percentiles and sentiment lift come from the server's
 * `summary`, computed over calls (a percentile cannot be averaged across days).
 */
export function computeKpis(points: DailyPoint[], summary?: BotAnalyticsSummary | null): Kpis {
  const sessions = points.reduce((a, p) => a + p.sessions, 0);
  const escalated = points.reduce((a, p) => a + p.escalated, 0);
  const abandoned = points.reduce((a, p) => a + p.abandoned, 0);
  const upsellPresented = points.reduce((a, p) => a + (p.upsellPresented ?? 0), 0);
  const ptpCaptured = points.reduce((a, p) => a + (p.ptpCaptured ?? 0), 0);
  const avgTurns = points.reduce((a, p) => a + p.avgTurns, 0) / (points.length || 1);
  const avgSentiment = points.reduce((a, p) => a + p.sentiment, 0) / (points.length || 1);
  return {
    sessions,
    containment: summary?.containment ?? null,
    deflection: summary?.deflection ?? null,
    deflectionEligible: summary?.deflectionEligible ?? 0,
    repeatContactDays: summary?.repeatContactDays ?? 7,
    escalation: (escalated / (sessions || 1)) * 100,
    abandonment: (abandoned / (sessions || 1)) * 100,
    avgTurns,
    latencyP50: summary?.latencyP50 ?? null,
    latencyP90: summary?.latencyP90 ?? null,
    avgSentiment,
    sentimentLift: summary?.sentimentLift ?? null,
    sentimentLiftCalls: summary?.sentimentLiftCalls ?? 0,
    upsellRate: (upsellPresented / (sessions || 1)) * 100,
    ptpRate: (ptpCaptured / (sessions || 1)) * 100,
    containmentSpark: points.map((p) =>
      p.botSessions ? ((p.botContained ?? 0) / p.botSessions) * 100 : 0,
    ),
    latencySpark: points.map((p) => p.latencyP90),
    turnsSpark: points.map((p) => p.avgTurns),
    sentimentSpark: points.map((p) => p.sentiment),
    escalationSpark: points.map((p) => (p.escalated / (p.sessions || 1)) * 100),
    sessionsSpark: points.map((p) => p.sessions),
    upsellSpark: points.map((p) => ((p.upsellPresented ?? 0) / (p.sessions || 1)) * 100),
    ptpSpark: points.map((p) => ((p.ptpCaptured ?? 0) / (p.sessions || 1)) * 100),
  };
}

/** The KPIs on screen and the daily series behind them, filters in the first row. */
export function botAnalyticsCsv(
  filters: BotAnalyticsFilters & { agentName?: string },
  kpis: Kpis,
  points: DailyPoint[],
): string {
  const kpiRows: Array<[string, number | null]> = [
    ["sessions", kpis.sessions],
    ["containment_pct", kpis.containment],
    ["deflection_pct", kpis.deflection],
    ["deflection_eligible_sessions", kpis.deflectionEligible],
    ["escalation_pct", kpis.escalation],
    ["abandonment_pct", kpis.abandonment],
    ["upsell_presented_pct", kpis.upsellRate],
    ["ptp_rate_pct", kpis.ptpRate],
    ["avg_turns", kpis.avgTurns],
    ["latency_p50_ms", kpis.latencyP50],
    ["latency_p90_ms", kpis.latencyP90],
    ["sentiment_lift", kpis.sentimentLift],
    ["sentiment_lift_calls", kpis.sentimentLiftCalls],
  ];
  const round = (v: number | null) => (v == null ? "" : Math.round(v * 1000) / 1000);
  return [
    row([
      "filters",
      `range=${filters.range}`,
      `channel=${filters.channel}`,
      `agent=${filters.agentName ?? filters.botId ?? "all"}`,
      `version=${filters.version ?? "all"}`,
    ]),
    "",
    row(["metric", "value"]),
    ...kpiRows.map(([k, v]) => row([k, round(v)])),
    "",
    row([
      "date",
      "sessions",
      "bot_sessions",
      "bot_contained",
      "resolved_by_bot",
      "escalated",
      "abandoned",
      "avg_turns",
      "latency_p50_ms",
      "latency_p90_ms",
      "latency_p99_ms",
      "sentiment",
      "upsell_presented",
      "ptp_captured",
    ]),
    ...points.map((p) =>
      row([
        p.date,
        p.sessions,
        p.botSessions ?? "",
        p.botContained ?? "",
        p.contained,
        p.escalated,
        p.abandoned,
        p.avgTurns,
        p.latencyP50,
        p.latencyP90,
        p.latencyP99,
        p.sentiment,
        p.upsellPresented ?? "",
        p.ptpCaptured ?? "",
      ]),
    ),
  ].join("\n");
}
