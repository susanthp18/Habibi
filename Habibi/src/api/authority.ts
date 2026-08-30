// -----------------------------------------------------------------------------
// Live authority matrix — "what may close on this call, in rupees".
//   GET  /authority/next   (backend/main.py :: authority_next)
//   POST /authority/apply  (live mode only)
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

import { getCustomer, type Customer } from "@/data/customer360-seed";
import {
  authorityReasonLabel,
  authorityStatusFor,
  emptyAuthorityPolicy,
  type AuthorityPolicy,
} from "@/lib/authority-policy";
import { apiGet, apiPost, mockDelay, USE_MOCK } from "./config";

/** matrix.py :: VERDICTS. */
export type AuthorityVerdict = "auto_approve" | "cap_inr" | "escalate";

/** features.py :: FEE_TYPES. */
export type AuthorityFeeType = "late_fee" | "bounce_charge" | "settlement" | "restructuring";

const FEE_TYPES: readonly AuthorityFeeType[] = [
  "late_fee",
  "bounce_charge",
  "settlement",
  "restructuring",
];

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
  if (USE_MOCK) {
    return mockDelay(mockAuthorityNext(customerId, { feeType, askedAmount }));
  }
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
  if (USE_MOCK) {
    throw new Error("Live goodwill apply is not available in mock mode");
  }
  return apiPost("/authority/apply", {
    decisionId: input.decisionId,
    amount: input.amount ?? undefined,
    disputeId: input.disputeId ?? undefined,
  });
}

// -----------------------------------------------------------------------------
// EMULATION — mock/demo only. A port of the Python authority matrix, not an
// approximation, for the same reason api/contact-policy.ts ports the contact
// veto: a mock that teaches a policy the backend does not hold is worse than no
// mock at all. Ported here:
//
//   * config.py — every threshold, with its default AND its env override, so a
//     demo can be tuned the way the deployment is (VITE_ prefix; Vite only
//     exposes those to the client).
//   * matrix.py :: decide() — the ladder in its exact order, with all of its
//     reason codes, and late_fee_cap_for()'s min against the posted fee.
//   * talk.py — talk_track() and escalate_line(), word for word.
//   * engine.py — mode gate, the escalate-shaped failure path, and the
//     suppressed/actionable flags of to_payload().
//
// NOT emulated, and absent rather than invented: treatment holds and the
// identity check. The seed has no equivalent of treatment_holds or a KYC step,
// so `hold:*` and `identity_not_verified` never fire here — they do on the
// server, and the matrix checks them before everything below. The mock also
// carries no decisionId: nothing was recorded, so nothing can be applied.
// -----------------------------------------------------------------------------

/** features.py :: SILENCING_HOLDS. Kept for fidelity — the seed carries none. */
const SILENCING_HOLDS = ["hardship", "complaint", "bereavement", "legal"];

const MODE_OFF = "off";
const MODE_SHADOW = "shadow";
const MODE_LIVE = "live";
const MODES = [MODE_OFF, MODE_SHADOW, MODE_LIVE];

/** Read statically — Vite only inlines literal `import.meta.env.X` accesses. */
const AUTHORITY_ENV = {
  mode: import.meta.env.VITE_AUTHORITY_MODE as string | undefined,
  lateFeeCap: import.meta.env.VITE_AUTHORITY_LATE_FEE_CAP as string | undefined,
  lateFeeMidCap: import.meta.env.VITE_AUTHORITY_LATE_FEE_MID_CAP as string | undefined,
  maxOutstanding: import.meta.env.VITE_AUTHORITY_LATE_FEE_MAX_OUTSTANDING as string | undefined,
  lateFeeMaxDpd: import.meta.env.VITE_AUTHORITY_LATE_FEE_MAX_DPD as string | undefined,
  minTenureMonths: import.meta.env.VITE_AUTHORITY_MIN_TENURE_MONTHS as string | undefined,
};

function envNumber(raw: string | undefined, fallback: number, integer = false): number {
  const parsed = Number(String(raw ?? "").trim());
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0, integer ? Math.trunc(parsed) : parsed);
}

/** config.py :: mode — an unrecognised value degrades to shadow, never to off. */
function mockMode(): string {
  const raw = (AUTHORITY_ENV.mode ?? MODE_SHADOW).trim().toLowerCase();
  return MODES.includes(raw) ? raw : MODE_SHADOW;
}

const mockLateFeeCap = () => envNumber(AUTHORITY_ENV.lateFeeCap, 500);
const mockLateFeeMidCap = () => envNumber(AUTHORITY_ENV.lateFeeMidCap, 250);
const mockLateFeeMaxOutstanding = () => envNumber(AUTHORITY_ENV.maxOutstanding, 100_000);
const mockLateFeeMaxDpd = () => envNumber(AUTHORITY_ENV.lateFeeMaxDpd, 61, true);
const mockMinTenureMonths = () => envNumber(AUTHORITY_ENV.minTenureMonths, 6, true);

/** features.py :: AccountAuthority — unknown facts are null, never zero. */
interface MockAuthorityFeatures {
  accountId: string | null;
  dpd: number | null;
  outstanding: number | null;
  tenureMonths: number | null;
  postedLateFee: number | null;
  goodwillCount12m: number;
  holds: string[];
  identityVerified: boolean;
}

const DAY_MS = 86_400_000;

/** SqlFeatureProvider.build(), read off the seed instead of Postgres. */
function mockFeatures(customer: Customer, at: number): MockAuthorityFeatures {
  const since = at - 365 * DAY_MS;
  const recent = customer.ledger.filter((entry) => {
    const posted = Date.parse(entry.date);
    return Number.isFinite(posted) && posted >= since;
  });

  // ledger_entries: fees posted in the last 12 months, positive only.
  const postedFee = recent
    .filter((entry) => entry.type === "fee" && entry.amount > 0)
    .reduce((sum, entry) => sum + entry.amount, 0);

  // Waivers are stored signed; the provider counts them and sums their size.
  const waivers = recent.filter((entry) => entry.type === "waiver");

  const opened = Date.parse(customer.account.openedOn);
  const tenureMonths = Number.isFinite(opened)
    ? Math.max(0, Math.floor((at - opened) / DAY_MS / 30))
    : null;

  return {
    accountId: customer.accountId ?? null,
    dpd: typeof customer.account.dpd === "number" ? customer.account.dpd : null,
    outstanding: typeof customer.outstanding === "number" ? customer.outstanding : null,
    tenureMonths,
    // The provider treats a zero fee total as "we do not know", not as zero.
    postedLateFee: postedFee > 0 ? postedFee : null,
    goodwillCount12m: waivers.length,
    holds: [],
    identityVerified: true,
  };
}

interface MockDecision {
  verdict: AuthorityVerdict;
  approvedAmount: number | null;
  capAmount: number | null;
  reason: string;
  reasonCodes: string[];
}

/** matrix.py :: _round_inr — whole rupees. */
function roundInr(value: number): number {
  return Math.max(0, Math.round(value));
}

function escalate(reason: string, extra: string[] = [], cap: number | null = null): MockDecision {
  return {
    verdict: "escalate",
    approvedAmount: null,
    capAmount: cap,
    reason,
    reasonCodes: [reason, ...extra],
  };
}

/** matrix.py :: late_fee_cap_for — null when live goodwill is forbidden. */
function mockLateFeeCapFor(features: MockAuthorityFeatures): number | null {
  const dpd = features.dpd;
  if (dpd === null) return null;
  if (dpd >= mockLateFeeMaxDpd()) return null;
  let cap = dpd <= 30 ? mockLateFeeCap() : mockLateFeeMidCap();
  const posted = features.postedLateFee;
  if (posted !== null) cap = Math.min(cap, Math.max(0, posted));
  return roundInr(cap);
}

/** matrix.py :: decide — the whole ladder, in order. */
function mockDecide(
  features: MockAuthorityFeatures,
  feeType: string,
  askedAmount: number | null,
): MockDecision {
  const kind = ((feeType || "").trim().toLowerCase() || "late_fee") as AuthorityFeeType;
  if (!FEE_TYPES.includes(kind)) return escalate("unknown_fee_type");

  if (!features.identityVerified) return escalate("identity_not_verified");

  for (const hold of features.holds) {
    if (SILENCING_HOLDS.includes(hold)) return escalate(`hold:${hold}`);
  }

  if (kind === "settlement") return escalate("settlement_live_forbidden");
  if (kind === "restructuring") return escalate("restructure_live_forbidden");
  if (kind === "bounce_charge") return escalate("bounce_reversal_live_forbidden");

  // late_fee from here.
  if (features.goodwillCount12m > 0) return escalate("prior_goodwill_12m");
  if (features.dpd === null) return escalate("dpd_unknown");
  if (features.dpd >= mockLateFeeMaxDpd()) return escalate("dpd_too_high");
  if (features.outstanding !== null && features.outstanding > mockLateFeeMaxOutstanding()) {
    return escalate("outstanding_too_high");
  }
  if (features.tenureMonths !== null && features.tenureMonths < mockMinTenureMonths()) {
    return escalate("tenure_too_short");
  }

  const cap = mockLateFeeCapFor(features);
  if (cap === null) return escalate("dpd_too_high");
  if (cap <= 0) return escalate("nothing_to_waive", [], 0);

  let asked = askedAmount === null || !Number.isFinite(askedAmount) ? null : Number(askedAmount);
  if (asked !== null && asked < 0) asked = null;

  if (asked === null) {
    return {
      verdict: "cap_inr",
      approvedAmount: cap,
      capAmount: cap,
      reason: "cap_available",
      reasonCodes: ["cap_available"],
    };
  }
  if (asked <= cap) {
    return {
      verdict: "auto_approve",
      approvedAmount: Math.min(asked > 0 ? roundInr(asked) : cap, cap),
      capAmount: cap,
      reason: "within_cap",
      reasonCodes: ["within_cap"],
    };
  }
  // Asked above the cap: the allowed move is still the cap, and the agent must
  // not quote a larger number.
  return {
    verdict: "cap_inr",
    approvedAmount: cap,
    capAmount: cap,
    reason: "asked_above_cap",
    reasonCodes: ["asked_above_cap", "cap_available"],
  };
}

function inr(amount: number | null): string {
  if (amount === null) return "";
  return `₹${Math.round(amount).toLocaleString("en-IN")}`;
}

/** talk.py :: escalate_line. */
function mockEscalateLine(reason: string | null, feeType: string): string {
  if (reason === "settlement_live_forbidden") {
    return (
      "Do not quote a settlement percentage. Warm-transfer to a specialist " +
      "with the transcript and the amount they asked for."
    );
  }
  if (reason === "restructure_live_forbidden") {
    return (
      "Restructuring needs a documented review. Log interest and warm-transfer. " +
      "Do not approve a plan or quote terms on this call."
    );
  }
  if (reason === "bounce_reversal_live_forbidden") {
    return (
      "Do not promise bounce-charge reversal on this call. Log a dispute " +
      "and offer a specialist callback."
    );
  }
  if (reason === "prior_goodwill_12m") {
    return (
      "A goodwill waiver already posted in the last 12 months. Escalate — " +
      "do not offer another reversal on this call."
    );
  }
  if (reason === "dpd_too_high") {
    return (
      "Out of policy for live goodwill — DPD is too high. Transfer; " +
      "do not quote a waiver amount."
    );
  }
  if (reason === "tenure_too_short") {
    return "Tenure is too short for live goodwill. Escalate without quoting a figure.";
  }
  if (reason === "identity_not_verified") {
    return "Identity is not verified. Do not discuss fees or quote any amount.";
  }
  if (reason?.startsWith("hold:")) {
    const kind = reason.slice("hold:".length);
    return `A ${kind} hold is on this account. Do not pitch a waiver. Warm-transfer with the packet.`;
  }
  if (feeType === "settlement") return "Do not quote a settlement percentage. Warm-transfer.";
  return (
    "Out of policy for live goodwill. Escalate to a specialist with the " +
    "transcript, the asked amount, and this reason. Do not quote a figure."
  );
}

/** talk.py :: talk_track. Figures come only from the decision. */
function mockTalkTrack(decision: MockDecision, feeType: string): string {
  if (decision.verdict === "auto_approve" && decision.approvedAmount !== null) {
    return (
      `You may reverse ${inr(decision.approvedAmount)} late fee on this call. ` +
      "Do not offer more. Call apply_goodwill with that amount."
    );
  }
  if (decision.verdict === "cap_inr" && decision.approvedAmount !== null) {
    const extra =
      decision.reason === "asked_above_cap"
        ? " They asked for more than the ceiling — do not quote a larger figure."
        : "";
    return (
      `Goodwill ceiling is ${inr(decision.approvedAmount)}. ` +
      "You may reverse up to that. If they insist on more, escalate without quoting a larger number." +
      extra
    );
  }
  return mockEscalateLine(decision.reason, feeType);
}

/** engine.py :: AuthorityResult.to_payload, for a decision that was never recorded. */
function mockPayload(
  decision: MockDecision,
  opts: { feeType: string; askedAmount: number | null; mode: string; customerId: string },
): AuthorityNext {
  const talkTrack = mockTalkTrack(decision, opts.feeType);
  const suppressed = opts.mode !== MODE_LIVE || decision.verdict === "escalate";
  return {
    verdict: decision.verdict,
    approvedAmount: decision.approvedAmount,
    capAmount: decision.capAmount,
    reason: decision.reason,
    reasonCodes: decision.reasonCodes,
    talkTrack,
    feeType: opts.feeType,
    askedAmount: opts.askedAmount,
    // Nothing was written, so there is nothing to apply. The Apply control is
    // hidden rather than offered and then refused.
    decisionId: null,
    mode: opts.mode,
    suppressed,
    actionable: !suppressed && decision.approvedAmount !== null,
    packet: {
      feeType: opts.feeType,
      askedAmount: opts.askedAmount,
      verdict: decision.verdict,
      approvedAmount: decision.approvedAmount,
      capAmount: decision.capAmount,
      reason: decision.reason,
      reasonCodes: decision.reasonCodes,
      talkTrack,
      customerId: opts.customerId,
    },
    latencyMs: 0,
  };
}

/**
 * engine.py :: recommend_authority, against the seed. Exported and time-
 * injectable so the ladder can be exercised without waiting a year for a
 * goodwill waiver to age out.
 */
export function mockAuthorityNext(
  customerId: string,
  opts: { feeType?: string; askedAmount?: number | null; at?: number } = {},
): AuthorityNext {
  const feeType = (opts.feeType || "late_fee").trim().toLowerCase() || "late_fee";
  const askedAmount = opts.askedAmount ?? null;
  const mode = mockMode();
  const base = { feeType, askedAmount, mode, customerId };

  if (mode === MODE_OFF) return mockPayload(escalate("engine_off"), base);

  const customer = getCustomer(customerId);
  if (!customer) {
    // The engine never raises: a failure to build features degrades to
    // escalate, logged. Here that is a customer the seed does not hold.
    return mockPayload(escalate("engine_error"), base);
  }

  const features = mockFeatures(customer, opts.at ?? Date.now());
  return mockPayload(mockDecide(features, feeType, askedAmount), base);
}
