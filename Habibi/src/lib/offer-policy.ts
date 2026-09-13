import { z } from "zod";
import { inr } from "@/lib/format";

export type OfferPolicyStatus =
  | "none"
  | "suppressed"
  | "shadow"
  | "ready"
  | "presented"
  | "interested"
  | "declined"
  | "open_lead";

/** OfferPolicyResponse (backend/schemas.py) — nested in insights, handoff and floor payloads. */
export const offerPolicySchema = z.object({
  status: z.enum([
    "none",
    "suppressed",
    "shadow",
    "ready",
    "presented",
    "interested",
    "declined",
    "open_lead",
  ]),
  decisionId: z.string().nullable(),
  customerId: z.string().nullable(),
  interactionId: z.string().nullable(),
  mode: z.string().nullable(),
  channel: z.string().nullable(),
  suppressionReason: z.string().nullable(),
  suppressionLabel: z.string().nullable(),
  productId: z.string().nullable(),
  productName: z.string().nullable(),
  suggestedAmount: z.number().nullable(),
  talkTrack: z.string().nullable(),
  reasonCodes: z.array(z.string()),
  score: z.number().nullable(),
  presented: z.boolean(),
  response: z.string().nullable(),
  leadId: z.string().nullable(),
  leadStage: z.string().nullable(),
  preferredWindow: z.string().nullable(),
  createdAt: z.string().nullable(),
});

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
  return inr(n);
}
