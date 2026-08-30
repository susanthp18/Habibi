// Callback & Scheduling Manager seed data
// Mutable in-memory store — mirrors the documents/disputes-seed pattern.

import { customers as _customers } from "./customer360-seed";
import type { LozengeTone } from "@/components/ui/lozenge";

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

export const STATUS_LABELS: Record<CbStatus, string> = {
  scheduled: "Scheduled",
  reminded: "Reminded",
  in_progress: "In progress",
  completed: "Completed",
  missed: "Missed",
  rescheduled: "Rescheduled",
  cancelled: "Cancelled",
};

export const STATUS_TONE: Record<CbStatus, LozengeTone> = {
  scheduled: "selected",
  reminded: "discovery",
  in_progress: "warning",
  completed: "success",
  missed: "danger",
  rescheduled: "neutral",
  cancelled: "neutral",
};

export const REASON_LABELS: Record<CbReason, string> = {
  payment_discussion: "Payment discussion",
  dispute_followup: "Dispute follow-up",
  document_query: "Document query",
  hardship_review: "Hardship review",
  upsell_interest: "Upsell interest",
  general: "General query",
};

export const CHANNEL_LABELS: Record<CbChannel, string> = {
  whatsapp: "WhatsApp",
  sms: "SMS",
  email: "Email",
};

export const SOURCE_LABELS: Record<CbSource, string> = {
  bot_voice: "Bot · Voice",
  bot_chat: "Bot · Chat",
  agent: "Agent",
};

export const PRIORITY_LABELS: Record<CbPriority, string> = {
  low: "Low",
  normal: "Normal",
  high: "High",
  urgent: "Urgent",
};

export const DISPOSITION_LABELS: Record<CbDisposition, string> = {
  reached: "Reached · resolved",
  no_answer: "No answer",
  ptp_captured: "PTP captured",
  not_interested: "Not interested",
  callback_again: "Callback again",
};

export const QUEUES = [
  "Retail Collections",
  "Cards Collections",
  "Loans Collections",
  "Escalations",
];

export const AGENTS = [
  "Unassigned",
  "Priya Nair",
  "Rohan Sethi",
  "Ananya Iyer",
  "Kabir Rao",
  "Sana Kapoor",
  "Vikram Menon",
];

export const CURRENT_AGENT = "Priya Nair";
export const CURRENT_QUEUE = "Retail Collections";

// ---- helpers ----
function pad(n: number) {
  return n < 10 ? `0${n}` : `${n}`;
}

/** Build an ISO string for `dayOffset` days from today at HH:MM local. */
function slotISO(dayOffset: number, hour: number, minute: number) {
  const d = new Date();
  d.setDate(d.getDate() + dayOffset);
  d.setHours(hour, minute, 0, 0);
  return d.toISOString();
}

function tailOf(accountId: string) {
  return accountId.slice(-4);
}

// Customer pool — reuse Customer 360, plus a few extras for volume.
const CUST_POOL = _customers.map((c) => ({
  id: c.id,
  name: c.name,
  accountId: c.accountId,
  dnd: c.contact.dnd,
  preferredWindow: `${c.contact.preferredWindow ?? "10:00–19:00"} IST`,
  timezone: c.contact.timezone ?? "Asia/Kolkata (IST)",
}));

const EXTRA = [
  {
    id: "aditya-verma",
    name: "Aditya Verma",
    accountId: "AC-99201",
    dnd: false,
    preferredWindow: "10:00–19:00 IST",
    timezone: "Asia/Kolkata (IST)",
  },
  {
    id: "meera-joshi",
    name: "Meera Joshi",
    accountId: "AC-99202",
    dnd: false,
    preferredWindow: "11:00–20:00 IST",
    timezone: "Asia/Kolkata (IST)",
  },
  {
    id: "nikhil-bansal",
    name: "Nikhil Bansal",
    accountId: "AC-99203",
    dnd: true,
    preferredWindow: "18:00–21:00 IST",
    timezone: "Asia/Kolkata (IST)",
  },
  {
    id: "riya-chawla",
    name: "Riya Chawla",
    accountId: "AC-99204",
    dnd: false,
    preferredWindow: "09:00–18:00 IST",
    timezone: "Asia/Kolkata (IST)",
  },
  {
    id: "sneha-pillai",
    name: "Sneha Pillai",
    accountId: "AC-99205",
    dnd: false,
    preferredWindow: "10:00–19:00 IST",
    timezone: "Asia/Kolkata (IST)",
  },
  {
    id: "farhan-khan",
    name: "Farhan Khan",
    accountId: "AC-99206",
    dnd: false,
    preferredWindow: "12:00–20:00 IST",
    timezone: "Asia/Kolkata (IST)",
  },
  {
    id: "arjun-nair-nyc",
    name: "Arjun Nair (NY)",
    accountId: "AC-99207",
    dnd: false,
    preferredWindow: "20:00–23:00 IST",
    timezone: "America/New_York (EST)",
  },
];

const POOL = [...CUST_POOL, ...EXTRA];

const REASONS: CbReason[] = [
  "payment_discussion",
  "dispute_followup",
  "document_query",
  "hardship_review",
  "upsell_interest",
  "general",
];

const SNIPPETS: Record<CbReason, string> = {
  payment_discussion:
    '"I get salary on the 5th — please call me after that to discuss the overdue."',
  dispute_followup: '"You said someone will call me back about the double charge on my card."',
  document_query: '"Can an agent walk me through the interest certificate for tax filing?"',
  hardship_review: '"I lost my job last month — need to talk about reducing the EMI."',
  upsell_interest: '"Yes, I might be interested in the top-up loan — call me tomorrow evening."',
  general: '"Please call me back, the bot couldn\'t answer my question."',
};

interface Blueprint {
  dayOffset: number;
  hour: number;
  minute: number;
  windowMins: 30 | 60 | 120;
  reason: CbReason;
  source: CbSource;
  status: CbStatus;
  assigneeIdx?: number; // index into AGENTS, 0 = Unassigned
  priority?: CbPriority;
  channel?: CbChannel;
}

const BLUEPRINTS: Blueprint[] = [
  // TODAY — busy schedule
  {
    dayOffset: 0,
    hour: 9,
    minute: 30,
    windowMins: 30,
    reason: "payment_discussion",
    source: "bot_voice",
    status: "completed",
    assigneeIdx: 1,
  },
  {
    dayOffset: 0,
    hour: 10,
    minute: 0,
    windowMins: 60,
    reason: "dispute_followup",
    source: "bot_voice",
    status: "completed",
    assigneeIdx: 2,
    priority: "high",
  },
  {
    dayOffset: 0,
    hour: 11,
    minute: 0,
    windowMins: 30,
    reason: "document_query",
    source: "bot_chat",
    status: "missed",
    assigneeIdx: 3,
  },
  {
    dayOffset: 0,
    hour: 12,
    minute: 30,
    windowMins: 60,
    reason: "hardship_review",
    source: "bot_voice",
    status: "in_progress",
    assigneeIdx: 1,
    priority: "urgent",
  },
  {
    dayOffset: 0,
    hour: 14,
    minute: 0,
    windowMins: 30,
    reason: "upsell_interest",
    source: "bot_voice",
    status: "reminded",
    assigneeIdx: 4,
  },
  {
    dayOffset: 0,
    hour: 15,
    minute: 0,
    windowMins: 60,
    reason: "payment_discussion",
    source: "bot_voice",
    status: "scheduled",
    assigneeIdx: 1,
  },
  {
    dayOffset: 0,
    hour: 16,
    minute: 30,
    windowMins: 30,
    reason: "general",
    source: "bot_chat",
    status: "scheduled",
    assigneeIdx: 0,
  },
  {
    dayOffset: 0,
    hour: 17,
    minute: 0,
    windowMins: 60,
    reason: "payment_discussion",
    source: "bot_voice",
    status: "scheduled",
    assigneeIdx: 5,
    priority: "high",
  },
  {
    dayOffset: 0,
    hour: 18,
    minute: 30,
    windowMins: 30,
    reason: "upsell_interest",
    source: "agent",
    status: "scheduled",
    assigneeIdx: 6,
  },
  {
    dayOffset: 0,
    hour: 20,
    minute: 0,
    windowMins: 60,
    reason: "hardship_review",
    source: "bot_voice",
    status: "scheduled",
    assigneeIdx: 0,
  }, // late — DND risk

  // TOMORROW
  {
    dayOffset: 1,
    hour: 10,
    minute: 0,
    windowMins: 30,
    reason: "payment_discussion",
    source: "bot_voice",
    status: "scheduled",
    assigneeIdx: 1,
  },
  {
    dayOffset: 1,
    hour: 11,
    minute: 30,
    windowMins: 60,
    reason: "dispute_followup",
    source: "bot_voice",
    status: "scheduled",
    assigneeIdx: 2,
    priority: "high",
  },
  {
    dayOffset: 1,
    hour: 14,
    minute: 0,
    windowMins: 30,
    reason: "document_query",
    source: "bot_chat",
    status: "scheduled",
    assigneeIdx: 3,
  },
  {
    dayOffset: 1,
    hour: 15,
    minute: 30,
    windowMins: 60,
    reason: "upsell_interest",
    source: "bot_voice",
    status: "scheduled",
    assigneeIdx: 4,
  },
  {
    dayOffset: 1,
    hour: 17,
    minute: 0,
    windowMins: 30,
    reason: "general",
    source: "agent",
    status: "scheduled",
    assigneeIdx: 5,
  },

  // DAY +2
  {
    dayOffset: 2,
    hour: 10,
    minute: 30,
    windowMins: 30,
    reason: "payment_discussion",
    source: "bot_voice",
    status: "scheduled",
    assigneeIdx: 1,
  },
  {
    dayOffset: 2,
    hour: 13,
    minute: 0,
    windowMins: 60,
    reason: "hardship_review",
    source: "bot_voice",
    status: "scheduled",
    assigneeIdx: 6,
    priority: "high",
  },
  {
    dayOffset: 2,
    hour: 16,
    minute: 0,
    windowMins: 30,
    reason: "dispute_followup",
    source: "bot_chat",
    status: "scheduled",
    assigneeIdx: 2,
  },

  // DAY +3
  {
    dayOffset: 3,
    hour: 11,
    minute: 0,
    windowMins: 30,
    reason: "upsell_interest",
    source: "bot_voice",
    status: "scheduled",
    assigneeIdx: 4,
  },
  {
    dayOffset: 3,
    hour: 15,
    minute: 0,
    windowMins: 60,
    reason: "payment_discussion",
    source: "bot_voice",
    status: "scheduled",
    assigneeIdx: 0,
  },

  // YESTERDAY — historical
  {
    dayOffset: -1,
    hour: 11,
    minute: 0,
    windowMins: 30,
    reason: "payment_discussion",
    source: "bot_voice",
    status: "completed",
    assigneeIdx: 1,
  },
  {
    dayOffset: -1,
    hour: 14,
    minute: 30,
    windowMins: 30,
    reason: "document_query",
    source: "bot_chat",
    status: "missed",
    assigneeIdx: 3,
  },
  {
    dayOffset: -1,
    hour: 16,
    minute: 0,
    windowMins: 60,
    reason: "hardship_review",
    source: "bot_voice",
    status: "completed",
    assigneeIdx: 2,
  },
  {
    dayOffset: -1,
    hour: 18,
    minute: 0,
    windowMins: 30,
    reason: "upsell_interest",
    source: "bot_voice",
    status: "missed",
    assigneeIdx: 4,
  },
];

function eventsFor(
  bp: Blueprint,
  createdAt: string,
  scheduledAt: string,
  cust: { name: string },
): CbEvent[] {
  const evts: CbEvent[] = [
    { at: createdAt, label: `Callback captured via ${SOURCE_LABELS[bp.source]}`, tone: "info" },
  ];
  if (bp.assigneeIdx !== undefined && bp.assigneeIdx > 0) {
    evts.push({
      at: createdAt,
      label: `Assigned to ${AGENTS[bp.assigneeIdx]}`,
      actor: "System",
      tone: "info",
    });
  }
  if (bp.status === "reminded") {
    evts.push({
      at: scheduledAt,
      label: `Reminder sent · WhatsApp`,
      actor: "System",
      tone: "info",
    });
  }
  if (bp.status === "in_progress") {
    evts.push({
      at: scheduledAt,
      label: `Call started with ${cust.name}`,
      actor: AGENTS[bp.assigneeIdx ?? 1],
      tone: "info",
    });
  }
  if (bp.status === "completed") {
    evts.push({
      at: scheduledAt,
      label: "Call completed · disposition captured",
      actor: AGENTS[bp.assigneeIdx ?? 1],
      tone: "success",
    });
  }
  if (bp.status === "missed") {
    evts.push({
      at: scheduledAt,
      label: "Missed — no agent joined in window",
      actor: "System",
      tone: "danger",
    });
  }
  return evts;
}

const _cbs: Callback[] = BLUEPRINTS.map((bp, i) => {
  const cust = POOL[i % POOL.length];
  const scheduledAt = slotISO(bp.dayOffset, bp.hour, bp.minute);
  const createdAtDate = new Date(scheduledAt);
  createdAtDate.setHours(createdAtDate.getHours() - 6);
  const createdAt = createdAtDate.toISOString();
  const assignee = AGENTS[bp.assigneeIdx ?? 0];
  const queue = QUEUES[i % QUEUES.length];
  const channel: CbChannel =
    bp.channel ?? (i % 3 === 0 ? "sms" : i % 3 === 1 ? "whatsapp" : "email");

  const reminders: CbReminder[] = [];
  const rem1 = new Date(scheduledAt);
  rem1.setHours(rem1.getHours() - 24);
  reminders.push({
    at: rem1.toISOString(),
    channel,
    status: bp.status === "scheduled" && bp.dayOffset > 0 ? "queued" : "sent",
  });
  if (bp.dayOffset <= 0) {
    const rem2 = new Date(scheduledAt);
    rem2.setMinutes(rem2.getMinutes() - 30);
    reminders.push({
      at: rem2.toISOString(),
      channel: "sms",
      status:
        bp.status === "completed" ||
        bp.status === "missed" ||
        bp.status === "reminded" ||
        bp.status === "in_progress"
          ? "sent"
          : "queued",
    });
  }

  // DND check: if scheduled outside preferredWindow OR customer.dnd is true
  const hour = bp.hour;
  const dndActive = cust.dnd || hour < 9 || hour >= 20;

  return {
    id: `CB-${(5001 + i).toString()}`,
    customerId: cust.id,
    customerName: cust.name,
    accountId: cust.accountId,
    accountTail: tailOf(cust.accountId),
    reason: bp.reason,
    scheduledAt,
    windowMins: bp.windowMins,
    customerTimezone: cust.timezone,
    preferredWindow: cust.preferredWindow,
    customerDnd: cust.dnd,
    dndActive,
    source: bp.source,
    assignee,
    queue,
    priority: bp.priority ?? "normal",
    status: bp.status,
    reminders,
    transcriptSnippet: SNIPPETS[bp.reason],
    originConversationId: bp.source !== "agent" ? `CV-${9000 + i}` : undefined,
    events: eventsFor(bp, createdAt, scheduledAt, cust),
    createdAt,
    disposition:
      bp.status === "completed"
        ? REASONS[i % REASONS.length] === "upsell_interest"
          ? "ptp_captured"
          : "reached"
        : undefined,
    outcomeNotes:
      bp.status === "completed" ? "Customer engaged; details logged to CRM." : undefined,
  };
});

export const callbacks: Callback[] = _cbs;

// ---- Filters ----
export interface Filters {
  search: string;
  queue: string | "all";
  assignee: string | "all";
  reasons: CbReason[];
  statuses: CbStatus[];
  channels: CbChannel[];
  dndSafeOnly: boolean;
  myQueueOnly: boolean;
}

export const defaultFilters: Filters = {
  search: "",
  queue: "all",
  assignee: "all",
  reasons: [],
  statuses: [],
  channels: [],
  dndSafeOnly: false,
  myQueueOnly: false,
};

export function filterCallbacks(
  list: Callback[],
  f: Filters,
  myQueue: string = CURRENT_QUEUE,
): Callback[] {
  return list.filter((c) => {
    if (f.myQueueOnly && c.queue !== myQueue) return false;
    if (f.queue !== "all" && c.queue !== f.queue) return false;
    if (f.assignee !== "all" && c.assignee !== f.assignee) return false;
    if (f.reasons.length && !f.reasons.includes(c.reason)) return false;
    if (f.statuses.length && !f.statuses.includes(c.status)) return false;
    if (f.channels.length && !c.reminders.some((r) => f.channels.includes(r.channel))) return false;
    if (f.dndSafeOnly && c.dndActive) return false;
    if (f.search) {
      const q = f.search.toLowerCase();
      const hay =
        `${c.customerName} ${c.accountId} ${c.id} ${REASON_LABELS[c.reason]} ${c.assignee}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

// ---- Metrics ----
export function computeMetrics(list: Callback[]) {
  const now = Date.now();
  const startOfDay = new Date();
  startOfDay.setHours(0, 0, 0, 0);
  const endOfDay = new Date();
  endOfDay.setHours(23, 59, 59, 999);
  const sevenDaysAgo = now - 7 * 86400000;

  const scheduledToday = list.filter((c) => {
    const t = new Date(c.scheduledAt).getTime();
    return (
      t >= startOfDay.getTime() &&
      t <= endOfDay.getTime() &&
      (c.status === "scheduled" || c.status === "reminded")
    );
  });
  const dueNextHour = list.filter((c) => {
    const t = new Date(c.scheduledAt).getTime();
    return t >= now && t <= now + 3600000 && (c.status === "scheduled" || c.status === "reminded");
  });
  const missed7d = list.filter(
    (c) => c.status === "missed" && new Date(c.scheduledAt).getTime() >= sevenDaysAgo,
  );
  const completed7d = list.filter(
    (c) => c.status === "completed" && new Date(c.scheduledAt).getTime() >= sevenDaysAgo,
  );
  const total7d = completed7d.length + missed7d.length;
  const completionRate = total7d ? Math.round((completed7d.length / total7d) * 100) : 0;
  const unassigned = list.filter(
    (c) => c.assignee === "Unassigned" && (c.status === "scheduled" || c.status === "reminded"),
  );

  return {
    scheduledToday: scheduledToday.length,
    dueNextHour: dueNextHour.length,
    missed7d: missed7d.length,
    completionRate,
    unassigned: unassigned.length,
    total: list.length,
  };
}

// ---- Calendar helpers ----
/** Return 7 dates starting from Monday of the week containing `anchor`. */
export function weekDays(anchor: Date): Date[] {
  const start = new Date(anchor);
  const day = start.getDay(); // 0=Sun..6=Sat
  const diffToMon = (day + 6) % 7;
  start.setDate(start.getDate() - diffToMon);
  start.setHours(0, 0, 0, 0);
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return d;
  });
}

export function sameDay(a: Date, b: Date) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

/** Minutes from CALENDAR_START on a date. */
export const CALENDAR_START_HOUR = 8;
export const CALENDAR_END_HOUR = 21;
export const CAL_MINUTES = (CALENDAR_END_HOUR - CALENDAR_START_HOUR) * 60;

export function minutesFromStart(iso: string): number {
  const d = new Date(iso);
  return (d.getHours() - CALENDAR_START_HOUR) * 60 + d.getMinutes();
}

export function fmtTime(iso: string) {
  const d = new Date(iso);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fmtDayShort(d: Date) {
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

export function fmtLongDate(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function isWithinDndWindow(
  cb: Pick<Callback, "preferredWindow" | "customerDnd">,
  iso?: string,
): boolean {
  const at = iso ? new Date(iso) : new Date((cb as Callback).scheduledAt);
  const hour = at.getHours();
  if (cb.customerDnd) return true;
  // parse "HH:MM–HH:MM ..."
  const m = /(\d{1,2}):(\d{2}).*?(\d{1,2}):(\d{2})/.exec(cb.preferredWindow);
  if (!m) return hour < 9 || hour >= 20;
  const startH = parseInt(m[1]);
  const endH = parseInt(m[3]);
  return hour < startH || hour >= endH;
}

/** Snap to next allowed 30-min slot at or after `from` inside preferred window. */
export function nextAllowedSlot(cb: Callback, from: Date = new Date()): string {
  const d = new Date(from);
  // Round to next :00 or :30
  const mins = d.getMinutes();
  const add = mins === 0 ? 0 : mins <= 30 ? 30 - mins : 60 - mins;
  d.setMinutes(d.getMinutes() + add, 0, 0);
  for (let i = 0; i < 96; i += 1) {
    const iso = d.toISOString();
    if (!isWithinDndWindow(cb, iso)) return iso;
    d.setMinutes(d.getMinutes() + 30);
  }
  return d.toISOString();
}

// ---- Mutations ----
function appendEvent(c: Callback, e: CbEvent) {
  c.events.push(e);
}

export function assign(id: string, assignee: string) {
  const c = callbacks.find((x) => x.id === id);
  if (!c) return;
  const from = c.assignee;
  c.assignee = assignee;
  appendEvent(c, {
    at: new Date().toISOString(),
    label: `Reassigned ${from} → ${assignee}`,
    actor: CURRENT_AGENT,
    tone: "info",
  });
}

export function reassignQueue(id: string, queue: string) {
  const c = callbacks.find((x) => x.id === id);
  if (!c) return;
  const from = c.queue;
  c.queue = queue;
  appendEvent(c, {
    at: new Date().toISOString(),
    label: `Queue ${from} → ${queue}`,
    actor: CURRENT_AGENT,
    tone: "info",
  });
}

export function setPriority(id: string, priority: CbPriority) {
  const c = callbacks.find((x) => x.id === id);
  if (!c) return;
  c.priority = priority;
  appendEvent(c, {
    at: new Date().toISOString(),
    label: `Priority → ${PRIORITY_LABELS[priority]}`,
    actor: CURRENT_AGENT,
    tone: "info",
  });
}

export function reschedule(id: string, newISO: string) {
  const c = callbacks.find((x) => x.id === id);
  if (!c) return;
  const from = c.scheduledAt;
  c.scheduledAt = newISO;
  c.status = "scheduled";
  c.dndActive = isWithinDndWindow(c, newISO);
  appendEvent(c, {
    at: new Date().toISOString(),
    label: `Rescheduled ${fmtLongDate(from)} → ${fmtLongDate(newISO)}`,
    actor: CURRENT_AGENT,
    tone: "info",
  });
}

export function cancel(id: string, reason: string) {
  const c = callbacks.find((x) => x.id === id);
  if (!c) return;
  c.status = "cancelled";
  appendEvent(c, {
    at: new Date().toISOString(),
    label: `Cancelled · ${reason}`,
    actor: CURRENT_AGENT,
    tone: "warn",
  });
}

export function markMissed(id: string) {
  const c = callbacks.find((x) => x.id === id);
  if (!c) return;
  c.status = "missed";
  appendEvent(c, {
    at: new Date().toISOString(),
    label: "Marked as missed",
    actor: "System",
    tone: "danger",
  });
}

export function markCompleted(id: string, disposition: CbDisposition, notes: string) {
  const c = callbacks.find((x) => x.id === id);
  if (!c) return;
  c.status = "completed";
  c.disposition = disposition;
  c.outcomeNotes = notes;
  appendEvent(c, {
    at: new Date().toISOString(),
    label: `Completed · ${DISPOSITION_LABELS[disposition]}`,
    actor: CURRENT_AGENT,
    tone: "success",
  });
}

export function startCall(id: string) {
  const c = callbacks.find((x) => x.id === id);
  if (!c) return;
  c.status = "in_progress";
  appendEvent(c, {
    at: new Date().toISOString(),
    label: "Call started",
    actor: CURRENT_AGENT,
    tone: "info",
  });
}

export function sendReminder(id: string, channel: CbChannel) {
  const c = callbacks.find((x) => x.id === id);
  if (!c) return;
  c.reminders.push({ at: new Date().toISOString(), channel, status: "sent" });
  if (c.status === "scheduled") c.status = "reminded";
  appendEvent(c, {
    at: new Date().toISOString(),
    label: `Reminder sent · ${CHANNEL_LABELS[channel]}`,
    actor: CURRENT_AGENT,
    tone: "info",
  });
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

export function createCallback(input: CreateInput): Callback {
  const cust = POOL.find((p) => p.id === input.customerId) ?? POOL[0];
  const id = `CB-${5001 + callbacks.length}`;
  const createdAt = new Date().toISOString();
  const cb: Callback = {
    id,
    customerId: cust.id,
    customerName: cust.name,
    accountId: cust.accountId,
    accountTail: tailOf(cust.accountId),
    reason: input.reason,
    scheduledAt: input.scheduledAt,
    windowMins: input.windowMins,
    customerTimezone: cust.timezone,
    preferredWindow: cust.preferredWindow,
    customerDnd: cust.dnd,
    dndActive: false,
    source: "agent",
    assignee: input.assignee,
    queue: input.queue,
    priority: input.priority,
    status: "scheduled",
    reminders: input.reminderChannels.map((ch) => ({
      at: createdAt,
      channel: ch,
      status: "queued",
    })),
    transcriptSnippet: input.notes ? `"${input.notes}"` : SNIPPETS[input.reason],
    events: [
      {
        at: createdAt,
        label: `Callback created by ${CURRENT_AGENT}`,
        actor: CURRENT_AGENT,
        tone: "info",
      },
    ],
    createdAt,
  };
  cb.dndActive = isWithinDndWindow(cb);
  callbacks.push(cb);
  return cb;
}

/** Bump any past-window scheduled/reminded callbacks to "missed". Returns count changed. */
export function autoMarkMissed(): number {
  let n = 0;
  const now = Date.now();
  callbacks.forEach((c) => {
    if (c.status !== "scheduled" && c.status !== "reminded") return;
    const end = new Date(c.scheduledAt).getTime() + c.windowMins * 60000;
    if (end < now) {
      c.status = "missed";
      appendEvent(c, {
        at: new Date().toISOString(),
        label: "Auto-marked missed (window elapsed)",
        actor: "System",
        tone: "danger",
      });
      n += 1;
    }
  });
  return n;
}

export function customerOptions() {
  return POOL.map((p) => ({ id: p.id, name: p.name, accountId: p.accountId }));
}
