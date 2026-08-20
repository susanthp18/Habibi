export type OfferPolicyStatus =
  | "none"
  | "suppressed"
  | "shadow"
  | "ready"
  | "presented"
  | "interested"
  | "declined"
  | "open_lead";

export type OfferPolicy = {
  status: OfferPolicyStatus;
  decisionId?: string | null;
  customerId?: string | null;
  interactionId?: string | null;
  mode?: string | null;
  channel?: string | null;
  suppressionReason?: string | null;
  suppressionLabel?: string | null;
  productId?: string | null;
  productName?: string | null;
  suggestedAmount?: number | null;
  talkTrack?: string | null;
  reasonCodes?: string[];
  score?: number | null;
  presented?: boolean;
  response?: string | null;
  leadId?: string | null;
  leadStage?: string | null;
  preferredWindow?: string | null;
  createdAt?: string | null;
};

export const OFFER_STATUS_LABEL: Record<OfferPolicyStatus, string> = {
  none: "Quiet",
  suppressed: "Suppressed",
  shadow: "Shadow",
  ready: "Ready",
  presented: "Presented",
  interested: "Interested",
  declined: "Declined",
  open_lead: "Open lead",
};

export type OfferChipTone = "neutral" | "success" | "warning" | "danger" | "discovery" | "selected";

export const OFFER_STATUS_TONE: Record<OfferPolicyStatus, OfferChipTone> = {
  none: "neutral",
  suppressed: "danger",
  shadow: "discovery",
  ready: "selected",
  presented: "warning",
  interested: "success",
  declined: "neutral",
  open_lead: "success",
};

export function emptyOfferPolicy(): OfferPolicy {
  return { status: "none", reasonCodes: [] };
}

export function fmtOfferAmount(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "";
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
}
