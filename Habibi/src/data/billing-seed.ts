export type Env = "production" | "sandbox";
export type Period = "mtd" | "7d" | "30d" | "quarter";
export type ServiceCategory = "LLM" | "Voice" | "Messaging" | "Infra";

export type Service = {
  id: string;
  name: string;
  provider: string;
  category: ServiceCategory;
  unit: string; // "1K tokens", "min", etc
  unitCostInr: number;
  color: string;
};

export type DayPoint = {
  date: string; // YYYY-MM-DD
  values: Record<string, number>; // serviceId -> inr
};

export type Tenant = {
  id: string;
  name: string;
  resolvedCalls: number;
  ahtSec: number;
  budgetInr: number;
  spendShare: number; // 0..1 of total org spend
};

export type Invoice = {
  id: string;
  month: string; // "Jun 2026"
  status: "paid" | "pending" | "draft";
  amountInr: number;
  issuedAt: string;
};

export type BudgetRule = {
  id: string;
  threshold: number; // percentage 0-100
  channels: string[];
  action: string;
  severity: "info" | "warn" | "critical";
};

export type Budget = {
  env: Env;
  monthlyCapInr: number;
  rules: BudgetRule[];
};

export const SERVICES: Service[] = [
  { id: "llm_gpt4o", name: "Azure OpenAI GPT-4o", provider: "Azure", category: "LLM", unit: "1K tokens", unitCostInr: 0.42, color: "#3b82f6" },
  { id: "stt_dg", name: "Deepgram Nova-3", provider: "Deepgram", category: "Voice", unit: "minute", unitCostInr: 0.36, color: "#8b5cf6" },
  { id: "tts_11l", name: "ElevenLabs Turbo v2", provider: "ElevenLabs", category: "Voice", unit: "1K chars", unitCostInr: 1.8, color: "#ec4899" },
  { id: "tel_twilio", name: "Twilio Voice (IN)", provider: "Twilio", category: "Voice", unit: "minute", unitCostInr: 0.85, color: "#f97316" },
  { id: "wa_twilio", name: "Twilio WhatsApp BSP", provider: "Twilio", category: "Messaging", unit: "conversation", unitCostInr: 0.62, color: "#22c55e" },
  { id: "pc_orch", name: "Pipecat Orchestrator", provider: "Pipecat", category: "Infra", unit: "active min", unitCostInr: 0.18, color: "#0ea5e9" },
  { id: "lake_ingest", name: "Data Lake ingest", provider: "Databricks", category: "Infra", unit: "GB", unitCostInr: 3.4, color: "#06b6d4" },
  { id: "infra_flat", name: "Postgres + Redis", provider: "Cloud", category: "Infra", unit: "month", unitCostInr: 42000, color: "#64748b" },
];

export const CATEGORY_COLORS: Record<ServiceCategory, string> = {
  LLM: "#3b82f6",
  Voice: "#f97316",
  Messaging: "#22c55e",
  Infra: "#64748b",
};

/* ---- Deterministic pseudo-random ---- */
function seeded(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xffffffff;
  };
}

function fmtDate(d: Date) {
  return d.toISOString().slice(0, 10);
}

/** 60 days of stacked-by-service spend (most-recent last). */
export function buildDaily(days = 60): DayPoint[] {
  const out: DayPoint[] = [];
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const rnd = seeded(20260721);
  // per-service baseline in ₹/day
  const base: Record<string, number> = {
    llm_gpt4o: 4800,
    stt_dg: 2600,
    tts_11l: 2100,
    tel_twilio: 5400,
    wa_twilio: 1200,
    pc_orch: 900,
    lake_ingest: 700,
    infra_flat: 1400, // amortized daily
  };
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    const dow = d.getDay();
    const weekend = dow === 0 || dow === 6 ? 0.55 : 1;
    const drift = 1 + (days - i) * 0.008; // slow growth
    const values: Record<string, number> = {};
    for (const s of SERVICES) {
      const noise = 0.85 + rnd() * 0.3;
      values[s.id] = Math.round(base[s.id] * weekend * drift * noise);
    }
    out.push({ date: fmtDate(d), values });
  }
  return out;
}

export const DAILY: DayPoint[] = buildDaily(60);

export function sliceForPeriod(period: Period): DayPoint[] {
  if (period === "7d") return DAILY.slice(-7);
  if (period === "30d") return DAILY.slice(-30);
  if (period === "quarter") return DAILY.slice(-60); // seed only holds 60d — used as proxy
  // MTD
  const now = new Date();
  const startDay = 1;
  return DAILY.filter((d) => {
    const dt = new Date(d.date);
    return (
      dt.getMonth() === now.getMonth() &&
      dt.getFullYear() === now.getFullYear() &&
      dt.getDate() >= startDay
    );
  });
}

export function previousPeriod(period: Period): DayPoint[] {
  const cur = sliceForPeriod(period);
  const len = cur.length;
  if (len === 0) return [];
  const idx = DAILY.findIndex((d) => d.date === cur[0].date);
  if (idx <= 0) return [];
  const start = Math.max(0, idx - len);
  return DAILY.slice(start, idx);
}

export function sumRange(rows: DayPoint[], serviceId?: string): number {
  return rows.reduce((s, r) => {
    if (serviceId) return s + (r.values[serviceId] ?? 0);
    return s + Object.values(r.values).reduce((a, b) => a + b, 0);
  }, 0);
}

export function changePct(current: number, previous: number): number {
  if (previous === 0) return current === 0 ? 0 : 100;
  return ((current - previous) / previous) * 100;
}

export function forecastEom(daily: DayPoint[]): number {
  if (!daily.length) return 0;
  const now = new Date();
  const dayOfMonth = now.getDate();
  const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  const total = sumRange(daily);
  const perDay = total / Math.max(1, dayOfMonth);
  return Math.round(perDay * daysInMonth);
}

/* ---- Tenants ---- */
export const TENANTS: Tenant[] = [
  { id: "hdfc_retail", name: "HDFC · Retail Loans", resolvedCalls: 21840, ahtSec: 168, budgetInr: 320000, spendShare: 0.42 },
  { id: "hdfc_cards", name: "HDFC · Credit Cards", resolvedCalls: 15220, ahtSec: 154, budgetInr: 260000, spendShare: 0.28 },
  { id: "kotak_pl", name: "Kotak · Personal Loans", resolvedCalls: 9420, ahtSec: 191, budgetInr: 180000, spendShare: 0.18 },
  { id: "icici_auto", name: "ICICI · Auto Loans", resolvedCalls: 6120, ahtSec: 175, budgetInr: 120000, spendShare: 0.12 },
];

/* ---- Invoices ---- */
function inrRoundTo(n: number, step = 100) {
  return Math.round(n / step) * step;
}
export const INVOICES: Invoice[] = [
  { id: "INV-2026-06", month: "Jun 2026", status: "paid", amountInr: inrRoundTo(612430), issuedAt: "2026-07-01" },
  { id: "INV-2026-05", month: "May 2026", status: "paid", amountInr: inrRoundTo(584220), issuedAt: "2026-06-01" },
  { id: "INV-2026-04", month: "Apr 2026", status: "paid", amountInr: inrRoundTo(548910), issuedAt: "2026-05-01" },
  { id: "INV-2026-03", month: "Mar 2026", status: "paid", amountInr: inrRoundTo(521330), issuedAt: "2026-04-01" },
  { id: "INV-2026-02", month: "Feb 2026", status: "paid", amountInr: inrRoundTo(498650), issuedAt: "2026-03-01" },
  { id: "INV-2026-07", month: "Jul 2026 (in progress)", status: "draft", amountInr: 0, issuedAt: "2026-08-01" },
];

/* ---- Budgets ---- */
export const BUDGETS: Budget[] = [
  {
    env: "production",
    monthlyCapInr: 600000,
    rules: [
      { id: "r1", threshold: 70, channels: ["email:finance-ops"], action: "Notify finance-ops", severity: "info" },
      { id: "r2", threshold: 90, channels: ["email:finance-ops", "slack:#billing"], action: "Escalate to Slack #billing", severity: "warn" },
      { id: "r3", threshold: 100, channels: ["slack:#billing", "pagerduty"], action: "Freeze non-critical batch jobs", severity: "critical" },
    ],
  },
  {
    env: "sandbox",
    monthlyCapInr: 40000,
    rules: [
      { id: "r4", threshold: 80, channels: ["email:devrel"], action: "Notify devrel", severity: "warn" },
      { id: "r5", threshold: 100, channels: ["email:devrel"], action: "Suspend sandbox keys", severity: "critical" },
    ],
  },
];

export type AlertEvent = { id: string; when: string; ruleId: string; env: Env; message: string };
export const ALERT_HISTORY: AlertEvent[] = [
  { id: "a1", when: "2026-07-19 14:02", ruleId: "r1", env: "production", message: "Prod spend crossed 70% of monthly cap" },
  { id: "a2", when: "2026-07-14 09:11", ruleId: "r4", env: "sandbox", message: "Sandbox spend crossed 80% of monthly cap" },
  { id: "a3", when: "2026-07-06 22:47", ruleId: "r1", env: "production", message: "Prod spend crossed 70% (recovered)" },
];

/* ---- Formatting ---- */
export function inr(n: number): string {
  return "₹" + Math.round(n).toLocaleString("en-IN");
}
export function inrCompact(n: number): string {
  if (n >= 1_00_00_000) return `₹${(n / 1_00_00_000).toFixed(2)} Cr`;
  if (n >= 1_00_000) return `₹${(n / 1_00_000).toFixed(2)} L`;
  if (n >= 1_000) return `₹${(n / 1_000).toFixed(1)}k`;
  return `₹${Math.round(n)}`;
}

export function serviceById(id: string): Service | undefined {
  return SERVICES.find((s) => s.id === id);
}

/** Usage in service-native units derived from spend + unit cost. */
export function usageUnits(spend: number, unitCost: number): number {
  if (unitCost <= 0) return 0;
  return spend / unitCost;
}
