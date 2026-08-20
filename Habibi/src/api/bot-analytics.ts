// -----------------------------------------------------------------------------
// Conversation & Bot Analytics — data access seam (read-only).
//   useBotAnalytics(range, channel) → GET /bot-analytics
//
// Live path aggregates from interactions (+ handoffs / transcript / unanswered).
// Mock path returns the seed exports filtered by range. No mutations.
// KPIs stay client-side via computeKpis(dailySeries).
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  dailySeries as seedDailySeries,
  escalationReasons as seedEscalationReasons,
  filterByRange,
  funnelStages as seedFunnelStages,
  intentAggs as seedIntentAggs,
  turnsHistogram as seedTurnsHistogram,
  unansweredQuestions as seedUnansweredQuestions,
  type ChannelKey,
  type DailyPoint,
  type EscalationReason,
  type IntentAgg,
  type RangeKey,
  type TurnsBucket,
  type UnansweredQuestion,
} from "@/data/bot-analytics-seed";
import { apiGet, mockDelay, USE_MOCK } from "./config";

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
  if (USE_MOCK) {
    // Mock keeps the old client-side range slice; channel scaling stays in the route.
    return mockDelay({
      dailySeries: filterByRange(range, seedDailySeries),
      intentAggs: seedIntentAggs,
      escalationReasons: seedEscalationReasons,
      unansweredQuestions: seedUnansweredQuestions,
      turnsHistogram: seedTurnsHistogram,
      funnelStages: seedFunnelStages,
    });
  }
  const qs = new URLSearchParams({ range, channel });
  return apiGet<BotAnalytics>(`/bot-analytics?${qs.toString()}`);
}

export function useBotAnalytics(range: RangeKey, channel: ChannelKey) {
  return useQuery({
    queryKey: ["bot-analytics", range, channel],
    queryFn: () => fetchBotAnalytics(range, channel),
    staleTime: 15_000,
  });
}

export type {
  ChannelKey,
  DailyPoint,
  EscalationReason,
  IntentAgg,
  RangeKey,
  TurnsBucket,
  UnansweredQuestion,
};
