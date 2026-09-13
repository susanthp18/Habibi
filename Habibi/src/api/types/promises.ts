/**
 * Domain / wire types for the promises surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
 */

/** The column's CHECK, as the wire declares it (api/wire/constants.json pins these lists). */
export const PROMISE_STATUSES = [
  "upcoming",
  "due_today",
  "kept",
  "broken",
  "partial",
  "cancelled",
] as const;
export type PromiseStatus = (typeof PROMISE_STATUSES)[number];
export type PromiseChannel = "voice" | "whatsapp" | "sms" | "chat" | "email";
export type PromiseSource = "bot" | "agent" | "self";
export const REMINDER_STATUSES = [
  "off",
  "queued",
  "scheduled",
  "sent",
  "acknowledged",
  "failed",
] as const;
export type ReminderStatus = (typeof REMINDER_STATUSES)[number];
/** Why a promise was renegotiated or withdrawn (promise_revisions.reason). */
export const PROMISE_REVISION_REASONS = [
  "customer_requested_delay",
  "salary_delayed",
  "medical",
  "dispute_raised",
  "partial_payment_agreed",
  "agent_correction",
  "other",
] as const;
export type PromiseRevisionReason = (typeof PROMISE_REVISION_REASONS)[number];

/** A renegotiation: what the commitment was, what it became, why. */
export interface PromiseRevision {
  seq: number;
  priorAmount: number;
  priorPromisedDate: string;
  amount: number;
  promisedDate: string;
  reason: PromiseRevisionReason;
  note?: string | null;
  actorKind: "human" | "bot" | "system";
  actor?: string | null;
  createdAt: string;
}

export interface ReviseInput {
  promisedDate?: string;
  amount?: number;
  reason: PromiseRevisionReason;
  note?: string;
}
/** What the create sheet (or the 360) submits. The owner defaults to the acting user. */
export interface CreateInput {
  customerId: string;
  accountId?: string;
  amount: number;
  promisedDate: string;
  channel: PromiseChannel;
  owner?: string;
  reminder: ReminderStatus;
  notes?: string;
}

export interface CustomerOption {
  id: string;
  name: string;
  accountId: string;
  outstanding: number;
}

export interface PlanInput {
  customerId: string;
  total: number;
  installments: number;
  startDate: string;
  cadence: PlanCadence;
  owner: string;
}

export interface PtpEvent {
  at: string;
  label: string;
  tone?: "info" | "success" | "warn" | "danger" | null;
}
export interface Promise {
  id: string;
  customerId: string;
  customerName: string;
  accountTail: string;
  amount: number;
  promisedDate: string; // ISO
  createdAt: string;
  channel: PromiseChannel;
  source: PromiseSource;
  owner: string;
  reminderStatus: ReminderStatus;
  status: PromiseStatus;
  revisionCount: number;
  cancelReason?: string | null;
  paidAmount?: number | null;
  notes?: string | null;
  planId?: string | null;
  events: PtpEvent[];
  confirmChannel?: "whatsapp" | "sms" | null;
  confirmStatus?: string | null;
  paymentIntentStatus?: string | null;
  paymentIntentId?: string | null;
  payLinkSent?: boolean;
  phoneLast4?: string | null;
}
export type PlanCadence = "weekly" | "biweekly" | "monthly";
export type PlanStatus = "on_track" | "slipped" | "completed";
export interface Installment {
  index: number;
  dueDate: string;
  amount: number;
  paid: boolean;
  paidOn?: string | null;
}
export interface PaymentPlan {
  id: string;
  customerId: string;
  customerName: string;
  accountTail: string;
  total: number;
  cadence: PlanCadence;
  startDate: string;
  installments: Installment[];
  owner: string;
  status: PlanStatus;
  createdAt: string;
}
export interface FollowUp {
  id: string;
  promiseId: string;
  customerName: string;
  amount: number;
  createdAt: string;
}
// ---- schedule builder ----
export interface ScheduleInput {
  total: number;
  installments: number;
  startDate: string; // ISO
  cadence: PlanCadence;
}
// ---- filters + metrics ----
export interface PromiseFilters {
  status: PromiseStatus | "all";
  source: PromiseSource | "all";
  aging: "any" | "3d" | "7d" | "gt7" | "overdue";
  amount: "any" | "lt5" | "5to25" | "gt25";
  owner: string | "all";
  search: string;
}
