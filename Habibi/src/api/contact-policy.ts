// -----------------------------------------------------------------------------
// Contact policy — the authoritative "may we contact this borrower right now?"
// verdict.  GET /customers/:id/contact-policy  (backend/main.py).
//
// The answer is the backend's, never the browser's. It is computed in the
// BORROWER's timezone against the statutory calling window, their consent
// record, allowed days, cooling-off and the daily/weekly caps — none of which
// the client can see. Recomputing any part of it here produces a second opinion
// that disagrees with the veto the dialler will actually apply, which on this
// screen means telling an agent it is fine to ring someone at 03:00.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./config";

/** Mirrors backend/schemas.py :: ContactPolicyResponse. */

export interface ContactPolicy {
  allowed: boolean;
  /** Veto code from contact_policy.py, or null when allowed. */
  reason: string | null;
  touchCounted: boolean;
  outreachToday: number;
  dailyCap: number;
  coalesced: boolean;
  channel: string;
  purpose: string;
}

export type ContactChannel = "voice" | "whatsapp" | "sms" | "email" | "chat" | "field";

export type ContactPurpose = "outreach" | "statutory" | "in_session";

export async function fetchContactPolicy(
  customerId: string,
  opts: { channel?: ContactChannel; purpose?: ContactPurpose; signal?: AbortSignal } = {},
): Promise<ContactPolicy> {
  const channel = opts.channel ?? "voice";
  const purpose = opts.purpose ?? "outreach";
  // The backend defaults this endpoint to channel=whatsapp, so both params are
  // always sent explicitly — the pill asks about voice.
  return apiGet<ContactPolicy>(
    `/customers/${encodeURIComponent(customerId)}/contact-policy?channel=${channel}&purpose=${purpose}`,
    { signal: opts.signal },
  );
}

/**
 * The verdict is a function of the clock, so it goes stale on its own: a pill
 * fetched at 18:58 is wrong at 19:01. Refetch on an interval and on focus so it
 * cannot sit green past the end of the calling window.
 */
export function useContactPolicy(
  customerId: string | undefined,
  opts: { channel?: ContactChannel; purpose?: ContactPurpose } = {},
) {
  const channel = opts.channel ?? "voice";
  const purpose = opts.purpose ?? "outreach";
  return useQuery({
    queryKey: ["contact-policy", customerId, channel, purpose],
    queryFn: ({ signal }) => fetchContactPolicy(customerId!, { channel, purpose, signal }),
    enabled: Boolean(customerId),
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });
}
