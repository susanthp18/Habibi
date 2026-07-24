// -----------------------------------------------------------------------------
// Handoff Hub — data access seam (initial session snapshot).
//   fetchHandoffSession() → the escalated-call snapshot at handoff time
//
// NOTE: transcript / sentiment / compliance ticks are simulated client-side
// only when USE_MOCK is true. Live mode shows the snapshot from GET /handoff/active
// without script replay (Phase 4 will stream turns over WebSocket).
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import {
  activeCall,
  complianceItems,
  customerContext,
  dispositions,
  suggestions,
  transcriptScript,
  type ComplianceItem,
  type Suggestion,
  type TranscriptTurn,
} from "@/data/handoff-seed";
import { apiGet, mockDelay, USE_MOCK } from "./config";

export type ActiveCall = typeof activeCall;
export type CustomerContext = typeof customerContext;

export type HandoffSession = {
  activeCall: ActiveCall;
  customerContext: CustomerContext;
  transcriptScript: TranscriptTurn[];
  suggestions: Suggestion[];
  complianceItems: ComplianceItem[];
  dispositions: string[];
};

export async function fetchHandoffSession(): Promise<HandoffSession> {
  const snapshot: HandoffSession = {
    activeCall,
    customerContext,
    transcriptScript,
    suggestions,
    complianceItems,
    dispositions,
  };
  if (USE_MOCK) return mockDelay(snapshot);
  return apiGet<HandoffSession>("/handoff/active");
}

export function useHandoffSession() {
  return useQuery({
    queryKey: ["handoff", "active"],
    queryFn: fetchHandoffSession,
    staleTime: Infinity,
  });
}
