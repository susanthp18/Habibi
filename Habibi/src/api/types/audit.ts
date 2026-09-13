/**
 * Domain / wire types for the audit surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
 *
 * Nullability follows `CallResponse` in `backend/schemas.py`.
 */

export type AuditChannel = "voice" | "whatsapp" | "sms";
export type Direction = "inbound" | "outbound";
export type HandlerKind = "bot" | "human" | "handoff";
export type Speaker = "bot" | "agent" | "customer" | "system";
export type SentimentBucket = "positive" | "neutral" | "negative";
export type Disposition =
  | "PTP Captured"
  | "Payment Made"
  | "Info Query Resolved"
  | "Dispute Raised"
  | "Callback Scheduled"
  | "Escalated"
  | "No Answer"
  | "Voicemail"
  | "DND — Not Contacted";
export type CallFlag =
  "compliance-miss" | "sentiment-drop" | "escalation" | "silence" | "abuse-detected" | "high-value";
export interface DisclosureCheck {
  id: string;
  label: string;
  read: boolean;
  atSec?: number;
}
export interface TranscriptTurn {
  id: string;
  t: number; // seconds from call start
  speaker: Speaker;
  text: string;
}
export interface SentimentPoint {
  t: number; // seconds
  v: number; // -1..+1
}
/** Mirrors `CallResponse` — several fields are `None` on the wire. */
export interface CallRecord {
  id: string;
  startedAt: string | null;
  duration: number; // seconds
  channel: AuditChannel;
  direction: Direction | null;
  handledBy: { kind: HandlerKind; agent?: string; bot?: string };
  customerId: string;
  customerName: string;
  phoneMasked: string;
  accountId: string | null;
  disposition: Disposition | null;
  summary: string | null;
  tags: string[];
  flags: CallFlag[];
  avgSentiment: number | null;
  sentimentSeries: SentimentPoint[];
  disclosures: DisclosureCheck[];
  transcript: TranscriptTurn[];
  redactionApplied: boolean;
  hash: string | null;
  ragHits: number;
  latencyMs: number | null;
  routing: string[];
}
export type DateRange = "today" | "7d" | "30d" | "all";
export interface AuditFilterState {
  q: string;
  dateRange: DateRange;
  channel: "all" | AuditChannel;
  handler: "all" | HandlerKind;
  agent: "all" | (string & {});
  disposition: "all" | Disposition;
  sentiment: "all" | SentimentBucket;
  flaggedOnly: boolean;
}
