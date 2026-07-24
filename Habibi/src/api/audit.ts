// -----------------------------------------------------------------------------
// Audit Trail (Call History) — data access seam.
//   fetchCalls() → every historical call record  (GET /calls)
// Filtering stays client-side (filterCalls in the seed) for the demo; when the
// backend is live this can move to query params on /calls.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import { calls, type CallFlag, type CallRecord } from "@/data/audit-seed";
import { apiGet, mockDelay, USE_MOCK } from "./config";

/** Live GET /calls returns [{flag,severity}]; the table renders CallFlag[]. */
function normalizeFlags(raw: unknown): CallFlag[] {
  if (!Array.isArray(raw)) return [];
  const out: CallFlag[] = [];
  for (const item of raw) {
    const flag = typeof item === "string" ? item : (item as { flag?: string })?.flag;
    if (!flag || flag === "smoke_flag") continue;
    out.push(flag as CallFlag);
  }
  return out;
}

export async function fetchCalls(): Promise<CallRecord[]> {
  if (USE_MOCK) return mockDelay(calls);
  const rows = await apiGet<Array<Omit<CallRecord, "flags"> & { flags: unknown }>>("/calls");
  return rows.map((r) => ({ ...r, flags: normalizeFlags(r.flags) }));
}

export function useCalls() {
  return useQuery({
    queryKey: ["calls"],
    queryFn: fetchCalls,
    staleTime: 30_000,
  });
}
