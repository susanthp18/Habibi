// -----------------------------------------------------------------------------
// Offer-engine observability — GET /offers/health.
//
// Part 7 of upsell_engine_plan.md. `offer_decisions` has carried every field
// these numbers need since the engine shipped; nothing surfaced them, so the
// only way to answer "is the recommender helping?" was ad-hoc SQL.
//
// Thresholds are NOT evaluated here. The server computes `alerts` and the UI
// renders them, because a threshold that lives in a chart config is a threshold
// nobody reviews — and because the same verdict has to reach a dashboard, a
// page and a weekly report without three implementations drifting apart.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import { apiGet, mockDelay, USE_MOCK } from "./config";

export type OfferHealthWindow = "24h" | "7d" | "30d" | "90d";

export interface OfferHealthAlert {
  metric: string;
  message: string;
}

export interface OfferEngineState {
  /** off | shadow | live. Shadow scores and logs but never speaks. */
  mode: string;
  scorer: string;
  abSplit: Array<{ variant: string; share: number }>;
  /** Unwindowed: null means the engine has never logged a decision at all. */
  lastDecisionAt: string | null;
}

export interface OfferHealth {
  window: string;
  includesSimulated: boolean;
  // What the engine is configured to do, alongside what it did. Every rate
  // below is null on an engine that has never run, and a wall of dashes cannot
  // by itself distinguish "off", "shadow by design" and "a quiet week".
  engine: OfferEngineState;
  volume: {
    decisions: number;
    approved: number;
    presented: number;
    customers: number;
    interactions: number;
  };
  // Every rate is `number | null`. Null means the denominator was zero, which
  // is not the same fact as 0% — "we presented nothing" and "nothing we
  // presented converted" call for opposite responses, and rendering both as
  // 0% is how a dead engine looks like a bad one.
  funnel: {
    coverage: number | null;
    coveragePrevious: number | null;
    coverageChange: number | null;
    presentationRate: number | null;
    interestRate: number | null;
    declineRate: number | null;
    responseRate: number | null;
  };
  latency: {
    p50: number | null;
    p95: number | null;
    p99: number | null;
    max: number | null;
    samples: number;
    budgetMs: number;
    withinBudget: boolean | null;
  };
  suppressionByReason: Array<{ reason: string; n: number; share: number | null }>;
  exclusionByReason: Array<{ reason: string; n: number }>;
  byProduct: Array<{
    product_id: string;
    product_name: string | null;
    presented: number;
    interested: number;
    won: number;
    lost: number;
    interestRate: number | null;
    winRate: number | null;
  }>;
  byRecommender: Array<{
    recommender: string;
    version: string;
    presented: number;
    interested: number;
    won: number;
    lost: number;
    interestRate: number | null;
    winRate: number | null;
  }>;
  byVariant: Array<{
    variant: string;
    decisions: number;
    customers: number;
    approved: number;
    presented: number;
    interested: number;
    won: number;
    coverage: number | null;
    interestRate: number | null;
    avgDurationSec: number | null;
    avgSentiment: number | null;
  }>;
  eligibility: {
    flags: number;
    unknown: number;
    failed: number;
    unknownRate: number | null;
  };
  closeProbe: {
    asked: number;
    declined: number;
    captured: number;
    conversion: number | null;
  };
  guardrails: {
    avgDurationSecWithOffer: number | null;
    avgDurationSecWithoutOffer: number | null;
    ahtDeltaSec: number | null;
    avgSentimentWithOffer: number | null;
    avgSentimentWithoutOffer: number | null;
    escalationRateWithOffer: number | null;
    escalationRateWithoutOffer: number | null;
  };
  alerts: OfferHealthAlert[];
}

/** Mock shape for USE_MOCK — deliberately unremarkable numbers, no alerts. */
const mockOfferHealth: OfferHealth = {
  window: "30d",
  includesSimulated: false,
  engine: { mode: "live", scorer: "rule", abSplit: [], lastDecisionAt: "2026-08-17T09:00:00Z" },
  volume: { decisions: 1240, approved: 806, presented: 677, customers: 412, interactions: 1180 },
  funnel: {
    coverage: 0.65,
    coveragePrevious: 0.63,
    coverageChange: 0.02,
    presentationRate: 0.84,
    interestRate: 0.163,
    declineRate: 0.79,
    responseRate: 0.95,
  },
  latency: {
    p50: 15,
    p95: 30,
    p99: 50,
    max: 148,
    samples: 1240,
    budgetMs: 150,
    withinBudget: true,
  },
  suppressionByReason: [
    { reason: "no_commitment_yet", n: 210, share: 0.48 },
    { reason: "sentiment_below_floor", n: 120, share: 0.28 },
    { reason: "no_eligible_candidates", n: 104, share: 0.24 },
  ],
  exclusionByReason: [
    { reason: "eligibility", n: 3120 },
    { reason: "already_held", n: 1180 },
    { reason: "open_lead_exists", n: 640 },
  ],
  byProduct: [
    {
      product_id: "topup-loan",
      product_name: "Top-up Loan",
      presented: 302,
      interested: 61,
      won: 18,
      lost: 24,
      interestRate: 0.202,
      winRate: 0.429,
    },
  ],
  byRecommender: [
    {
      recommender: "rule",
      version: "1.0.0",
      presented: 677,
      interested: 110,
      won: 31,
      lost: 44,
      interestRate: 0.163,
      winRate: 0.413,
    },
  ],
  byVariant: [],
  eligibility: { flags: 4820, unknown: 1446, failed: 212, unknownRate: 0.3 },
  closeProbe: { asked: 402, declined: 318, captured: 44, conversion: 0.109 },
  guardrails: {
    avgDurationSecWithOffer: 214.5,
    avgDurationSecWithoutOffer: 198.2,
    ahtDeltaSec: 16.3,
    avgSentimentWithOffer: 0.121,
    avgSentimentWithoutOffer: 0.104,
    escalationRateWithOffer: 0.031,
    escalationRateWithoutOffer: 0.034,
  },
  alerts: [],
};

export async function fetchOfferHealth(
  window: OfferHealthWindow = "30d",
  includeSimulated = false,
): Promise<OfferHealth> {
  if (USE_MOCK) return mockDelay({ ...mockOfferHealth, window });
  const query = `?window=${encodeURIComponent(window)}&includeSimulated=${includeSimulated}`;
  return apiGet<OfferHealth>(`/offers/health${query}`);
}

export function useOfferHealth(window: OfferHealthWindow = "30d", includeSimulated = false) {
  return useQuery({
    queryKey: ["offer-health", window, includeSimulated],
    queryFn: () => fetchOfferHealth(window, includeSimulated),
    // These are rolling aggregates over days; refetching per render buys
    // nothing and the queries scan the decision log.
    staleTime: 60_000,
  });
}

export type TunerCopyItem = { name: string; value: number; current: number };

export type TunerSuggestions = {
  mode: string;
  applied: boolean;
  note: string;
  copyToEnv: TunerCopyItem[];
  evidence?: { presented?: number; declined?: number; days?: number };
  treatment?: {
    mode: string;
    applied: boolean;
    note: string;
    copyToEnv: TunerCopyItem[];
    evidence?: { actionable?: number; fieldVisits?: number; days?: number };
  };
};

export function useTunerSuggestions(days = 14) {
  return useQuery({
    queryKey: ["tuner-suggestions", days],
    queryFn: async () =>
      USE_MOCK
        ? mockDelay({
            mode: "shadow",
            applied: false,
            note: "insufficient_log",
            copyToEnv: [],
            treatment: { mode: "shadow", applied: false, note: "insufficient_log", copyToEnv: [] },
          } satisfies TunerSuggestions)
        : apiGet<TunerSuggestions>(`/offers/tuner-suggestions?days=${days}`),
    staleTime: 60_000,
  });
}

/** `0.163` → `"16.3%"`, and null → "—" rather than a misleading "0%". */
export function fmtRate(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

/** Signed variant, for deltas where direction is the whole point. */
export function fmtDelta(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const pct = value * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(digits)}%`;
}
