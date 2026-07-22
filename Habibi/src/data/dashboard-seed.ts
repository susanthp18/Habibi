// Executive Dashboard synthetic data
// All numbers are illustrative but internally consistent.

export type Trend = { date: string; value: number };
export type StackedPoint = { date: string; voice: number; whatsapp: number; chat: number };

export type Segment = "all" | "card" | "personal" | "auto";
export type TeamFilter = "all" | "bot" | "human";
export type Range = "today" | "7d" | "30d" | "qtd";

export type HeroKpi = {
  label: string;
  value: string;
  raw: number;
  unit?: string;
  delta: number; // vs prior period, negative = down
  deltaGood: "down" | "up"; // which direction is good
  sub: string;
  spark: number[];
};

export type Kpi = {
  key: string;
  label: string;
  value: string;
  delta: number;
  deltaGood: "down" | "up";
  spark: number[];
  tone?: "default" | "brand" | "success" | "warning";
};

function daysAgo(n: number) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function series(days: number, base: number, variance: number, drift = 0): Trend[] {
  const out: Trend[] = [];
  let v = base;
  for (let i = days - 1; i >= 0; i--) {
    v = base + drift * (days - i) + (Math.sin(i / 2.7) * variance) / 2 + (Math.random() - 0.5) * variance;
    out.push({ date: daysAgo(i), value: Math.max(0, Math.round(v)) });
  }
  return out;
}

function sparkline(len = 14, base = 50, variance = 12): number[] {
  return Array.from({ length: len }, (_, i) =>
    Math.max(0, Math.round(base + Math.sin(i / 2) * variance + (Math.random() - 0.5) * variance))
  );
}

// -------- Hero KPIs --------
export const heroKpis: HeroKpi[] = [
  {
    label: "Avg Handle Time (AHT)",
    value: "4m 12s",
    raw: 252,
    delta: -18.4,
    deltaGood: "down",
    sub: "vs prior period · target ≤ 5m",
    spark: sparkline(14, 280, 30).map((v) => Math.round(v * 0.9)),
  },
  {
    label: "Upsell Conversion Rate",
    value: "14.6%",
    raw: 14.6,
    unit: "%",
    delta: 3.2,
    deltaGood: "up",
    sub: "eligibility-gated offers accepted",
    spark: sparkline(14, 11, 3),
  },
];

// -------- Secondary KPIs --------
export const kpis: Kpi[] = [
  {
    key: "recovered",
    label: "Total Dues Recovered",
    value: "$2.48M",
    delta: 12.1,
    deltaGood: "up",
    spark: sparkline(14, 85, 20),
    tone: "success",
  },
  {
    key: "recoveryRate",
    label: "Recovery Rate",
    value: "68.4%",
    delta: 2.7,
    deltaGood: "up",
    spark: sparkline(14, 65, 6),
  },
  {
    key: "containment",
    label: "Bot Containment",
    value: "71.2%",
    delta: 5.9,
    deltaGood: "up",
    spark: sparkline(14, 66, 8),
    tone: "brand",
  },
  {
    key: "ptp",
    label: "Promise-Kept Rate",
    value: "61.8%",
    delta: -1.4,
    deltaGood: "up",
    spark: sparkline(14, 62, 5),
    tone: "warning",
  },
  {
    key: "csat",
    label: "Avg Sentiment / CSAT",
    value: "0.62",
    delta: 0.08,
    deltaGood: "up",
    spark: sparkline(14, 55, 8),
  },
  {
    key: "calls",
    label: "Calls Handled",
    value: "8,412",
    delta: 6.3,
    deltaGood: "up",
    spark: sparkline(14, 260, 40),
  },
];

// -------- Trend series (30 days) --------
export const recoveryTrend: Trend[] = series(30, 78000, 22000, 400).map((p) => ({
  date: p.date,
  value: Math.round(p.value),
}));

export const callVolumeStacked: StackedPoint[] = Array.from({ length: 30 }, (_, i) => {
  const day = daysAgo(29 - i);
  const base = 220 + Math.sin(i / 3) * 60 + (Math.random() - 0.5) * 40;
  const voice = Math.max(80, Math.round(base));
  const whatsapp = Math.max(30, Math.round(base * 0.55 + (Math.random() - 0.5) * 30));
  const chat = Math.max(15, Math.round(base * 0.3 + (Math.random() - 0.5) * 20));
  return { date: day, voice, whatsapp, chat };
});

export const sentimentDistribution = {
  positive: 58,
  neutral: 27,
  negative: 15,
};

export const botVsHuman = [
  { name: "Contained by bot", value: 5987, color: "var(--brand-primary)" },
  { name: "Escalated to human", value: 1638, color: "var(--warning)" },
  { name: "Direct to human", value: 787, color: "var(--brand-navy)" },
];

// -------- Leaderboard --------
export type LeaderRow = {
  rank: number;
  name: string;
  team: string;
  calls: number;
  aht: string;
  upsell: number; // %
  csat: number; // 0-1
};

export const leaderboard: LeaderRow[] = [
  { rank: 1, name: "Priya Nair", team: "Card Collections", calls: 214, aht: "3m 41s", upsell: 22.4, csat: 0.83 },
  { rank: 2, name: "Arjun Mehta", team: "Personal Loans", calls: 198, aht: "3m 58s", upsell: 19.7, csat: 0.79 },
  { rank: 3, name: "Sara Khan", team: "Card Collections", calls: 187, aht: "4m 04s", upsell: 18.9, csat: 0.81 },
  { rank: 4, name: "David Chen", team: "Auto Loans", calls: 176, aht: "4m 12s", upsell: 16.2, csat: 0.76 },
  { rank: 5, name: "Meera Iyer", team: "Personal Loans", calls: 168, aht: "4m 22s", upsell: 15.8, csat: 0.74 },
  { rank: 6, name: "Rohan Verma", team: "Card Collections", calls: 161, aht: "4m 31s", upsell: 14.4, csat: 0.72 },
];

// -------- At-risk accounts --------
export type AtRiskAccount = {
  id: string;
  name: string;
  account: string;
  outstanding: number;
  daysPastDue: number;
  risk: "critical" | "high" | "medium";
  lastContact: string;
  product: "Card" | "Personal Loan" | "Auto Loan";
};

export const atRiskAccounts: AtRiskAccount[] = [
  { id: "a1", name: "Anita Desai", account: "AC-88214", outstanding: 12480, daysPastDue: 92, risk: "critical", lastContact: "2d ago", product: "Personal Loan" },
  { id: "a2", name: "Vikram Rao", account: "AC-77410", outstanding: 8640, daysPastDue: 74, risk: "critical", lastContact: "6h ago", product: "Card" },
  { id: "a3", name: "Neha Kapoor", account: "AC-90112", outstanding: 5210, daysPastDue: 61, risk: "high", lastContact: "1d ago", product: "Card" },
  { id: "a4", name: "James Patel", account: "AC-66803", outstanding: 22100, daysPastDue: 58, risk: "high", lastContact: "3d ago", product: "Auto Loan" },
  { id: "a5", name: "Farah Ahmed", account: "AC-71992", outstanding: 3980, daysPastDue: 45, risk: "high", lastContact: "5h ago", product: "Card" },
  { id: "a6", name: "Rahul Sinha", account: "AC-58004", outstanding: 15300, daysPastDue: 38, risk: "medium", lastContact: "4d ago", product: "Personal Loan" },
];

// Multiplier applied to numbers based on filter selection — cheap way to make
// the dashboard feel responsive to filters without a real backend.
export function filterMultiplier(range: Range, segment: Segment, team: TeamFilter) {
  const r = range === "today" ? 0.05 : range === "7d" ? 0.25 : range === "qtd" ? 2.9 : 1;
  const s = segment === "all" ? 1 : segment === "card" ? 0.55 : segment === "personal" ? 0.3 : 0.15;
  const t = team === "all" ? 1 : team === "bot" ? 0.66 : 0.34;
  return r * s * t;
}
