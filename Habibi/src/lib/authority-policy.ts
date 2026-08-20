import { fmtOfferAmount } from "@/lib/offer-policy";

export type AuthorityPolicyStatus =
  | "none"
  | "escalate"
  | "shadow"
  | "cap"
  | "auto_approve"
  | "applied";

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

export type AuthorityChipTone = "neutral" | "success" | "warning" | "danger" | "discovery" | "selected";

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

export const fmtAuthorityAmount = fmtOfferAmount;

export function canApplyAuthority(policy?: AuthorityPolicy | null): boolean {
  if (!policy || policy.enacted) return false;
  if ((policy.mode || "").toLowerCase() !== "live") return false;
  return policy.status === "auto_approve" || policy.status === "cap";
}
