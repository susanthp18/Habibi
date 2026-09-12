/**
 * CustomerInsightsResponse -- GET /customers/{id}/insights. The decision
 * engine's reading of one customer; nothing here is derived in the browser.
 */

import type { OfferPolicy } from "@/lib/offer-policy";

export type NbaActionKind =
  | "ptp"
  | "dispute"
  | "statement"
  | "call"
  | "callback"
  | "review"
  | "offer"
  // Spoken by the decision engine. The card used to have its own contact
  // ladder — "DND, so WhatsApp", "outside the window, so schedule a callback",
  // "over 30 DPD, so call" — written twice, once here and once in Python, and
  // kept in step by hand. The engine decides those against the real consent
  // record, the real calling window and the real frequency budget, so they are
  // gone from both copies and these are what it says instead.
  | "message"
  | "mandate"
  | "schedule"
  | "plan"
  | "field"
  | "legal"
  | "wait";

export type InsightBullet = {
  id: string;
  text: string;
  source: string;
  confidence: "high" | "medium" | "low";
};

export type NbaItem = {
  id: string;
  rank: number;
  title: string;
  reason: string;
  action: NbaActionKind;
  priority: "high" | "medium" | "low";
  leadId?: string | null;
  /** Present on the engine's row. A rupee figure a collections head can argue
   *  with, rather than a dimensionless priority nobody can. */
  expectedValueInr?: number | null;
  scheduledAt?: string | null;
  decisionId?: string | null;
  treatmentAction?: string | null;
  source?: string | null;
  /** The engine decided but is not acting — shadow mode. Labelled rather than
   *  hidden, so nobody reads a shadow recommendation as queued work. */
  advisory?: boolean | null;
};

export type BehaviorMetrics = {
  ptpKeepRate: number | null;
  daysSinceContact: number | null;
  openDisputeAmount: number;
  nextEmiAmount: number | null;
  nextEmiDate: string | null;
  paymentStreak: number;
  brokenPromiseCount: number;
  activePromiseAmount: number;
};

export type ActivityPreviewItem = {
  id: string;
  kind: string;
  label: string;
  note?: string | null;
  /** Read off startedAt / createdAt / filedAt / requestedAt server-side — any of which can be null. */
  at: string | null;
  tone?: string | null;
};

/** One ranked action the engine considered but did not pick.
 *  Mirrors agent_core/treatment/scoring.py :: ScoredAction.to_log(). Note the
 *  key is `expectedValue` here and `expectedValueInr` on the chosen action —
 *  the producer spells them differently, so this does too. */
export type TreatmentAlternative = {
  action: string;
  channel?: string | null;
  at?: string | null;
  expectedValue?: number | null;
  pReach?: number | null;
  pResolve?: number | null;
  cost?: number | null;
  reasonCodes?: string[];
  components?: Record<string, number>;
};

/** The engine's full payload, not just the row rendered as an NBA. The excluded
 *  reasons and the ranked alternatives are what a supervisor overriding the
 *  decision needs, and they are already computed server-side.
 *  Mirrors agent_core/treatment/engine.py :: TreatmentResult.to_payload(). */
export type TreatmentSnapshot = {
  action: string;
  actionLabel?: string | null;
  channel?: string | null;
  at?: string | null;
  expectedValueInr?: number | null;
  suppressed?: boolean;
  reason?: string | null;
  reasonText?: string | null;
  rationale?: string;
  decisionId?: string | null;
  propensity?: number | null;
  policyVersion?: number | null;
  mode?: string | null;
  variant?: string | null;
  latencyMs?: number | null;
  alternatives?: TreatmentAlternative[];
  /** action -> veto reason, for the actions arbitration ruled out. */
  excluded?: Record<string, string>;
};

export type CustomerInsights = {
  customerId: string;
  summary: InsightBullet[];
  nba: NbaItem[];
  metrics: BehaviorMetrics;
  activity: ActivityPreviewItem[];
  generatedAt: string;
  offerPolicy?: OfferPolicy | null;
  // No authorityPolicy: the goodwill matrix is policy-as-code the server owns
  // (agent_core/authority); the panel asks GET /authority/next.
  treatment?: TreatmentSnapshot | null;
};
