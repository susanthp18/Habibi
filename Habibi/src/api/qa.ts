// -----------------------------------------------------------------------------
// QA Scorecards — data access seam.
//   Scorecards/rubric: GET + PATCH (core MVP)
//   Coaching / calibration: GET + POST/PATCH (fast-follow)
// -----------------------------------------------------------------------------

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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
import { toast } from "sonner";

export async function fetchScorecards(): Promise<Scorecard[]> {
  return apiGet<Scorecard[]>("/scorecards");
}

export function useScorecards() {
  return useQuery({ queryKey: ["scorecards"], queryFn: fetchScorecards });
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
  });
}

export async function patchCalibrationSession(
  id: string,
  patch: { status: "active" | "closed" },
): Promise<CalibrationSession> {
  return apiPatch<CalibrationSession>(`/calibration-sessions/${id}`, patch);
}

export type { Rubric, Scorecard, ScorecardEntry, CoachingAction, CalibrationSession };

// ---------- mutations ----------

export function useSaveScorecard() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: async (v: { sc: Scorecard; entries: ScorecardEntry[] }) => {
      await saveScorecard(v.sc, v.entries);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["scorecards"] });
      toast.success("Draft saved");
    },
  });
}

export function useFinalizeScorecard() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: async (v: { sc: Scorecard; entries: ScorecardEntry[] }) => {
      await finalizeScorecard(v.sc, v.entries);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["scorecards"] });
      toast.success("Scorecard published", {
        description: "Sent to agent + logged to audit trail.",
      });
    },
  });
}

export function useMoveCoachingAction() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (v: { id: string; status: CoachingAction["status"] }) =>
      patchCoachingAction(v.id, { status: v.status }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["coaching-actions"] }),
  });
}

export function useCreateCoachingAction() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: createCoachingAction,
    onSuccess: (item) => {
      void qc.invalidateQueries({ queryKey: ["coaching-actions"] });
      toast.success("Coaching action created", { description: `${item.agentId} · ${item.title}` });
    },
  });
}

export function useCloseCalibrationSession() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "toast" },
    mutationFn: (id: string) => patchCalibrationSession(id, { status: "closed" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["calibration-sessions"] });
      toast.success("Calibration closed");
    },
  });
}

// ---------------------------------------------------------------------------
// GET /eval/disagreements — where the auto-scorer and a human disagreed.
//
// Only the two contradictions that matter are mined: live QA passed a call
// humans scored red, or barged a call humans scored green. Read-only by
// construction — `applied` is false on the envelope and on every item, and the
// module says "Rubric tweaks only" / "this never writes the rubric".
// ---------------------------------------------------------------------------

export type QaDisagreement = {
  interactionId: string | null;
  liveVerdict: string;
  humanBand: string;
  humanScore: number | null;
  suggestedRubricTweak: string;
  applied: boolean;
};

export type QaDisagreements = {
  applied: boolean;
  count: number;
  items: QaDisagreement[];
};

export async function fetchQaDisagreements(limit = 50): Promise<QaDisagreements> {
  return apiGet<QaDisagreements>(`/eval/disagreements?limit=${limit}`);
}

export function useQaDisagreements(limit = 50) {
  return useQuery({
    queryKey: ["eval-disagreements", limit],
    queryFn: () => fetchQaDisagreements(limit),
    staleTime: 60_000,
  });
}
