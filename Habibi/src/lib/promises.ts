import type {
  PromiseStatus,
  PromiseChannel,
  PromiseSource,
  ReminderStatus,
  PtpEvent,
  Promise,
  PlanCadence,
  PlanStatus,
  Installment,
  PaymentPlan,
  FollowUp,
  ScheduleInput,
  Filters,
} from "@/api/types/promises";

function cadenceDays(c: PlanCadence) {
  return c === "weekly" ? 7 : c === "biweekly" ? 14 : 30;
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

export const STATUS_ORDER: PromiseStatus[] = ["upcoming", "due_today", "kept", "broken", "partial"];

export const STATUS_LABELS: Record<PromiseStatus, string> = {
  upcoming: "Upcoming",
  due_today: "Due today",
  kept: "Kept",
  broken: "Broken",
  partial: "Partial",
};
