import type { LozengeTone } from "@/components/ui/lozenge";
import type {
  CbStatus,
  CbReason,
  CbChannel,
  CbSource,
  CbPriority,
  CbDisposition,
  CbReminder,
  CbEvent,
  Callback,
  CallbackFilters,
  CreateInput,
} from "@/api/types/callbacks";

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

export const CURRENT_QUEUE = "Retail Collections";

// ---- helpers ----
function pad(n: number) {
  return n < 10 ? `0${n}` : `${n}`;
}

export const defaultFilters: CallbackFilters = {
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
  f: CallbackFilters,
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
export type WeekDays = [Date, Date, Date, Date, Date, Date, Date];

/** Return 7 dates starting from Monday of the week containing `anchor`. */
export function weekDays(anchor: Date): WeekDays {
  const start = new Date(anchor);
  const day = start.getDay(); // 0=Sun..6=Sat
  const diffToMon = (day + 6) % 7;
  start.setDate(start.getDate() - diffToMon);
  start.setHours(0, 0, 0, 0);
  const day_ = (i: number) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return d;
  };
  return [day_(0), day_(1), day_(2), day_(3), day_(4), day_(5), day_(6)];
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
  const startH = parseInt(m[1] ?? "");
  const endH = parseInt(m[3] ?? "");
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
