/**
 * Domain / wire types for the promises surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
 */

export type PromiseStatus = "upcoming" | "due_today" | "kept" | "broken" | "partial";
export type PromiseChannel = "voice" | "whatsapp" | "sms" | "chat" | "email";
export type PromiseSource = "bot" | "agent" | "self";
export type ReminderStatus = "off" | "scheduled" | "sent";
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
export interface Filters {
  status: PromiseStatus | "all";
  source: PromiseSource | "all";
  aging: "any" | "3d" | "7d" | "gt7" | "overdue";
  amount: "any" | "lt5" | "5to25" | "gt25";
  owner: string | "all";
  search: string;
}
