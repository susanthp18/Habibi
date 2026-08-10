// -----------------------------------------------------------------------------
// Per-call cost — what one interaction actually spent, by service and model.
//
// Until the voice pipeline was instrumented, the only cost figure anywhere in
// the product was total spend / resolved calls: an allocation, not a
// measurement. This reads usage events attributed to a single interaction.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import { apiGet, USE_MOCK } from "./config";

export type CallCostLine = {
  serviceId: string;
  serviceName: string;
  unit: string;
  category: string;
  color: string;
  /** Deployment for LLM, neural voice for TTS, locale for STT. */
  model: string | null;
  units: number;
  costInr: number;
  events: number;
};

export type CallCost = {
  interactionId: string;
  /**
   * False when the call carries no usage events at all — i.e. it predates
   * pipeline metering. Render this as "not metered", never as ₹0.00: a real
   * zero and an unmeasured call are different claims.
   */
  attributed: boolean;
  totalInr: number;
  lines: CallCostLine[];
  durationSec: number;
  channel: string | null;
  status: string | null;
  totalTokens: number;
};

export function fetchCallCost(interactionId: string): Promise<CallCost> {
  return apiGet<CallCost>(`/interactions/${encodeURIComponent(interactionId)}/cost`);
}

export function useCallCost(interactionId: string | null | undefined) {
  return useQuery({
    queryKey: ["call-cost", interactionId],
    queryFn: () => fetchCallCost(interactionId as string),
    enabled: Boolean(interactionId) && !USE_MOCK,
    staleTime: 30_000,
  });
}
