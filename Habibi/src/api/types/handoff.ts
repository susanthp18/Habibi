/**
 * Domain / wire types for the handoff surface.
 *
 * Lived in a `data/*-seed.ts` mock factory. Moved here so live `api/`
 * modules do not import their contract from fixtures (WP-048).
 */

export type Speaker = "customer" | "agent" | "bot" | "system";
export type TranscriptTurn = {
  id: string;
  speaker: Speaker;
  text: string;
  /** Absolute second offset from call start when this line appears. */
  at: number;
  /** Sentiment delta this turn contributes (-1..+1). */
  sentimentDelta?: number;
};
export type Suggestion = {
  id: string;
  title: string;
  body: string;
  source: string;
  /** Show after this many seconds. */
  showAfter: number;
};
export type ComplianceItem = {
  id: string;
  label: string;
  required: boolean;
  autoAt?: number; // auto-check at second N (simulated)
};
