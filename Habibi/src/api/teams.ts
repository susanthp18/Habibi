// -----------------------------------------------------------------------------
// Teams / queues — picker roster sourced from the DB (GET /teams).
// Same anti-drift rationale as api/staff.ts: never hardcode name→id maps.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./config";

export interface Team {
  id: string;
  name: string;
}

export async function fetchTeams(): Promise<Team[]> {
  return apiGet<Team[]>("/teams");
}

export function useTeams() {
  return useQuery({ queryKey: ["teams"], queryFn: fetchTeams, staleTime: 5 * 60_000 });
}

let rosterCache: Promise<Team[]> | null = null;

export function teamRoster(): Promise<Team[]> {
  if (!rosterCache) {
    rosterCache = fetchTeams().catch((err) => {
      rosterCache = null;
      throw err;
    });
  }
  return rosterCache;
}

export async function resolveTeam(name: string): Promise<Team> {
  const roster = await teamRoster();
  const match = roster.find((t) => t.name === name);
  if (!match) {
    throw new Error(`"${name}" isn't a known team — pick a queue from the roster`);
  }
  return match;
}

export function teamNames(roster: Team[]): string[] {
  return roster.map((t) => t.name);
}
