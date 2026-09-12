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

import { apiGet } from "./config";

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

export async function fetchOfferHealth(
  window: OfferHealthWindow = "30d",
  includeSimulated = false,
): Promise<OfferHealth> {
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
      ({
        mode: "retired",
        applied: false,
        note: "tuner_removed",
        copyToEnv: [],
        treatment: { mode: "retired", applied: false, note: "tuner_removed", copyToEnv: [] },
      }) satisfies TunerSuggestions,
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
