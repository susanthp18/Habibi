// -----------------------------------------------------------------------------
// Upsell, end to end: what customers said, what the offer engine decided, and
// whether it was sent and answered.
//
//   GET  /offers/decisions               → the offer log
//   GET  /offers/decisions/{id}          → one offer, end to end
//   GET  /offers/opportunities           → a customer's signals + latest offer
//   GET  /offers/signals/health          → what the signal sweep read and skipped
//   POST /offers/signals/{id}/feedback   → mark a detected signal right or wrong
// -----------------------------------------------------------------------------

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost } from "./config";

export type CustomerSignal = {
  id: string;
  code: string;
  label: string;
  productHint: string | null;
  horizon: string | null;
  confidence: number;
  channel: string;
  interactionId: string;
  createdAt: string;
  feedback: "right" | "wrong" | null;
  /** The customer's own words, masked. */
  evidence: string | null;
};

export type OfferTrace = {
  id: string;
  family: "offer";
  customerId: string;
  customerName: string | null;
  createdAt: string;
  mode: string;
  context: string;
  signals: CustomerSignal[];
  choice: {
    productId: string | null;
    name: string | null;
    suggestedAmount: number | null;
    score: number | null;
    held: boolean;
    holdReason: string | null;
    holdReasonText: string | null;
    pickProbability: number | null;
  };
  options: Array<{
    productId: string;
    name: string;
    status: "scored" | "blocked";
    chosen: boolean;
    score?: number | null;
    explanation?: string | null;
    reasonCodes?: string[];
    reason?: string;
    code?: string;
  }>;
  suitability: Array<{
    product_id: string;
    verdict: string;
    assessor: string;
    assessed_at: string;
    expires_at: string | null;
    evidence_ref: string;
  }>;
  delivery: {
    presented: boolean;
    presentedAt: string | null;
    response: string | null;
    respondedAt: string | null;
    messages: Array<{ id: string; status: string; template_name: string | null; created_at: string }>;
    leads: Array<{ id: string; stage: string; owner_user_id: string | null; created_at: string }>;
  };
  versions: Record<string, string | number | null>;
};

export type OfferLogRow = {
  id: string;
  created_at: string;
  customer_id: string;
  customer_name: string | null;
  mode: string;
  chosen_product_id: string | null;
  product_name: string | null;
  score: number | null;
  suppression_reason: string | null;
  holdReasonText: string | null;
  presented: boolean;
  response: string | null;
  context: string | null;
  signals: number;
};

export type SignalHealth = {
  scans: Array<{ status: string; skip_reason: string | null; skipText: string | null; n: number }>;
  codes: Array<{ signal_code: string; label: string; found: number; right: number; wrong: number }>;
};

export function useOfferLog(customerId?: string | null) {
  return useQuery({
    queryKey: ["offer-log", customerId ?? null],
    queryFn: () => {
      const p = new URLSearchParams({ limit: "100" });
      if (customerId) p.set("customerId", customerId);
      return apiGet<OfferLogRow[]>(`/offers/decisions?${p.toString()}`);
    },
    staleTime: 30_000,
  });
}

export function useOfferTrace(decisionId: string | null | undefined) {
  return useQuery({
    queryKey: ["offer-trace", decisionId],
    queryFn: () => apiGet<OfferTrace>(`/offers/decisions/${encodeURIComponent(decisionId!)}`),
    enabled: Boolean(decisionId),
  });
}

export function useOpportunities(customerId: string | null | undefined) {
  return useQuery({
    queryKey: ["offer-opportunities", customerId],
    queryFn: () =>
      apiGet<{ signals: CustomerSignal[]; decision: OfferTrace | null }>(
        `/offers/opportunities?customerId=${encodeURIComponent(customerId!)}`,
      ),
    enabled: Boolean(customerId),
  });
}

export function useSignalHealth() {
  return useQuery({
    queryKey: ["offer-signal-health"],
    queryFn: () => apiGet<SignalHealth>("/offers/signals/health"),
    staleTime: 60_000,
  });
}

export function useSignalFeedback() {
  const qc = useQueryClient();
  return useMutation({
    meta: { errors: "caller" },
    mutationFn: (input: { signalId: string; verdict: "right" | "wrong" }) =>
      apiPost(`/offers/signals/${encodeURIComponent(input.signalId)}/feedback`, { verdict: input.verdict }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["offer-opportunities"] });
      void qc.invalidateQueries({ queryKey: ["offer-signal-health"] });
      void qc.invalidateQueries({ queryKey: ["offer-trace"] });
    },
  });
}
