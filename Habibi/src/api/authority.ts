// -----------------------------------------------------------------------------
// Live authority matrix — "what may close on this call, in rupees".
//   GET  /authority/next   (backend/main.py :: authority_next)
//   POST /authority/apply
//
// The verdict is the server's. The matrix is policy-as-code in
// backend/agent_core/authority/, and every threshold in it is read from the
// environment at call time on purpose: deciding that a first-time late-fee
// goodwill cap is ₹500 rather than ₹300 is an operational act, not a release.
// A second copy of those numbers in the browser is a copy that goes stale the
// first time an operator tunes one — and a stale copy on this screen quotes a
// borrower a ceiling the backend would refuse to post, or refuses one it would
// have allowed. The panel used to carry exactly that: dpd >= 61 escalates,
// ₹500 under 30 DPD and ₹250 above, and two of the eleven escalate reasons.
//
// GET /authority/next is safe to call from a screen: outside AUTHORITY_MODE=live
// the engine decides, logs and posts nothing. It does write a decision row into
// the shadow corpus each time, which is why this module does not poll.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  authorityReasonLabel,
  authorityStatusFor,
  emptyAuthorityPolicy,
  type AuthorityPolicy,
} from "@/lib/authority-policy";
import { apiGet, apiPost } from "./config";

/** matrix.py :: VERDICTS. */

export type AuthorityVerdict = "auto_approve" | "cap_inr" | "escalate";

/** features.py :: FEE_TYPES. */
export type AuthorityFeeType = "late_fee" | "bounce_charge" | "settlement" | "restructuring";

/** talk.py :: packet — what a specialist needs if this leaves the call. */
export interface AuthorityPacket {
  feeType: string;
  askedAmount: number | null;
  verdict: string;
  approvedAmount: number | null;
  capAmount: number | null;
  reason: string | null;
  reasonCodes: string[];
  talkTrack: string;
  customerId: string | null;
}

/** Mirrors engine.py :: AuthorityResult.to_payload(). */
export interface AuthorityNext {
  verdict: AuthorityVerdict;
  approvedAmount: number | null;
  capAmount: number | null;
  reason: string | null;
  reasonCodes: string[];
  talkTrack: string;
  feeType: string;
  askedAmount: number | null;
  decisionId: string | null;
  /** off | shadow | live. Only `live` may post. */
  mode: string;
  suppressed: boolean;
  actionable: boolean;
  packet: AuthorityPacket | null;
  latencyMs: number;
}

export interface AuthorityNextOptions {
  accountId?: string | null;
  feeType?: AuthorityFeeType;
  askedAmount?: number | null;
  interactionId?: string | null;
}

export async function fetchAuthorityNext(
  customerId: string,
  opts: AuthorityNextOptions & { signal?: AbortSignal } = {},
): Promise<AuthorityNext> {
  const feeType = opts.feeType ?? "late_fee";
  const askedAmount = opts.askedAmount ?? null;
  const params = new URLSearchParams({ customerId, feeType });
  if (opts.accountId) params.set("accountId", opts.accountId);
  if (askedAmount !== null) params.set("askedAmount", String(askedAmount));
  if (opts.interactionId) params.set("interactionId", opts.interactionId);
  return apiGet<AuthorityNext>(`/authority/next?${params.toString()}`, { signal: opts.signal });
}

/**
 * The allowed move for this account, from the engine that owns the question.
 *
 * No refetch interval and no refetch on focus: every call writes a row into the
 * shadow corpus the rollout decision is read from, so a screen left open must
 * not manufacture decisions nobody asked for.
 */
export function useAuthorityNext(customerId: string | undefined, opts: AuthorityNextOptions = {}) {
  const feeType = opts.feeType ?? "late_fee";
  const askedAmount = opts.askedAmount ?? null;
  const interactionId = opts.interactionId ?? null;
  const accountId = opts.accountId ?? null;
  return useQuery({
    queryKey: ["authority-next", customerId, feeType, askedAmount, interactionId, accountId],
    queryFn: ({ signal }) =>
      fetchAuthorityNext(customerId!, { accountId, feeType, askedAmount, interactionId, signal }),
    enabled: Boolean(customerId),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

/**
 * Server verdict → the one policy shape Floor, Handoff and 360 all render.
 *
 * `enacted` is false by construction: this is a decision that has just been
 * made, not one that has posted. Only /authority/apply makes it true, and the
 * caller re-reads afterwards.
 */
export function authorityPolicyFromNext(next: AuthorityNext, customerId?: string): AuthorityPolicy {
  return {
    ...emptyAuthorityPolicy(),
    status: authorityStatusFor({ verdict: next.verdict, mode: next.mode }),
    decisionId: next.decisionId ?? null,
    customerId: customerId ?? next.packet?.customerId ?? null,
    mode: next.mode ?? null,
    feeType: next.feeType ?? null,
    askedAmount: next.askedAmount ?? null,
    verdict: next.verdict ?? null,
    approvedAmount: next.approvedAmount ?? null,
    capAmount: next.capAmount ?? null,
    reason: next.reason ?? null,
    reasonLabel: authorityReasonLabel(next.reason),
    reasonCodes: next.reasonCodes ?? [],
    talkTrack: next.talkTrack || null,
    enacted: false,
  };
}

export async function applyAuthority(input: {
  decisionId: string;
  amount?: number | null;
  disputeId?: string | null;
}): Promise<{ ledgerId: string; disputeId?: string | null; amount: number }> {
  return apiPost("/authority/apply", {
    decisionId: input.decisionId,
    amount: input.amount ?? undefined,
    disputeId: input.disputeId ?? undefined,
  });
}
