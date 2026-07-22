// -----------------------------------------------------------------------------
// Executive Dashboard — data access seam.
//
// The mock branch applies the same filter scaling the real backend will perform
// server-side, so the component stays purely presentational. Going live is a
// one-line change (see fetchDashboard below).
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  atRiskAccounts,
  botVsHuman,
  callVolumeStacked,
  filterMultiplier,
  heroKpis,
  kpis,
  leaderboard,
  recoveryTrend,
  sentimentDistribution,
  type AtRiskAccount,
  type HeroKpi,
  type Kpi,
  type LeaderRow,
  type Range,
  type Segment,
  type StackedPoint,
  type TeamFilter,
  type Trend,
} from "@/data/dashboard-seed";
import { apiGet, mockDelay, USE_MOCK } from "./config";

export type DashboardParams = { range: Range; segment: Segment; team: TeamFilter };

export type SentimentDistribution = { positive: number; neutral: number; negative: number };
export type BotVsHumanSlice = { name: string; value: number; color: string };

/** The full payload the /dashboard endpoint returns (already filtered/scaled). */
export type DashboardData = {
  heroKpis: HeroKpi[];
  kpis: Kpi[];
  recoveryTrend: Trend[];
  callVolumeStacked: StackedPoint[];
  sentimentDistribution: SentimentDistribution;
  botVsHuman: BotVsHumanSlice[];
  leaderboard: LeaderRow[];
  atRiskAccounts: AtRiskAccount[];
};

// --- Mock: replicates the server-side filtering the CRM API will do ----------
function buildMockDashboard({ range, segment, team }: DashboardParams): DashboardData {
  const m = filterMultiplier(range, segment, team);

  const scaledHero = heroKpis.map((k, i) => {
    if (i === 0) {
      // AHT — scale seconds, tighten when the bot-only filter is selected
      const secs = Math.round(k.raw * (team === "bot" ? 0.55 : team === "human" ? 1.35 : 1));
      const mm = Math.floor(secs / 60);
      const ss = secs % 60;
      return { ...k, value: `${mm}m ${ss.toString().padStart(2, "0")}s` };
    }
    // Upsell conversion — mild segment influence
    const raw = k.raw * (segment === "personal" ? 1.4 : segment === "card" ? 1.1 : 1);
    return { ...k, value: `${raw.toFixed(1)}%` };
  });

  const scaledKpis = kpis.map((k) => {
    if (k.key === "recovered") {
      const v = 2.48 * m;
      return { ...k, value: v >= 1 ? `$${v.toFixed(2)}M` : `$${(v * 1000).toFixed(0)}k` };
    }
    if (k.key === "calls") {
      return { ...k, value: Math.round(8412 * m).toLocaleString() };
    }
    return k;
  });

  const scaledRecovery = recoveryTrend.map((p) => ({ ...p, value: Math.round(p.value * m) }));

  const scaledVolume = callVolumeStacked.map((p) => ({
    ...p,
    voice: Math.round(p.voice * m * (team === "bot" ? 0.9 : 1)),
    whatsapp: Math.round(p.whatsapp * m),
    chat: Math.round(p.chat * m),
  }));

  const scaledBotVsHuman = botVsHuman.map((d) => ({ ...d, value: Math.round(d.value * m) }));

  return {
    heroKpis: scaledHero,
    kpis: scaledKpis,
    recoveryTrend: scaledRecovery,
    callVolumeStacked: scaledVolume,
    sentimentDistribution,
    botVsHuman: scaledBotVsHuman,
    leaderboard,
    atRiskAccounts,
  };
}

/**
 * Fetch the executive dashboard for the given filters.
 * PHASE 2: delete the mock branch — the live branch below is the real call.
 */
export async function fetchDashboard(params: DashboardParams): Promise<DashboardData> {
  if (USE_MOCK) return mockDelay(buildMockDashboard(params));

  const qs = new URLSearchParams(params as Record<string, string>).toString();
  return apiGet<DashboardData>(`/dashboard?${qs}`);
}

/** React-Query hook consumed by the Dashboard screen. */
export function useDashboard(params: DashboardParams) {
  return useQuery({
    queryKey: ["dashboard", params],
    queryFn: () => fetchDashboard(params),
    staleTime: 30_000,
  });
}
