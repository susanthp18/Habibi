// -----------------------------------------------------------------------------
// Audit Trail (Call History) — data access seam.
//   fetchCalls() → every historical call record  (GET /calls)
// Filtering stays client-side (filterCalls in the seed) for the demo; when the
// backend is live this can move to query params on /calls.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import { calls, type CallRecord } from "@/data/audit-seed";
import { apiGet, mockDelay, USE_MOCK } from "./config";

export async function fetchCalls(): Promise<CallRecord[]> {
  if (USE_MOCK) return mockDelay(calls);
  return apiGet<CallRecord[]>("/calls");
}

export function useCalls() {
  return useQuery({
    queryKey: ["calls"],
    queryFn: fetchCalls,
    staleTime: 30_000,
  });
}
