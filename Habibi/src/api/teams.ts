// -----------------------------------------------------------------------------
// Teams / queues — picker roster sourced from the DB (GET /teams).
// Same anti-drift rationale as api/staff.ts: never hardcode name→id maps.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import { apiGet, mockDelay, USE_MOCK } from "./config";

export interface Team {
  id: string;
  name: string;
}

/** Mirrors the seeded DB teams so mock mode resolves the same names. */
const MOCK_TEAMS: Team[] = [
  { id: "card-collections", name: "Card Collections" },
  { id: "cards-sales", name: "Cards Sales" },
  { id: "insurance", name: "Insurance" },
  { id: "retail-collections", name: "Retail Collections" },
  { id: "retail-sales", name: "Retail Sales" },
  { id: "supervisors", name: "Supervisors" },
];

export async function fetchTeams(): Promise<Team[]> {
  if (USE_MOCK) return mockDelay(MOCK_TEAMS);
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
