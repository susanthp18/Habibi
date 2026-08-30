import { fmtOfferAmount } from "@/lib/offer-policy";

export type AuthorityPolicyStatus =
  "none" | "escalate" | "shadow" | "cap" | "auto_approve" | "applied";

export type AuthorityPolicy = {
  status: AuthorityPolicyStatus;
  decisionId?: string | null;
  customerId?: string | null;
  accountId?: string | null;
  interactionId?: string | null;
  mode?: string | null;
  feeType?: string | null;
  askedAmount?: number | null;
  verdict?: string | null;
  approvedAmount?: number | null;
  capAmount?: number | null;
  reason?: string | null;
  reasonLabel?: string | null;
  reasonCodes?: string[];
  talkTrack?: string | null;
  enacted?: boolean;
  disputeId?: string | null;
  createdAt?: string | null;
};

export const AUTHORITY_STATUS_LABEL: Record<AuthorityPolicyStatus, string> = {
  none: "Quiet",
  escalate: "Escalate",
  shadow: "Shadow",
  cap: "Ceiling",
  auto_approve: "In policy",
  applied: "Applied",
};

export type AuthorityChipTone =
  "neutral" | "success" | "warning" | "danger" | "discovery" | "selected";

export const AUTHORITY_STATUS_TONE: Record<AuthorityPolicyStatus, AuthorityChipTone> = {
  none: "neutral",
  escalate: "danger",
  shadow: "discovery",
  cap: "warning",
  auto_approve: "success",
  applied: "selected",
};

export function emptyAuthorityPolicy(): AuthorityPolicy {
  return { status: "none", reasonCodes: [] };
}

/**
 * Operator-facing copy for every reason code the matrix can emit — a port of
 * agent_core/authority/policy.py :: _REASON_LABELS, kept word for word so a rep
 * reading Customer 360 sees the sentence Handoff and Floor already show.
 *
 * The codes themselves are stable, logged and counted server-side; this map
 * only names them. An unrecognised code is still rendered (see
 * `authorityReasonLabel`) rather than swallowed — a reason this build has never
 * heard of is a reason the operator still needs to read.
 */
export const AUTHORITY_REASON_LABEL: Record<string, string> = {
  engine_off: "Authority engine is off",
  engine_error: "Authority engine errored — escalate",
  unknown_fee_type: "Unknown fee type — escalate",
  identity_not_verified: "Identity not verified",
  prior_goodwill_12m: "Goodwill already used in the last 12 months",
  dpd_too_high: "DPD too high for live goodwill",
  dpd_unknown: "DPD unknown — escalate",
  outstanding_too_high: "Ticket too large for live goodwill",
  tenure_too_short: "Tenure too short for live goodwill",
  settlement_live_forbidden: "Do not quote a settlement percentage",
  restructure_live_forbidden: "Restructuring needs a specialist",
  bounce_reversal_live_forbidden: "Do not promise bounce-charge reversal",
  asked_above_cap: "Asked above the goodwill ceiling",
  within_cap: "Asked amount is inside the cap",
  cap_available: "In-policy goodwill ceiling",
  nothing_to_waive: "No late fee on the ledger to reverse",
  "hold:hardship": "Hardship hold — do not pitch a waiver",
  "hold:legal": "Legal hold — do not pitch a waiver",
  "hold:complaint": "Complaint hold — do not pitch a waiver",
  "hold:bereavement": "Bereavement hold — do not pitch a waiver",
};

/** policy.py :: humanize — a known label, a generated hold line, or the raw code. */
export function authorityReasonLabel(reason: string | null | undefined): string | null {
  if (!reason) return null;
  const known = AUTHORITY_REASON_LABEL[reason];
  if (known) return known;
  if (reason.startsWith("hold:")) {
    const kind = reason.slice("hold:".length);
    return `${kind.charAt(0).toUpperCase()}${kind.slice(1)} hold — do not pitch a waiver`;
  }
  return reason.replace(/_/g, " ");
}

/**
 * Verdict + mode → the status this app's chips are keyed on. Mirrors
 * policy.py :: _from_row, including its final `else escalate` — a verdict this
 * build does not recognise is never rendered as an allowed move.
 */
export function authorityStatusFor(input: {
  verdict?: string | null;
  mode?: string | null;
  enacted?: boolean;
}): AuthorityPolicyStatus {
  const verdict = (input.verdict || "").trim().toLowerCase();
  const mode = (input.mode || "").trim().toLowerCase();
  if (input.enacted) return "applied";
  if (verdict === "escalate") return "escalate";
  if (mode === "shadow" && (verdict === "auto_approve" || verdict === "cap_inr")) return "shadow";
  if (verdict === "auto_approve") return "auto_approve";
  if (verdict === "cap_inr") return "cap";
  if (verdict) return "escalate";
  return "none";
}

export const fmtAuthorityAmount = fmtOfferAmount;

export function canApplyAuthority(policy?: AuthorityPolicy | null): boolean {
  if (!policy || policy.enacted) return false;
  if ((policy.mode || "").toLowerCase() !== "live") return false;
  return policy.status === "auto_approve" || policy.status === "cap";
}
