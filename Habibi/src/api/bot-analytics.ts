// -----------------------------------------------------------------------------
// Conversation & Bot Analytics — data access seam (read-only).
//   useBotAnalytics(filters) → GET /bot-analytics
//
// Live path aggregates from interactions (+ handoffs / transcript / unanswered).
// No mutations. Headline KPIs that daily rows cannot give (true percentiles,
// deflection, sentiment lift) come from the server's `summary`; the rest are
// derived client-side via computeKpis(dailySeries, summary).
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import type {
  ChannelKey,
  DailyPoint,
  EscalationReason,
  IntentAgg,
  RangeKey,
  TurnsBucket,
  UnansweredQuestion,
} from "@/api/types/bot-analytics";
import { computeKpis } from "@/lib/bot-analytics";
import { apiGet } from "./config";

export interface BotAnalytics {
  dailySeries: DailyPoint[];
  intentAggs: IntentAgg[];
  escalationReasons: EscalationReason[];
  unansweredQuestions: UnansweredQuestion[];
  turnsHistogram: TurnsBucket[];
  funnelStages: Array<{ id: string; label: string; count: number }>;
  byCard?: Array<{
    botId: string;
    sessions: number;
    contained: number;
    escalated: number;
    containment: number;
    handoffRate: number;
    latencyP99: number;
    sloMs: number;
  }>;
  skillHistogram?: Array<{ skillId: string; activations: number }>;
  summary?: BotAnalyticsSummary | null;
  /** Agents (and Voice Studio versions) with calls in the range and channel. */
  agents?: Array<{ botId: string; name: string; versions: string[] }>;
}

export interface BotAnalyticsSummary {
  botSessions: number;
  containment: number | null;
  deflection: number | null;
  deflectionEligible: number;
  repeatContactDays: number;
  latencyP50: number | null;
  latencyP90: number | null;
  sentimentLift: number | null;
  sentimentLiftCalls: number;
}

export interface BotAnalyticsFilters {
  range: RangeKey;
  channel: ChannelKey;
  /** handler_bot_id; Voice Studio agents are `voice-studio-{workflowId}`. */
  botId?: string;
  /** A Voice Studio published version number. */
  version?: string;
}

export async function fetchBotAnalytics(f: BotAnalyticsFilters): Promise<BotAnalytics> {
  const qs = new URLSearchParams({ range: f.range, channel: f.channel });
  if (f.botId) qs.set("botId", f.botId);
  if (f.version) qs.set("version", f.version);
  return apiGet<BotAnalytics>(`/bot-analytics?${qs.toString()}`);
}

export function useBotAnalytics(f: BotAnalyticsFilters) {
  return useQuery({
    queryKey: ["bot-analytics", f.range, f.channel, f.botId ?? "", f.version ?? ""],
    queryFn: () => fetchBotAnalytics(f),
  });
}

export function analyticsKpis(points: DailyPoint[], summary?: BotAnalyticsSummary | null) {
  return computeKpis(points, summary);
}
