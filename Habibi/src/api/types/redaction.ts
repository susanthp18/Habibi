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
}
export interface RedactionTurn {
  id: string;
  t: number;
  speaker: "bot" | "agent" | "customer" | "system";
  text: string;
}
export interface AudioSegment {
  atSec: number;
  durSec: number;
  type: PiiEntityType;
  findingId: string;
  muted: boolean;
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
  status: "queued" | "ready" | "failed";
  downloadCount: number;
  entitiesRedacted: number;
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
