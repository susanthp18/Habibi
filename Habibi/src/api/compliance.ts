// -----------------------------------------------------------------------------
// Compliance Risk — data access seam.
//   fetchViolations() → feed list  (GET /violations)
//   assign / acknowledge / resolve / add note → Phase 3A writes (hardened in 3B)
//
// Mock branch preserves in-memory seed mutators. Live branch maps to PATCH +
// POST /notes; the screen shape is richer than the old {id,status} stub, so
// callers invalidate + refetch. Assignees resolve through /staff; note author
// is the acting user from GET /me — never a hardcoded "You" / CURRENT_AGENT.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  acknowledgeViolation as acknowledgeSeed,
  addViolationNote as addSeedNote,
  assignViolation as assignSeed,
  resolveViolation as resolveSeed,
  violations as seedViolations,
  type Violation,
  type ViolationStatus,
} from "@/data/compliance-seed";
import { apiGet, apiPatch, apiPost, mockDelay, USE_MOCK } from "./config";
import { currentActor } from "./me";
import { resolveActor } from "./staff";

export async function fetchViolations(): Promise<Violation[]> {
  if (USE_MOCK) return mockDelay(seedViolations);
  return apiGet<Violation[]>("/violations");
}

export function useViolations() {
  return useQuery({ queryKey: ["violations"], queryFn: fetchViolations, staleTime: 15_000 });
}

async function postNote(id: string, note: string): Promise<void> {
  const text = note.trim();
  if (!text) return;
  if (USE_MOCK) {
    const me = await currentActor();
    addSeedNote(id, text, me.name);
    return;
  }
  await apiPost(`/violations/${id}/notes`, { text });
}

export async function assignViolation(
  v: Violation,
  assignee: string,
  note = "Assigned for review.",
): Promise<void> {
  if (USE_MOCK) {
    const me = await currentActor();
    assignSeed(v.id, assignee, note, me.name);
    return;
  }
  const actor = await resolveActor(assignee);
  if (actor.kind !== "human") {
    throw new Error(`${assignee} is a bot — compliance review is assigned to people`);
  }
  await apiPatch(`/violations/${v.id}`, {
    status: "in_review" satisfies ViolationStatus,
    assigneeUserId: actor.id,
  });
  await postNote(v.id, note);
}

export async function acknowledgeViolation(v: Violation, note = "Acknowledged."): Promise<void> {
  if (USE_MOCK) {
    const me = await currentActor();
    acknowledgeSeed(v.id, note, me.name);
    return;
  }
  await apiPatch(`/violations/${v.id}`, { status: "acknowledged" satisfies ViolationStatus });
  await postNote(v.id, note);
}

export async function resolveViolation(v: Violation, note: string): Promise<void> {
  const text = note.trim();
  if (!text) throw new Error("A resolution note is required");
  if (USE_MOCK) {
    const me = await currentActor();
    resolveSeed(v.id, text, me.name);
    return;
  }
  await apiPatch(`/violations/${v.id}`, { status: "resolved" satisfies ViolationStatus });
  await postNote(v.id, text);
}

export async function addViolationNote(v: Violation, note: string): Promise<void> {
  await postNote(v.id, note);
}

export type { Violation, ViolationStatus };
