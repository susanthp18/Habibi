/**
 * Domain / wire types for the disputes surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
 */

import type { DisputeSla } from "./dispute-sla";

export type { SlaTone } from "./dispute-sla";

export type DisputeStatus = "new" | "under_review" | "awaiting_customer" | "resolved" | "rejected";
export type DisputeType =
  "paid_already" | "wrong_amount" | "not_my_account" | "fee_waiver" | "duplicate_charge" | "fraud";
export type DisputeSource = "bot_voice" | "bot_chat" | "agent";
export type DisputePriority = "low" | "normal" | "high" | "urgent";
export type ResolutionCode =
  | "valid_waive_fee"
  | "valid_reverse_charge"
  | "invalid_no_action"
  | "duplicate"
  | "needs_more_info";
export interface DisputeEvent {
  at: string;
  label: string;
  actor?: string;
  tone?: "info" | "success" | "warn" | "danger";
}
export interface Evidence {
  id: string;
  name: string;
  kind: "screenshot" | "receipt" | "statement" | "audio" | "other";
  uploadedAt: string;
  uploadedBy: string;
}
/** What the store holds: the dispute itself, with no SLA rendering on it. */
export interface DisputeRecord {
  id: string;
  customerId: string;
  customerName: string;
  accountId: string;
  accountTail: string;
  type: DisputeType;
  disputedAmount: number;
  source: DisputeSource;
  transcriptSnippet: string;
  originConversationId?: string;
  capturedAt: string;
  slaDueAt: string;
  status: DisputeStatus;
  assignee: string;
  priority: DisputePriority;
  evidence: Evidence[];
  events: DisputeEvent[];
  resolutionCode?: ResolutionCode;
  resolutionNotes?: string;
}
/**
 * What a screen gets: the record plus the SLA the server computed for it.
 * The board never derives the chip from slaDueAt — see api/types/dispute-sla.ts.
 */
export type Dispute = DisputeRecord & DisputeSla;
// ---- DisputeFilters ----
export interface DisputeFilters {
  search: string;
  types: DisputeType[]; // empty = all
  sources: DisputeSource[]; // empty = all
  assignee: "all" | (string & {});
  sla: "all" | "at_risk" | "breached";
  amount: "any" | "lt5" | "5to25" | "gt25";
  myQueue: boolean;
}
