// -----------------------------------------------------------------------------
// QA Scorecards — data access seam.
//   Scorecards/rubric: GET + PATCH (core MVP)
//   Coaching / calibration: GET + POST/PATCH (fast-follow)
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import type {
  CalibrationSession,
  CoachingAction,
  CoachingStatus,
  Rubric,
  Scorecard,
  ScorecardEntry,
} from "@/api/types/qa";
import { apiGet, apiPatch, apiPost } from "./config";
import { currentActor } from "./me";

export async function fetchScorecards(): Promise<Scorecard[]> {
  return apiGet<Scorecard[]>("/scorecards");
}

export function useScorecards() {
  return useQuery({ queryKey: ["scorecards"], queryFn: fetchScorecards, staleTime: 15_000 });
}

export type QaCoverage = {
  windowDays: number;
  completed: number;
  scored: number;
  coverage: number | null;
  pendingReview: number;
  criticalFails: number;
};

export async function fetchQaCoverage(): Promise<QaCoverage> {
  return apiGet<QaCoverage>("/qa/coverage");
}

export function useQaCoverage() {
  return useQuery({ queryKey: ["qa-coverage"], queryFn: fetchQaCoverage, staleTime: 30_000 });
}

export async function fetchQaInteractionPack(
  interactionId: string,
): Promise<Record<string, unknown>> {
  return apiGet(`/qa/interactions/${encodeURIComponent(interactionId)}/pack`);
}

export async function fetchRubric(rubricId?: string | null): Promise<Rubric> {
  const q = rubricId ? `?rubricId=${encodeURIComponent(rubricId)}` : "";
  return apiGet<Rubric>(`/rubric${q}`);
}

export function useRubric(rubricId?: string | null) {
  return useQuery({
    queryKey: ["rubric", rubricId ?? "default"],
    queryFn: () => fetchRubric(rubricId),
    staleTime: 5 * 60_000,
  });
}

/** Persist criterion scores as an AI draft (or keep final if already published). */
export async function saveScorecard(sc: Scorecard, entries: ScorecardEntry[]): Promise<void> {
  await apiPatch(`/scorecards/${sc.id}`, {
    status: sc.status === "final" ? "final" : "ai_draft",
    entries,
  });
}

/** Publish the scorecard — sets final + reviewer from the acting user. */
export async function finalizeScorecard(sc: Scorecard, entries: ScorecardEntry[]): Promise<void> {
  const me = await currentActor();
  await apiPatch(`/scorecards/${sc.id}`, {
    status: "final",
    entries,
    reviewerUserId: me.id,
  });
}

export async function fetchCoachingActions(): Promise<CoachingAction[]> {
  return apiGet<CoachingAction[]>("/coaching-actions");
}

export function useCoachingActions() {
  return useQuery({
    queryKey: ["coaching-actions"],
    queryFn: fetchCoachingActions,
    staleTime: 15_000,
  });
}

export async function createCoachingAction(
  data: Omit<CoachingAction, "id" | "createdAt" | "notes" | "status">,
): Promise<CoachingAction> {
  return apiPost<CoachingAction>("/coaching-actions", {
    agentId: data.agentId,
    title: data.title,
    category: data.category,
    scorecardId: data.scorecardId,
    callId: data.callId,
    dueAt: data.dueAt,
  });
}

export async function patchCoachingAction(
  id: string,
  patch: { status?: CoachingStatus; title?: string; category?: string; dueAt?: string },
): Promise<CoachingAction> {
  return apiPatch<CoachingAction>(`/coaching-actions/${id}`, patch);
}

export async function fetchCalibrationSessions(): Promise<CalibrationSession[]> {
  return apiGet<CalibrationSession[]>("/calibration-sessions");
}

export function useCalibrationSessions() {
  return useQuery({
    queryKey: ["calibration-sessions"],
    queryFn: fetchCalibrationSessions,
    staleTime: 15_000,
  });
}

export async function patchCalibrationSession(
  id: string,
  patch: { status: "active" | "closed" },
): Promise<CalibrationSession> {
  return apiPatch<CalibrationSession>(`/calibration-sessions/${id}`, patch);
}

export type { Rubric, Scorecard, ScorecardEntry, CoachingAction, CalibrationSession };
