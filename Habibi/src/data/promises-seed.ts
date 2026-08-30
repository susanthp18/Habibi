// Promise-to-Pay & Payment Plans seed data.
// All state is mutated in-memory by the route so actions feel real.

import {
  customers as _customers,
  fmtMoney as _fmtMoney,
  fmtDate as _fmtDate,
} from "./customer360-seed";

export type PromiseStatus = "upcoming" | "due_today" | "kept" | "broken" | "partial";
export type PromiseChannel = "voice" | "whatsapp" | "sms" | "chat" | "email";
export type PromiseSource = "bot" | "agent" | "self";
export type ReminderStatus = "off" | "scheduled" | "sent";

export interface PtpEvent {
  at: string;
  label: string;
  tone?: "info" | "success" | "warn" | "danger";
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
  paidAmount?: number;
  notes?: string;
  planId?: string;
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
  paidOn?: string;
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

// re-export formatters so consumers don't cross-import
export const fmtMoney = _fmtMoney;
export const fmtDate = _fmtDate;

// ---- helpers ----
const now = new Date();
function dayISO(offsetDays: number) {
  const d = new Date(now);
  d.setDate(d.getDate() + offsetDays);
  d.setHours(10, 0, 0, 0);
  return d.toISOString();
}
function tail(id: string) {
  return id.slice(-4);
}

const AGENTS = ["Priya Nair", "Rohan Sethi", "Ananya Iyer", "Kabir Rao", "Sana Kapoor", "AI Bot"];

// ---- seed builders ----
type CustSlim = { id: string; name: string; accountId: string; outstanding: number };
const custPool: CustSlim[] = _customers.map((c) => ({
  id: c.id,
  name: c.name,
  accountId: c.accountId,
  outstanding: c.outstanding || 45000,
}));

// Enrich with a wider synthetic roster
const extraNames = [
  "Aditya Verma",
  "Meera Joshi",
  "Nikhil Bansal",
  "Riya Chawla",
  "Vikram Malhotra",
  "Sneha Pillai",
  "Arjun Menon",
  "Devika Rao",
  "Farhan Khan",
  "Isha Kapoor",
  "Sameer Ahuja",
  "Tanvi Shah",
  "Rahul Sinha",
  "Neha Trivedi",
  "Yash Gupta",
];
extraNames.forEach((name, i) => {
  custPool.push({
    id: `X${i + 1}`,
    name,
    accountId: `AC-99${(100 + i).toString()}`,
    outstanding: 18000 + ((i * 7331) % 90000),
  });
});

function pickChannel(i: number): PromiseChannel {
  return (["voice", "whatsapp", "whatsapp", "sms", "chat", "voice"] as const)[i % 6];
}
function pickSource(i: number): PromiseSource {
  return (["bot", "bot", "agent", "agent", "self", "bot"] as const)[i % 6];
}
function pickReminder(i: number): ReminderStatus {
  return (["scheduled", "sent", "scheduled", "off", "sent", "scheduled"] as const)[i % 6];
}

interface Blueprint {
  status: PromiseStatus;
  daysOffset: number; // relative promised date
  createdOffset: number; // relative created date (negative = past)
}

const blueprints: Blueprint[] = [
  // Upcoming
  { status: "upcoming", daysOffset: 2, createdOffset: -1 },
  { status: "upcoming", daysOffset: 3, createdOffset: -2 },
  { status: "upcoming", daysOffset: 5, createdOffset: -3 },
  { status: "upcoming", daysOffset: 6, createdOffset: -1 },
  { status: "upcoming", daysOffset: 9, createdOffset: -4 },
  { status: "upcoming", daysOffset: 12, createdOffset: -2 },
  // Due today
  { status: "due_today", daysOffset: 0, createdOffset: -4 },
  { status: "due_today", daysOffset: 0, createdOffset: -6 },
  { status: "due_today", daysOffset: 0, createdOffset: -2 },
  { status: "due_today", daysOffset: 0, createdOffset: -3 },
  // Kept
  { status: "kept", daysOffset: -1, createdOffset: -5 },
  { status: "kept", daysOffset: -3, createdOffset: -9 },
  { status: "kept", daysOffset: -6, createdOffset: -14 },
  { status: "kept", daysOffset: -10, createdOffset: -20 },
  // Broken
  { status: "broken", daysOffset: -2, createdOffset: -8 },
  { status: "broken", daysOffset: -4, createdOffset: -12 },
  { status: "broken", daysOffset: -7, createdOffset: -15 },
  // Partial
  { status: "partial", daysOffset: -1, createdOffset: -6 },
  { status: "partial", daysOffset: -3, createdOffset: -10 },
  { status: "partial", daysOffset: -5, createdOffset: -13 },
  { status: "partial", daysOffset: -8, createdOffset: -18 },
  // A couple more
  { status: "upcoming", daysOffset: 14, createdOffset: -1 },
];

function eventsForStatus(
  status: PromiseStatus,
  created: string,
  promised: string,
  amount: number,
  paidAmount?: number,
): PtpEvent[] {
  const evts: PtpEvent[] = [{ at: created, label: "Promise captured", tone: "info" }];
  if (status === "upcoming" || status === "due_today") {
    evts.push({ at: created, label: "Reminder scheduled", tone: "info" });
    if (status === "due_today")
      evts.push({ at: promised, label: "Reminder sent (SMS + WhatsApp)", tone: "info" });
  }
  if (status === "kept") {
    evts.push({ at: promised, label: `Payment received · ${_fmtMoney(amount)}`, tone: "success" });
  }
  if (status === "partial") {
    evts.push({
      at: promised,
      label: `Partial payment · ${_fmtMoney(paidAmount ?? amount / 2)}`,
      tone: "warn",
    });
    evts.push({ at: promised, label: "Balance follow-up scheduled", tone: "info" });
  }
  if (status === "broken") {
    evts.push({ at: promised, label: "Reminder sent, no response", tone: "warn" });
    evts.push({
      at: promised,
      label: "Auto-flagged as broken · routed to follow-up",
      tone: "danger",
    });
  }
  return evts;
}

const _seedPromises: Promise[] = blueprints.map((bp, i) => {
  const c = custPool[i % custPool.length];
  const base = 2000 + ((i * 1373) % 22000);
  const amount = Math.round(base / 100) * 100;
  const created = dayISO(bp.createdOffset);
  const promised = dayISO(bp.daysOffset);
  const paidAmount = bp.status === "partial" ? Math.round((amount * 0.4) / 100) * 100 : undefined;
  return {
    id: `PTP-${(1001 + i).toString()}`,
    customerId: c.id,
    customerName: c.name,
    accountTail: tail(c.accountId),
    amount,
    promisedDate: promised,
    createdAt: created,
    channel: pickChannel(i),
    source: pickSource(i),
    owner: AGENTS[i % AGENTS.length],
    reminderStatus: pickReminder(i),
    status: bp.status,
    paidAmount,
    notes: bp.status === "broken" ? "No response on follow-up call." : undefined,
    events: eventsForStatus(bp.status, created, promised, amount, paidAmount),
  };
});

// ---- payment plans ----
let _seedPlans: PaymentPlan[] = [];
function buildPlan(
  idx: number,
  customer: CustSlim,
  total: number,
  n: number,
  cadence: PlanCadence,
  paidCount: number,
): PaymentPlan {
  const startOffset = -n + paidCount; // start so paidCount installments are past-due
  const startDate = dayISO(startOffset * cadenceDays(cadence));
  const per = Math.round(total / n / 100) * 100;
  const installments: Installment[] = Array.from({ length: n }, (_, i) => {
    const due = dayISO((startOffset + i) * cadenceDays(cadence));
    return {
      index: i + 1,
      dueDate: due,
      amount: i === n - 1 ? total - per * (n - 1) : per,
      paid: i < paidCount,
      paidOn: i < paidCount ? due : undefined,
    };
  });
  const overdue = installments.some(
    (x) => !x.paid && new Date(x.dueDate).getTime() < Date.now() - 86400000,
  );
  const status: PlanStatus = paidCount === n ? "completed" : overdue ? "slipped" : "on_track";
  return {
    id: `PLAN-${2001 + idx}`,
    customerId: customer.id,
    customerName: customer.name,
    accountTail: tail(customer.accountId),
    total,
    cadence,
    startDate,
    installments,
    owner: AGENTS[idx % (AGENTS.length - 1)],
    status,
    createdAt: dayISO(startOffset * cadenceDays(cadence) - 2),
  };
}
function cadenceDays(c: PlanCadence) {
  return c === "weekly" ? 7 : c === "biweekly" ? 14 : 30;
}
_seedPlans = [
  buildPlan(0, custPool[0], 48000, 6, "monthly", 3),
  buildPlan(1, custPool[2], 28000, 4, "biweekly", 2),
  buildPlan(2, custPool[4], 60000, 6, "monthly", 4),
  buildPlan(3, custPool[6], 18000, 3, "weekly", 3),
  buildPlan(4, custPool[8], 72000, 8, "monthly", 2),
  buildPlan(5, custPool[10], 32000, 4, "biweekly", 1),
];

// ---- mutable exports (single session state) ----
export const promises: Promise[] = _seedPromises;
export const plans: PaymentPlan[] = _seedPlans;
export const followUps: FollowUp[] = [];

// ---- customer picker source ----
export function listCustomerSlim(): CustSlim[] {
  return custPool;
}

// ---- schedule builder ----
export interface ScheduleInput {
  total: number;
  installments: number;
  startDate: string; // ISO
  cadence: PlanCadence;
}
export function buildSchedule({
  total,
  installments,
  startDate,
  cadence,
}: ScheduleInput): Installment[] {
  const per = Math.round(total / installments / 100) * 100;
  const start = new Date(startDate);
  const days = cadenceDays(cadence);
  return Array.from({ length: installments }, (_, i) => {
    const due = new Date(start);
    due.setDate(due.getDate() + i * days);
    return {
      index: i + 1,
      dueDate: due.toISOString(),
      amount: i === installments - 1 ? total - per * (installments - 1) : per,
      paid: false,
    };
  });
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
export const defaultFilters: Filters = {
  status: "all",
  source: "all",
  aging: "any",
  amount: "any",
  owner: "all",
  search: "",
};

export function filterPromises(list: Promise[], f: Filters): Promise[] {
  const today = new Date().setHours(0, 0, 0, 0);
  return list.filter((p) => {
    if (f.status !== "all" && p.status !== f.status) return false;
    if (f.source !== "all" && p.source !== f.source) return false;
    if (f.owner !== "all" && p.owner !== f.owner) return false;
    if (f.search) {
      const q = f.search.toLowerCase();
      if (
        !p.customerName.toLowerCase().includes(q) &&
        !p.accountTail.includes(q) &&
        !p.id.toLowerCase().includes(q)
      )
        return false;
    }
    if (f.amount !== "any") {
      const a = p.amount;
      if (f.amount === "lt5" && a >= 5000) return false;
      if (f.amount === "5to25" && (a < 5000 || a > 25000)) return false;
      if (f.amount === "gt25" && a <= 25000) return false;
    }
    if (f.aging !== "any") {
      const promised = new Date(p.promisedDate).setHours(0, 0, 0, 0);
      const diffDays = Math.round((promised - today) / 86400000);
      if (f.aging === "3d" && !(diffDays >= 0 && diffDays <= 3)) return false;
      if (f.aging === "7d" && !(diffDays >= 0 && diffDays <= 7)) return false;
      if (f.aging === "gt7" && !(diffDays > 7)) return false;
      if (f.aging === "overdue" && !(diffDays < 0)) return false;
    }
    return true;
  });
}

export function computeMetrics(list: Promise[]) {
  const active = list.filter((p) => p.status === "upcoming" || p.status === "due_today");
  const dueToday = list.filter((p) => p.status === "due_today");
  const kept = list.filter((p) => p.status === "kept");
  const broken = list.filter((p) => p.status === "broken");
  const partial = list.filter((p) => p.status === "partial");
  const resolved = kept.length + broken.length + partial.length;
  const keptRate =
    resolved === 0 ? 0 : Math.round(((kept.length + partial.length * 0.5) / resolved) * 100);

  const atRiskAmt =
    broken.reduce((s, p) => s + p.amount, 0) +
    partial.reduce((s, p) => s + (p.amount - (p.paidAmount ?? 0)), 0);

  // avg days-to-keep among kept promises
  const daysToKeep = kept.map((p) => {
    const days = Math.round(
      (new Date(p.promisedDate).getTime() - new Date(p.createdAt).getTime()) / 86400000,
    );
    return Math.max(days, 0);
  });
  const avgDays =
    daysToKeep.length === 0
      ? 0
      : Math.round((daysToKeep.reduce((a, b) => a + b, 0) / daysToKeep.length) * 10) / 10;

  return {
    keptRate,
    activeCount: active.length,
    activeAmt: active.reduce((s, p) => s + p.amount, 0),
    dueTodayCount: dueToday.length,
    dueTodayAmt: dueToday.reduce((s, p) => s + p.amount, 0),
    atRiskAmt,
    avgDays,
    counts: {
      all: list.length,
      upcoming: list.filter((p) => p.status === "upcoming").length,
      due_today: dueToday.length,
      kept: kept.length,
      broken: broken.length,
      partial: partial.length,
    },
    subtotals: {
      upcoming: list.filter((p) => p.status === "upcoming").reduce((s, p) => s + p.amount, 0),
      due_today: dueToday.reduce((s, p) => s + p.amount, 0),
      kept: kept.reduce((s, p) => s + p.amount, 0),
      broken: broken.reduce((s, p) => s + p.amount, 0),
      partial: partial.reduce((s, p) => s + p.amount, 0),
    },
  };
}

// ---- mutations ----
let nextPtp = 2000;
export function createPromise(input: {
  customerId: string;
  customerName: string;
  accountTail: string;
  amount: number;
  promisedDate: string;
  channel: PromiseChannel;
  source: PromiseSource;
  owner: string;
  reminder: ReminderStatus;
  notes?: string;
  planId?: string;
}): Promise {
  const id = `PTP-${(nextPtp++).toString()}`;
  const createdAt = new Date().toISOString();
  const today = new Date().setHours(0, 0, 0, 0);
  const promisedDay = new Date(input.promisedDate).setHours(0, 0, 0, 0);
  const status: PromiseStatus = promisedDay === today ? "due_today" : "upcoming";
  const p: Promise = {
    id,
    customerId: input.customerId,
    customerName: input.customerName,
    accountTail: input.accountTail,
    amount: input.amount,
    promisedDate: input.promisedDate,
    createdAt,
    channel: input.channel,
    source: input.source,
    owner: input.owner,
    reminderStatus: input.reminder,
    status,
    planId: input.planId,
    notes: input.notes,
    events: [
      { at: createdAt, label: "Promise captured", tone: "info" },
      ...(input.reminder !== "off"
        ? [{ at: createdAt, label: "Reminder scheduled", tone: "info" as const }]
        : []),
    ],
  };
  promises.unshift(p);
  return p;
}

let nextPlan = 3000;
export function createPlan(input: {
  customerId: string;
  customerName: string;
  accountTail: string;
  total: number;
  installments: number;
  startDate: string;
  cadence: PlanCadence;
  owner: string;
}): PaymentPlan {
  const id = `PLAN-${(nextPlan++).toString()}`;
  const schedule = buildSchedule({
    total: input.total,
    installments: input.installments,
    startDate: input.startDate,
    cadence: input.cadence,
  });
  const plan: PaymentPlan = {
    id,
    customerId: input.customerId,
    customerName: input.customerName,
    accountTail: input.accountTail,
    total: input.total,
    cadence: input.cadence,
    startDate: input.startDate,
    installments: schedule,
    owner: input.owner,
    status: "on_track",
    createdAt: new Date().toISOString(),
  };
  plans.unshift(plan);
  // First installment becomes an upcoming promise
  createPromise({
    customerId: input.customerId,
    customerName: input.customerName,
    accountTail: input.accountTail,
    amount: schedule[0].amount,
    promisedDate: schedule[0].dueDate,
    channel: "whatsapp",
    source: "agent",
    owner: input.owner,
    reminder: "scheduled",
    notes: `Installment 1 of ${input.installments} · plan ${id}`,
    planId: id,
  });
  return plan;
}

export function movePromise(
  id: string,
  next: PromiseStatus,
  opts?: { paidAmount?: number },
): FollowUp | undefined {
  const p = promises.find((x) => x.id === id);
  if (!p) return;
  const at = new Date().toISOString();
  p.status = next;
  if (next === "kept") {
    p.paidAmount = p.amount;
    p.events.push({ at, label: `Marked kept · ${fmtMoney(p.amount)}`, tone: "success" });
  } else if (next === "partial") {
    p.paidAmount = opts?.paidAmount ?? Math.round(p.amount * 0.5);
    p.events.push({ at, label: `Marked partial · ${fmtMoney(p.paidAmount)}`, tone: "warn" });
  } else if (next === "broken") {
    p.events.push({ at, label: "Marked broken", tone: "danger" });
    const fu: FollowUp = {
      id: `FU-${Date.now().toString().slice(-6)}`,
      promiseId: p.id,
      customerName: p.customerName,
      amount: p.amount,
      createdAt: at,
    };
    followUps.unshift(fu);
    p.events.push({ at, label: "Routed to follow-up queue", tone: "danger" });
    return fu;
  } else {
    p.events.push({ at, label: `Moved to ${next.replace("_", " ")}`, tone: "info" });
  }
}

export function reschedulePromise(id: string, newDate: string) {
  const p = promises.find((x) => x.id === id);
  if (!p) return;
  p.promisedDate = newDate;
  const today = new Date().setHours(0, 0, 0, 0);
  const promisedDay = new Date(newDate).setHours(0, 0, 0, 0);
  p.status = promisedDay === today ? "due_today" : "upcoming";
  p.events.push({
    at: new Date().toISOString(),
    label: `Rescheduled to ${fmtDate(newDate)}`,
    tone: "info",
  });
}

export const STATUS_ORDER: PromiseStatus[] = ["upcoming", "due_today", "kept", "broken", "partial"];
export const STATUS_LABELS: Record<PromiseStatus, string> = {
  upcoming: "Upcoming",
  due_today: "Due today",
  kept: "Kept",
  broken: "Broken",
  partial: "Partial",
};
