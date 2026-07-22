// -----------------------------------------------------------------------------
// QA Scorecards — data access seam (scorecard core MVP).
//   fetchScorecards / fetchRubric → GET /scorecards + GET /rubric
//   saveScorecard / finalizeScorecard → widened PATCH /scorecards/{id}
//
// Coaching + calibration stay on seed until their endpoints land. Reviewer is
// always the acting user from GET /me — never a hardcoded "You" / "Meera Joshi".
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  defaultRubric,
  scorecards as seedScorecards,
  type Rubric,
  type Scorecard,
  type ScorecardEntry,
} from "@/data/qa-seed";
import { apiGet, apiPatch, mockDelay, USE_MOCK } from "./config";
import { currentActor } from "./me";

export async function fetchScorecards(): Promise<Scorecard[]> {
  if (USE_MOCK) return mockDelay(seedScorecards);
  return apiGet<Scorecard[]>("/scorecards");
}

export function useScorecards() {
  return useQuery({ queryKey: ["scorecards"], queryFn: fetchScorecards, staleTime: 15_000 });
}

export async function fetchRubric(): Promise<Rubric> {
  if (USE_MOCK) return mockDelay(defaultRubric);
  return apiGet<Rubric>("/rubric");
}

export function useRubric() {
  return useQuery({ queryKey: ["rubric"], queryFn: fetchRubric, staleTime: 5 * 60_000 });
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

export type { Rubric, Scorecard, ScorecardEntry };
