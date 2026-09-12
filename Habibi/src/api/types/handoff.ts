/**
 * Domain / wire types for the handoff surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
 */

export type Speaker = "customer" | "agent" | "bot" | "system";
export type TranscriptTurn = {
  id: string;
  /** Plain `str` on HandoffTranscriptTurn; `Speaker` names the four the cockpit styles. */
  speaker: Speaker | (string & {});
  text: string;
  /** Absolute second offset from call start when this line appears. */
  at: number;
  /** Sentiment delta this turn contributes (-1..+1). */
  sentimentDelta?: number | null;
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
