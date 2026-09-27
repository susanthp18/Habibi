// -----------------------------------------------------------------------------
// Audit Trail (Call History) — data access seam.
//   fetchCalls() → every historical call record  (GET /calls)
// Filtering is client-side (lib/audit.filterCalls); it can move to query params
// on /calls when the list outgrows one page.
// -----------------------------------------------------------------------------

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

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

/** Calls per page on the Audit screen; each row carries its transcript. */
export const CALLS_PAGE = 100;

async function fetchCallsPage(offset: number): Promise<CallRecord[]> {
  const rows = await apiGet<Array<Omit<CallRecord, "flags"> & { flags: unknown }>>(
    `/calls?limit=${CALLS_PAGE}&offset=${offset}`,
  );
  return rows.map((r) => ({ ...r, flags: normalizeFlags(r.flags) }));
}

/** The Audit list, newest first, one page at a time ("Load older calls"). */
export function useCallPages() {
  return useInfiniteQuery({
    queryKey: ["calls", "pages"],
    queryFn: ({ pageParam }) => fetchCallsPage(pageParam),
    initialPageParam: 0,
    getNextPageParam: (last, all) =>
      last.length < CALLS_PAGE ? undefined : all.length * CALLS_PAGE,
    staleTime: 30_000,
  });
}

/** One call by id: a deep link (Compliance "Open in Audit") to a call outside the loaded pages. */
export function useCall(id: string | null) {
  return useQuery({
    queryKey: ["calls", "one", id],
    queryFn: async () => {
      const r = await apiGet<Omit<CallRecord, "flags"> & { flags: unknown }>(
        `/calls/${encodeURIComponent(id!)}`,
      );
      return { ...r, flags: normalizeFlags(r.flags) };
    },
    enabled: !!id,
    staleTime: 30_000,
  });
}

export function useCalls() {
  return useQuery({
    queryKey: ["calls"],
    queryFn: fetchCalls,
    staleTime: 30_000,
  });
}

export interface EvidenceVerification {
  linked: boolean;
  ok: boolean;
  hash?: string | null;
  seq?: number | null;
  /** link, predecessor, recording, transcript: each recomputed now. */
  checks: { check: string; ok: boolean }[];
}

/** Recompute the call's evidence-chain link on demand (hash, predecessor, recording, words). */
export function useEvidence(interactionId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["calls", "evidence", interactionId],
    queryFn: () =>
      apiGet<EvidenceVerification>(`/interactions/${encodeURIComponent(interactionId)}/evidence`),
    enabled,
    staleTime: 0,
  });
}
