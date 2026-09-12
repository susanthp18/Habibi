/**
 * Domain / wire types for the upsell surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
 */

export type LeadStage = "interested" | "contacted" | "qualified" | "won" | "lost";
export type LeadSource = "bot_voice" | "bot_chat" | "agent";
export type Sentiment = "positive" | "neutral" | "negative";
export type Priority = "low" | "normal" | "high";
export type Team = "Retail Sales" | "Cards Sales" | "Insurance";
export type FollowUpChannel = "voice" | "whatsapp" | "email" | "sms";
export interface Product {
  id: string;
  name: string;
  category: "Loan" | "Card" | "Insurance";
  minTicket: number;
  maxTicket: number;
  indicativeROI: string; // e.g. "12.5% p.a."
  description: string;
}
export interface EligibilityFlag {
  label: string;
  ok: boolean;
  detail: string;
}
export interface FollowUp {
  id?: string;
  at: string; // ISO
  channel: FollowUpChannel;
  note: string;
  done: boolean;
}
export type LeadEventKind =
  | "created"
  | "stage_moved"
  | "assigned"
  | "team_changed"
  | "followup_scheduled"
  | "followup_done"
  | "offer_edited"
  | "won"
  | "lost";
export interface LeadEvent {
  at: string;
  kind: LeadEventKind;
  by: string;
  note?: string;
}
export interface LeadOffer {
  productId: string;
  label: string;
  indicativeAmount: number;
  indicativeROI: string;
}
export interface Lead {
  id: string;
  customerId: string;
  customerName: string;
  accountId: string;
  accountTail: string;
  offer: LeadOffer;
  stage: LeadStage;
  capturedAt: string;
  sourceCallId?: string;
  source: LeadSource;
  sentimentAtCapture: Sentiment;
  /**
   * Polarity in [-1, 1], matching agent_core/sentiment.py — negative values are
   * real and mean the customer sounded unhappy.
   *
   * This was rendered as `score * 100` with a "%" suffix, which read a genuinely
   * negative lead as "-25%". It is a polarity, not a confidence.
   */
  sentimentScore: number;
  transcriptSnippet: string;
  eligibilityFlags: EligibilityFlag[];
  /** Display name, or null when the lead is unassigned (bot-captured leads are). */
  owner: string | null;
  team: Team | string | null;
  nextFollowUpAt?: string | null;
  followUps: FollowUp[];
  priority: Priority;
  /** Null when the product has no ticket band to derive an indicative value from. */
  estimatedValue: number | null;
  closedAt?: string | null;
  lossReason?: string | null;
  wonAmount?: number | null;
  events: LeadEvent[];
}
export interface Filters {
  search: string;
  team: "all" | Team;
  owner: string; // "all" or name
  productId: "all" | string;
  source: "all" | LeadSource;
  sentiments: Sentiment[];
  priorities: Priority[];
  myQueue: boolean;
}
export interface Metrics {
  openLeads: number;
  pipelineValue: number;
  wonWeek: number;
  wonWeekAmount: number;
  conversionRate: number; // 0..100
  avgDaysToClose: number;
  perStage: Record<LeadStage, { count: number; amount: number }>;
}
