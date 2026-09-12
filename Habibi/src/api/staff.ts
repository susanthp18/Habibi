// -----------------------------------------------------------------------------
// Assignable actors (humans + bots) — the single source for owner/assignee pickers.
//
// Replaces per-screen hardcoded name→id maps, which silently drift from the DB
// (a name the roster does not hold would 404 on assignment). GET /staff.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./config";

export interface Staff {
  id: string;
  name: string;
  kind: "human" | "bot";
  team: string | null;
  status: string | null;
}

export async function fetchStaff(): Promise<Staff[]> {
  return apiGet<Staff[]>("/staff");
}

export function useStaff() {
  return useQuery({ queryKey: ["staff"], queryFn: fetchStaff, staleTime: 5 * 60_000 });
}

// Mutations are plain async functions (not hooks), so they resolve names through
// a memoised roster rather than a React query.
let rosterCache: Promise<Staff[]> | null = null;

export function staffRoster(): Promise<Staff[]> {
  if (!rosterCache) {
    rosterCache = fetchStaff().catch((err) => {
      rosterCache = null; // don't cache failures
      throw err;
    });
  }
  return rosterCache;
}

/** Resolve a display name to a real actor, or throw with a clear reason. */
export async function resolveActor(name: string): Promise<Staff> {
  const roster = await staffRoster();
  const match = roster.find((s) => s.name === name);
  if (!match) {
    throw new Error(`"${name}" isn't a known user or bot — pick someone from the roster`);
  }
  return match;
}

export function humanNames(roster: Staff[]): string[] {
  return roster.filter((s) => s.kind === "human").map((s) => s.name);
}
