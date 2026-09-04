/**
 * Domain / wire types for the dashboard surface.
 *
 * Lived in a `data/*-seed.ts` mock factory. Moved here so live `api/`
 * modules do not import their contract from fixtures (WP-048).
 */

export type Trend = { date: string; value: number };
export type StackedPoint = { date: string; voice: number; whatsapp: number; chat: number };
export type Segment = "all" | "card" | "personal" | "auto";
export type TeamFilter = "all" | "bot" | "human";
export type Range = "today" | "7d" | "30d" | "qtd";
// `delta` is nullable on purpose. "Flat" and "there is no prior period to
// compare against" are different claims, and the server used to render the
// second as the first with a hardcoded number. null → the chip is omitted.
export type HeroKpi = {
  label: string;
  value: string;
  raw: number;
  unit?: string;
  delta: number | null; // vs prior period, negative = down
  deltaGood: "down" | "up"; // which direction is good
  sub: string;
  spark: number[];
};
export type Kpi = {
  key: string;
  label: string;
  value: string;
  delta: number | null;
  deltaGood: "down" | "up";
  sub?: string;
  spark: number[];
  tone?: "default" | "brand" | "success" | "warning";
};
// -------- Leaderboard --------
export type LeaderRow = {
  rank: number;
  name: string;
  team: string;
  calls: number;
  aht: string;
  // null when the rep captured no leads / handled no scored calls in the
  // window. Previously synthesised as `12 + rank * 1.3`, which looked like a
  // ranking and was an index.
  upsell: number | null; // %
  csat: number | null; // 0-1
};
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
