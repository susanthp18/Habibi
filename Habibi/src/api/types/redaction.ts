/**
 * Domain / wire types for the redaction surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
 */

export type PiiEntityType =
  | "card"
  | "pan"
  | "phone"
  | "email"
  | "address"
  | "dob"
  | "account"
  | "ifsc"
  | "aadhaar"
  | "pincode"
  | "name"
  | "upi"
  | "passport"
  | "voter_id"
  | "driving_licence"
  | "secret"
  | "custom";
export interface PiiFinding {
  id: string;
  turnId: string;
  type: PiiEntityType;
  start: number; // char offset in turn.text
  end: number;
  text: string;
  masked: string;
  confidence: number; // 0..1
  source: "auto" | "manual";
  accepted: boolean;
  /** Low confidence: masked, and waiting for a reviewer to confirm. */
  needsReview?: boolean;
  /** pattern | context | crm | model | custom:<rule> */
  detector?: string;
  /** The model that found it, when a model did (repo@revision). */
  modelVersion?: string | null;
}
export interface RedactionTurn {
  id: string;
  t: number;
  speaker: "bot" | "agent" | "customer" | "system";
  text: string;
  /** The turn as plain runs and finding spans (record detail only). */
  segments?: { text: string; findingId?: string }[];
}
export interface AudioSegment {
  atSec: number;
  durSec: number;
  type: PiiEntityType;
  findingId: string;
  muted: boolean;
  /** Whose channel is beeped. */
  channel?: "customer" | "agent" | null;
  /** False when the words could not be timed exactly and a wider stretch is beeped. */
  aligned?: boolean;
}
export interface RedactionRecord {
  id: string;
  callId: string;
  customer: string;
  customerId: string;
  channel: "voice" | "whatsapp" | "sms";
  handler: string;
  occurredAt: string;
  durationSec: number;
  transcript: RedactionTurn[];
  findings: PiiFinding[];
  audioSegments: AudioSegment[];
  reviewed: boolean;
  /** Detail only: the transcript shows the words as spoken (raw-PII viewers). */
  rawVisible?: boolean;
  /** The call-intelligence pass: queued | running | done | failed. */
  processing?: string | null;
}
export type ExportFormat = "pdf" | "csv" | "audio-zip";
export type ExportScope = "transcript" | "audio" | "metadata";
export interface ExportJob {
  id: string;
  at: string;
  actor: string;
  actorRole: string;
  recordIds: string[];
  format: ExportFormat;
  scope: ExportScope[];
  watermark: string;
  status: "queued" | "running" | "ready" | "failed";
  downloadCount: number;
  entitiesRedacted: number;
  kind?: "redaction" | "dashboard";
  mailStatus?: string | null;
  /** Why a failed export could not be built. */
  error?: string | null;
}
export interface RuleConfig {
  enabled: boolean;
  replacement: string;
  label: string;
}
export type RedactionRules = Record<PiiEntityType, RuleConfig>;
export interface RecordFilter {
  q: string;
  channel: "all" | "voice" | "whatsapp" | "sms";
  hasPiiOnly: boolean;
}
