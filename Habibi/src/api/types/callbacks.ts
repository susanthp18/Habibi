/**
 * Domain / wire types for the callbacks surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
 */

export type CbStatus =
  "scheduled" | "reminded" | "in_progress" | "completed" | "missed" | "rescheduled" | "cancelled";
export type CbReason =
  | "payment_discussion"
  | "dispute_followup"
  | "document_query"
  | "hardship_review"
  | "upsell_interest"
  | "general";
export type CbChannel = "whatsapp" | "sms" | "email";
export type CbSource = "bot_voice" | "bot_chat" | "agent";
export type CbPriority = "low" | "normal" | "high" | "urgent";
export type CbDisposition =
  "reached" | "no_answer" | "ptp_captured" | "not_interested" | "callback_again";
export interface CbReminder {
  at: string;
  channel: CbChannel;
  status: "queued" | "sent" | "acknowledged";
}
export interface CbEvent {
  at: string;
  label: string;
  actor?: string;
  tone?: "info" | "success" | "warn" | "danger";
}
export interface Callback {
  id: string;
  customerId: string;
  customerName: string;
  accountId: string;
  accountTail: string;
  reason: CbReason;
  scheduledAt: string; // ISO
  windowMins: 30 | 60 | 120;
  customerTimezone: string;
  preferredWindow: string; // "10:00–19:00 IST"
  /** Permanent DND flag from the customer record (independent of the scheduled slot). */
  customerDnd: boolean;
  dndActive: boolean; // whether the scheduled slot falls in a DND / outside preferred window
  source: CbSource;
  assignee: string;
  queue: string;
  priority: CbPriority;
  status: CbStatus;
  reminders: CbReminder[];
  transcriptSnippet: string;
  originConversationId?: string;
  events: CbEvent[];
  createdAt: string;
  disposition?: CbDisposition;
  outcomeNotes?: string;
}
// ---- CallbackFilters ----
export interface CallbackFilters {
  search: string;
  queue: string | "all";
  assignee: string | "all";
  reasons: CbReason[];
  statuses: CbStatus[];
  channels: CbChannel[];
  dndSafeOnly: boolean;
  myQueueOnly: boolean;
}
export interface CreateInput {
  customerId: string;
  reason: CbReason;
  scheduledAt: string;
  windowMins: 30 | 60 | 120;
  queue: string;
  assignee: string;
  reminderChannels: CbChannel[];
  priority: CbPriority;
  notes?: string;
}
