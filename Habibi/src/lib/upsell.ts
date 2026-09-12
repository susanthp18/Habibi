import type { Filters, Lead, LeadSource, LeadStage } from "@/api/types/upsell";
import { inrCompact } from "@/lib/format";

/** Compact rupees; a lead with no indicative value reads as a dash, not a zero. */
export function fmtMoney(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return inrCompact(n);
}

/**
 * Render sentiment polarity for display.
 *
 * Signed and on a -100..+100 scale so the convention is unambiguous at a
 * glance. Showing `score * 100` with a "%" suffix implied a confidence
 * percentage and printed "-25%" for a negative lead.
 */
export function fmtSentiment(score: number | null | undefined): string {
  if (score === null || score === undefined || Number.isNaN(score)) return "—";
  const scaled = Math.round(score * 100);
  return scaled > 0 ? `+${scaled}` : String(scaled);
}

/** Money for arithmetic (totals, sorting) — absent means zero, not NaN. */
export function moneyValue(n: number | null | undefined): number {
  return n === null || n === undefined || Number.isNaN(n) ? 0 : n;
}

/** The figure a lead contributes to pipeline/closed totals. */
export function leadValue(l: Pick<Lead, "stage" | "wonAmount" | "estimatedValue">): number {
  return moneyValue(l.stage === "won" ? (l.wonAmount ?? l.estimatedValue) : l.estimatedValue);
}

export function fmtRelative(iso: string) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  const abs = Math.abs(diff);
  const sign = diff >= 0 ? "" : "in ";
  const suffix = diff >= 0 ? " ago" : "";
  if (abs < 60) return "just now";
  if (abs < 3600) return `${sign}${Math.round(abs / 60)}m${suffix}`;
  if (abs < 86400) return `${sign}${Math.round(abs / 3600)}h${suffix}`;
  return `${sign}${Math.round(abs / 86400)}d${suffix}`;
}

export const defaultFilters: Filters = {
  search: "",
  team: "all",
  owner: "all",
  productId: "all",
  source: "all",
  sentiments: [],
  priorities: [],
  myQueue: false,
};

// ---------- labels ----------

export const STAGE_ORDER: LeadStage[] = ["interested", "contacted", "qualified", "won", "lost"];

export const STAGE_LABELS: Record<LeadStage, string> = {
  interested: "Interested",
  contacted: "Contacted",
  qualified: "Qualified",
  won: "Won",
  lost: "Lost",
};

export const SOURCE_LABELS: Record<LeadSource, string> = {
  bot_voice: "Bot · Voice",
  bot_chat: "Bot · Chat",
  agent: "Agent",
};
