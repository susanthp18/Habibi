// -----------------------------------------------------------------------------
// Assignable actors (humans + bots) — the single source for owner/assignee pickers.
//
// Replaces per-screen hardcoded name→id maps, which silently drift from the DB
// (a seed-only name like "Rohan Sethi" would 404 on assignment). Live mode reads
// GET /staff; mock mirrors the seeded roster so both modes stay coherent.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import { apiGet, mockDelay, USE_MOCK } from "./config";

export interface Staff {
  id: string;
  name: string;
  kind: "human" | "bot";
  team: string | null;
  status: string | null;
}

/** Mirrors the seeded DB roster so mock mode resolves the same names. */
const MOCK_STAFF: Staff[] = [
  { id: "arjun-mehta", name: "Arjun Mehta", kind: "human", team: "Card Collections", status: "active" },
  { id: "david-chen", name: "David Chen", kind: "human", team: "Supervisors", status: "active" },
  { id: "meera-iyer", name: "Meera Iyer", kind: "human", team: "Card Collections", status: "active" },
  { id: "priya-nair", name: "Priya Nair", kind: "human", team: "Supervisors", status: "active" },
  { id: "rahul-verma", name: "Rahul Verma", kind: "human", team: "Card Collections", status: "active" },
  { id: "rohan-verma", name: "Rohan Verma", kind: "human", team: "Card Collections", status: "active" },
  { id: "sara-khan", name: "Sara Khan", kind: "human", team: "Card Collections", status: "active" },
  { id: "collectionsbot-v2-4", name: "CollectionsBot v2.4", kind: "bot", team: null, status: "active" },
  { id: "kaia-v2-4", name: "Kaia v2.4", kind: "bot", team: null, status: "active" },
  { id: "webchatbot", name: "WebChatBot", kind: "bot", team: null, status: "active" },
];

export async function fetchStaff(): Promise<Staff[]> {
  if (USE_MOCK) return mockDelay(MOCK_STAFF);
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
