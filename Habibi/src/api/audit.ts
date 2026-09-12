// -----------------------------------------------------------------------------
// Audit Trail (Call History) — data access seam.
//   fetchCalls() → every historical call record  (GET /calls)
// Filtering is client-side (lib/audit.filterCalls); it can move to query params
// on /calls when the list outgrows one page.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import type { CallFlag, CallRecord } from "@/api/types/audit";
import { apiGet } from "./config";

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
