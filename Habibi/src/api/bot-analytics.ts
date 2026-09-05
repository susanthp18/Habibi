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
import {
  computeKpis,
  dailySeries as seedDailySeries,
  escalationReasons as seedEscalationReasons,
  filterByRange,
  funnelStages as seedFunnelStages,
  intentAggs as seedIntentAggs,
  turnsHistogram as seedTurnsHistogram,
  unansweredQuestions as seedUnansweredQuestions,
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

/** Live pushes channel into SQL. Mock scales historic PoC session counts here. */
export function analyticsKpis(points: DailyPoint[], channel: ChannelKey) {
  const base = computeKpis(points);
  if (!USE_MOCK || channel === "all") return base;
  const factor = channel === "voice" ? 0.72 : channel === "whatsapp" ? 0.2 : 0.08;
  return { ...base, sessions: Math.round(base.sessions * factor) };
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
