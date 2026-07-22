// -----------------------------------------------------------------------------
// The acting user — one identity for the whole app.
//
// The shell used to render a hardcoded "Priya Shah · Team Delta" while the
// backend recorded every write against `priya-nair` ("Priya Nair"). Two
// identities that disagree make the audit trail lie, so both now come from
// GET /me. Real authentication replaces the server side in Phase 5 (OIDC);
// this seam does not change when it does.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import { apiGet, mockDelay, USE_MOCK } from "./config";

export interface Me {
  id: string;
  name: string;
  kind: "human" | "bot";
  team: string | null;
  status: string | null;
  tenantId: string;
}

/** Mock identity mirrors the seeds' CURRENT_AGENT so both modes agree. */
const MOCK_ME: Me = {
  id: "priya-nair",
  name: "Priya Nair",
  kind: "human",
  team: "Supervisors",
  status: "active",
  tenantId: "hdfc.retail",
};

export async function fetchMe(): Promise<Me> {
  if (USE_MOCK) return mockDelay(MOCK_ME);
  return apiGet<Me>("/me");
}

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: 5 * 60_000 });
}

let meCache: Promise<Me> | null = null;

/** For non-hook callers (mutations, defaults). */
export function currentActor(): Promise<Me> {
  if (!meCache) {
    meCache = fetchMe().catch((err) => {
      meCache = null;
      throw err;
    });
  }
  return meCache;
}
