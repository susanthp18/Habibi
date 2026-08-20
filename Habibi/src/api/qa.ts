// -----------------------------------------------------------------------------
// QA Scorecards — data access seam.
//   Scorecards/rubric: GET + PATCH (core MVP)
//   Coaching / calibration: GET + POST/PATCH (fast-follow)
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  defaultRubric,
  initialCalibrations,
  initialCoaching,
  scorecards as seedScorecards,
  type CalibrationSession,
  type CoachingAction,
  type CoachingStatus,
  type Rubric,
  type Scorecard,
  type ScorecardEntry,
} from "@/data/qa-seed";
import { apiGet, apiPatch, apiPost, mockDelay, USE_MOCK } from "./config";
import { currentActor } from "./me";

export async function fetchScorecards(): Promise<Scorecard[]> {
  if (USE_MOCK) return mockDelay(seedScorecards);
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
  if (USE_MOCK) {
    return mockDelay({
      windowDays: 7,
      completed: 24,
      scored: 18,
      coverage: 0.75,
      pendingReview: 10,
      criticalFails: 2,
    });
  }
  return apiGet<QaCoverage>("/qa/coverage");
}

export function useQaCoverage() {
  return useQuery({ queryKey: ["qa-coverage"], queryFn: fetchQaCoverage, staleTime: 30_000 });
}

export async function fetchQaInteractionPack(interactionId: string): Promise<Record<string, unknown>> {
  if (USE_MOCK) {
    return mockDelay({ interactionId, transcript: "", flags: [], liveQa: [] });
  }
  return apiGet(`/qa/interactions/${encodeURIComponent(interactionId)}/pack`);
}

export async function fetchRubric(rubricId?: string | null): Promise<Rubric> {
  if (USE_MOCK) return mockDelay(defaultRubric);
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

function mutateSeedScorecard(
  id: string,
  patch: Partial<Scorecard> & { entries?: ScorecardEntry[] },
): void {
  const idx = seedScorecards.findIndex((s) => s.id === id);
  if (idx < 0) return;
  const current = seedScorecards[idx]!;
  seedScorecards[idx] = { ...current, ...patch, entries: patch.entries ?? current.entries };
}

/** Persist criterion scores as an AI draft (or keep final if already published). */
export async function saveScorecard(sc: Scorecard, entries: ScorecardEntry[]): Promise<void> {
  if (USE_MOCK) {
    mutateSeedScorecard(sc.id, {
      entries,
      status: sc.status === "final" ? "final" : "ai_draft",
    });
    await mockDelay(undefined);
    return;
  }
  await apiPatch(`/scorecards/${sc.id}`, {
    status: sc.status === "final" ? "final" : "ai_draft",
    entries,
  });
}

/** Publish the scorecard — sets final + reviewer from the acting user. */
export async function finalizeScorecard(sc: Scorecard, entries: ScorecardEntry[]): Promise<void> {
  if (USE_MOCK) {
    const me = await currentActor();
    mutateSeedScorecard(sc.id, {
      entries,
      status: "final",
      reviewer: me.name,
      scoredAt: new Date().toISOString(),
    });
    await mockDelay(undefined);
    return;
  }
  const me = await currentActor();
  await apiPatch(`/scorecards/${sc.id}`, {
    status: "final",
    entries,
    reviewerUserId: me.id,
  });
}

// ---------- Coaching ----------

let _mockCoaching: CoachingAction[] = [...initialCoaching];

export async function fetchCoachingActions(): Promise<CoachingAction[]> {
  if (USE_MOCK) return mockDelay(_mockCoaching);
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
  if (USE_MOCK) {
    const item: CoachingAction = {
      ...data,
      id: `coach-${Date.now()}`,
      status: "assigned",
      notes: [],
      createdAt: new Date().toISOString(),
    };
    _mockCoaching = [item, ..._mockCoaching];
    return mockDelay(item);
  }
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
  if (USE_MOCK) {
    _mockCoaching = _mockCoaching.map((a) => (a.id === id ? { ...a, ...patch } : a));
    const row = _mockCoaching.find((a) => a.id === id);
    if (!row) throw new Error("coaching_action_not_found");
    return mockDelay(row);
  }
  return apiPatch<CoachingAction>(`/coaching-actions/${id}`, patch);
}

// ---------- Calibration ----------

let _mockCalibrations: CalibrationSession[] = [...initialCalibrations];

export async function fetchCalibrationSessions(): Promise<CalibrationSession[]> {
  if (USE_MOCK) return mockDelay(_mockCalibrations);
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
  if (USE_MOCK) {
    _mockCalibrations = _mockCalibrations.map((s) =>
      s.id === id ? { ...s, status: patch.status } : s,
    );
    const row = _mockCalibrations.find((s) => s.id === id);
    if (!row) throw new Error("calibration_session_not_found");
    return mockDelay(row);
  }
  return apiPatch<CalibrationSession>(`/calibration-sessions/${id}`, patch);
}

export type { Rubric, Scorecard, ScorecardEntry, CoachingAction, CalibrationSession };
