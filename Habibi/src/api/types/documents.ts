/**
 * Domain / wire types for the documents surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
 */

export type DocStatus = "requested" | "generating" | "sent" | "failed";
export type DocChannel = "whatsapp" | "email" | "sms";
export type RequestedVia =
  "bot_voice" | "bot_chat" | "agent" | "mcp" | "clerk" | "vision" | "inbox";
export type DocSource = "crm" | "vision" | "clerk" | "mcp";
export type DocType =
  | "account_statement"
  | "no_dues_certificate"
  | "interest_certificate"
  | "foreclosure_letter"
  | "loan_schedule"
  | "payment_receipt"
  | "kyc_letter";
export interface DocEvent {
  at: string;
  label: string;
  actor?: string;
  tone?: "info" | "success" | "warn" | "danger";
}
export interface DocRequest {
  id: string;
  customerId: string;
  customerName: string;
  accountId: string;
  accountTail: string;
  docType: DocType;
  period?: string;
  requestedVia: RequestedVia;
  requestedAt: string;
  deliveryChannel: DocChannel;
  deliveryTarget: string;
  status: DocStatus;
  source?: DocSource;
  templateId: string;
  generatedAt?: string;
  sentAt?: string;
  failedReason?: string;
  sizeKb?: number;
  attempts: number;
  assignee: string;
  events: DocEvent[];
}
export interface Template {
  id: string;
  name: string;
  docType: DocType;
  description: string;
  previewLines: string[];
}
// ---- Aging tone ----
export type AgingTone = "fresh" | "warn" | "stale" | "done";
export interface AgingInfo {
  tone: AgingTone;
  hours: number;
  label: string;
}
// ---- DocumentFilters ----
export interface DocumentFilters {
  search: string;
  docTypes: DocType[]; // empty = all
  channels: DocChannel[];
  vias: RequestedVia[];
  statuses: DocStatus[];
  range: "today" | "7d" | "30d" | "all";
  assignee: string | "all";
}
export interface NewRequestInput {
  customerId: string;
  docType: DocType;
  period?: string;
  channel: DocChannel;
  templateId: string;
}
