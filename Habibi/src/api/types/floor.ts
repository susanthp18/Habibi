/**
 * Domain / wire types for the floor surface.
 *
 * Lived in a `data/*-seed.ts` mock factory. Moved here so live `api/`
 * modules do not import their contract from fixtures (WP-048).
 */

import type { AuthorityPolicy } from "@/lib/authority-policy";
import type { OfferPolicy } from "@/lib/offer-policy";

export type Channel = "voice" | "whatsapp" | "sms";
export type HandlerKind = "bot" | "human";
export type Risk = "low" | "medium" | "high";
export type FloorAction = "barge" | "whisper" | "listen" | "inbox";
export type AgentFloorStatus = "available" | "on_call" | "wrap_up" | "on_break" | "offline";
export type RecentTurn = { speaker: string; text: string };
export type ActiveCall = {
  id: string;
  handler: { kind: HandlerKind; name: string; initials?: string };
  customer: string;
  customerId?: string;
  accountId?: string;
  accountTail: string;
  conversationId?: string | null;
  handlerUserId?: string | null;
  channel: Channel;
  topic: string;
  durationSec: number;
  sentiment: number; // -1..1
  sentimentTrend: number; // recent delta
  risk: Risk;
  lastLine: string;
  language: string;
  flags: string[];
  pendingHandoff: boolean;
  outstanding: number;
  customerRisk: string;
  dnd: boolean;
  recentTurns: RecentTurn[];
  recommendedAction: FloorAction;
  agentCard?: { botId: string; displayName: string } | null;
  offerPolicy?: OfferPolicy | null;
  authorityPolicy?: AuthorityPolicy | null;
  liveQa?: {
    status?: string;
    reason?: string | null;
    reasonCodes?: string[];
    recommendedAction?: string;
    audioCapable?: boolean;
    mode?: string | null;
  } | null;
};
export type AlertKind =
  "sentiment_drop" | "compliance" | "long_hold" | "escalation" | "silence" | "loop_detected";
export type FloorAlert = {
  id: string;
  callId: string;
  kind: AlertKind;
  severity: 1 | 2 | 3; // 3 = most severe
  reason: string;
  at: string; // relative time label
  recommendedAction: FloorAction;
};
export type FloorAgent = {
  userId: string;
  name: string;
  initials: string;
  status: AgentFloorStatus;
  sinceAt: string;
  interactionId?: string | null;
  customer?: string | null;
};
