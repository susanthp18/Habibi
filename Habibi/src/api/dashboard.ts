// -----------------------------------------------------------------------------
// Executive Dashboard — data access seam.
//
// The mock branch applies the same filter scaling the real backend will perform
// server-side, so the component stays purely presentational. Going live is a
// one-line change (see fetchDashboard below).
// -----------------------------------------------------------------------------

import { useMutation, useQuery } from "@tanstack/react-query";

import type {
  AtRiskAccount,
  HeroKpi,
  Kpi,
  LeaderRow,
  Range,
  Segment,
  StackedPoint,
  TeamFilter,
  Trend,
} from "@/api/types/dashboard";
import type { ExportJob } from "@/api/types/redaction";
import { apiGet, apiGetBlob, apiPost } from "./config";

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

/**
 * Fetch the executive dashboard for the given filters.
 * PHASE 2: delete the mock branch — the live branch below is the real call.
 */
export async function fetchDashboard(params: DashboardParams): Promise<DashboardData> {
  const qs = new URLSearchParams(params).toString();
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

export async function fetchDashboardCsv(params: DashboardParams): Promise<{ blob: Blob; filename: string }> {
  const qs = new URLSearchParams(params).toString();
  const { blob, headers } = await apiGetBlob(`/dashboard.csv?${qs}`);
  const filename =
    headers.get("Content-Disposition")?.match(/filename="([^"]+)"/)?.[1] ||
    `dashboard-${params.range}-${params.segment}-${params.team}.csv`;
  return { blob, filename };
}

export async function emailDashboardExport(params: DashboardParams): Promise<ExportJob> {
  return apiPost<ExportJob>("/export-jobs", { kind: "dashboard", ...params, format: "csv" });
}

export function useEmailDashboardExport() {
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: emailDashboardExport,
  });
}
