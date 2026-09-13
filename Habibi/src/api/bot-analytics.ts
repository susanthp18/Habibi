// -----------------------------------------------------------------------------
// Conversation & Bot Analytics — data access seam (read-only).
//   useBotAnalytics(range, channel) → GET /bot-analytics
//
// Live path aggregates from interactions (+ handoffs / transcript / unanswered).
// Mock path returns the seed exports filtered by range. No mutations.
// KPIs stay client-side via computeKpis(dailySeries).
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
}

export async function fetchBotAnalytics(
  range: RangeKey,
  channel: ChannelKey,
): Promise<BotAnalytics> {
  const qs = new URLSearchParams({ range, channel });
  return apiGet<BotAnalytics>(`/bot-analytics?${qs.toString()}`);
}

export function useBotAnalytics(range: RangeKey, channel: ChannelKey) {
  return useQuery({
    queryKey: ["bot-analytics", range, channel],
    queryFn: () => fetchBotAnalytics(range, channel),
  });
}

export function analyticsKpis(points: DailyPoint[], channel: ChannelKey) {
  // The channel narrows the query on the server; nothing is scaled here.
  void channel;
  return computeKpis(points);
}
