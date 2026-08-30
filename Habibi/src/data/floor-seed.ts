import type { OfferPolicy } from "@/lib/offer-policy";
import type { AuthorityPolicy } from "@/lib/authority-policy";

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

export const LIVE_QA_STATUS_LABEL: Record<string, string> = {
  would_barge: "Would barge",
  barge: "Barge",
  whisper: "Whisper",
  inbox: "Inbox",
  flagged: "QA flag",
};

export const LIVE_QA_STATUS_TONE: Record<string, "warning" | "danger" | "discovery" | "selected"> =
  {
    would_barge: "warning",
    barge: "danger",
    whisper: "discovery",
    inbox: "selected",
    flagged: "warning",
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

export const topicOptions = [
  "Dues query",
  "Payment failed",
  "PTP capture",
  "Dispute",
  "EMI restructure",
  "Statement request",
  "Waiver request",
  "Upsell — top-up loan",
  "Callback request",
] as const;

export const actionLabel: Record<FloorAction, string> = {
  barge: "Take over",
  whisper: "Whisper",
  listen: "Listen",
  inbox: "Open inbox",
};

const THREAT = /ombudsman|threat|lawyer|rbi|abuse|police/i;

function inferAction(c: {
  channel: Channel;
  handler: { kind: HandlerKind };
  pendingHandoff?: boolean;
  lastLine?: string;
  topic?: string;
}): FloorAction {
  if (c.channel === "whatsapp" || c.channel === "sms") return "inbox";
  if (c.pendingHandoff) return "barge";
  if (THREAT.test(c.lastLine || "") || /dispute/i.test(c.topic || "")) {
    return c.handler.kind === "bot" ? "barge" : "whisper";
  }
  return c.handler.kind === "human" ? "listen" : "listen";
}

type SeedCall = Omit<
  ActiveCall,
  | "flags"
  | "pendingHandoff"
  | "outstanding"
  | "customerRisk"
  | "dnd"
  | "recentTurns"
  | "recommendedAction"
  | "customerId"
  | "accountId"
> &
  Partial<ActiveCall>;

function hydrate(raw: SeedCall): ActiveCall {
  const pendingHandoff = raw.pendingHandoff ?? false;
  return {
    ...raw,
    flags: raw.flags ?? [],
    pendingHandoff,
    outstanding: raw.outstanding ?? 0,
    customerRisk: raw.customerRisk ?? raw.risk,
    dnd: raw.dnd ?? false,
    recentTurns: raw.recentTurns ?? [{ speaker: "customer", text: raw.lastLine }],
    recommendedAction: raw.recommendedAction ?? inferAction({ ...raw, pendingHandoff }),
    customerId: raw.customerId,
    accountId: raw.accountId ?? `ACC-••${raw.accountTail}`,
    offerPolicy: raw.offerPolicy,
    authorityPolicy: raw.authorityPolicy,
  };
}

const _rawCalls: SeedCall[] = [
  {
    id: "c-01",
    handler: { kind: "human", name: "Aarav K.", initials: "AK" },
    customer: "Priya Menon",
    accountTail: "1207",
    channel: "voice",
    topic: "Dispute",
    durationSec: 342,
    sentiment: 0.28,
    sentimentTrend: 0.18,
    risk: "high",
    lastLine: "Perfect. I'm capturing a Promise-to-Pay: 12,180 now…",
    language: "EN-IN",
    offerPolicy: {
      status: "suppressed",
      suppressionReason: "open_dispute",
      suppressionLabel: "Open dispute — do not pitch",
      reasonCodes: ["open_dispute"],
    },
  },
  {
    id: "c-02",
    handler: { kind: "bot", name: "BigBound v2.4" },
    customer: "Rohit Sharma",
    accountTail: "8843",
    channel: "voice",
    topic: "Dues query",
    durationSec: 68,
    sentiment: 0.05,
    sentimentTrend: 0.02,
    risk: "low",
    lastLine: "Your current outstanding balance is ₹8,940.",
    language: "HI-IN",
  },
  {
    id: "c-03",
    handler: { kind: "bot", name: "BigBound v2.4" },
    customer: "Neha Verma",
    accountTail: "4471",
    channel: "voice",
    topic: "Payment failed",
    durationSec: 121,
    sentiment: -0.42,
    sentimentTrend: -0.22,
    risk: "medium",
    lastLine: "I already told you — the money was cut from my account!",
    language: "EN-IN",
    flags: ["loop_detected"],
    pendingHandoff: true,
    recommendedAction: "barge",
  },
  {
    id: "c-04",
    handler: { kind: "human", name: "Meera D.", initials: "MD" },
    customer: "Anil Kapoor",
    accountTail: "9012",
    channel: "voice",
    topic: "EMI restructure",
    durationSec: 512,
    sentiment: 0.15,
    sentimentTrend: 0.05,
    risk: "medium",
    lastLine: "Yes ma'am, tenure extension by 12 months should work.",
    language: "EN-IN",
  },
  {
    id: "c-05",
    handler: { kind: "bot", name: "BigBound v2.4" },
    customer: "Deepa Iyer",
    accountTail: "3320",
    channel: "whatsapp",
    topic: "Statement request",
    durationSec: 22,
    sentiment: 0.35,
    sentimentTrend: 0.1,
    risk: "low",
    lastLine: "Sending your July statement to your registered email now.",
    language: "EN-IN",
  },
  {
    id: "c-06",
    handler: { kind: "human", name: "Karan S.", initials: "KS" },
    customer: "Vikram Rathi",
    accountTail: "7788",
    channel: "voice",
    topic: "Waiver request",
    durationSec: 198,
    sentiment: -0.55,
    sentimentTrend: -0.3,
    risk: "high",
    lastLine: "This is ridiculous, I've been a customer for eight years!",
    language: "HI-IN",
    flags: ["abuse-detected"],
    recommendedAction: "whisper",
  },
  {
    id: "c-07",
    handler: { kind: "bot", name: "BigBound v2.4" },
    customer: "Sana Ali",
    accountTail: "2210",
    channel: "voice",
    topic: "PTP capture",
    durationSec: 84,
    sentiment: 0.22,
    sentimentTrend: 0.08,
    risk: "medium",
    lastLine: "Confirming: ₹5,000 by 25 July. Is that correct?",
    language: "EN-IN",
    offerPolicy: {
      status: "ready",
      productId: "topup-loan",
      productName: "Top-up Loan",
      suggestedAmount: 150000,
      talkTrack: "You may be eligible for a Top-up Loan of about one point five lakh rupees.",
      reasonCodes: ["eligible"],
    },
  },
  {
    id: "c-08",
    handler: { kind: "bot", name: "BigBound v2.4" },
    customer: "Manoj Pillai",
    accountTail: "6655",
    channel: "voice",
    topic: "Upsell — top-up loan",
    durationSec: 143,
    sentiment: 0.4,
    sentimentTrend: 0.12,
    risk: "low",
    lastLine: "You're pre-approved for a top-up of up to ₹1,50,000.",
    language: "EN-IN",
    offerPolicy: {
      status: "presented",
      productId: "topup-loan",
      productName: "Top-up Loan",
      suggestedAmount: 150000,
      talkTrack: "You're pre-approved for a top-up of up to one point five lakh rupees.",
      presented: true,
      reasonCodes: ["eligible"],
    },
  },
  {
    id: "c-09",
    handler: { kind: "human", name: "Ritu B.", initials: "RB" },
    customer: "Farhan Qureshi",
    accountTail: "5501",
    channel: "voice",
    topic: "Dispute",
    durationSec: 421,
    sentiment: -0.7,
    sentimentTrend: -0.15,
    risk: "high",
    lastLine: "Escalate this or I'm going to the ombudsman.",
    language: "EN-IN",
    flags: ["auto-escalate"],
    pendingHandoff: true,
    recommendedAction: "barge",
    offerPolicy: {
      status: "suppressed",
      suppressionReason: "open_dispute",
      suppressionLabel: "Open dispute — do not pitch",
      reasonCodes: ["open_dispute"],
    },
  },
  {
    id: "c-10",
    handler: { kind: "bot", name: "BigBound v2.4" },
    customer: "Lakshmi R.",
    accountTail: "0098",
    channel: "voice",
    topic: "Callback request",
    durationSec: 34,
    sentiment: 0.1,
    sentimentTrend: 0.0,
    risk: "low",
    lastLine: "Scheduling a callback for tomorrow 5 PM. Confirmed?",
    language: "TA-IN",
  },
  {
    id: "c-11",
    handler: { kind: "bot", name: "BigBound v2.4" },
    customer: "Suresh Nair",
    accountTail: "3312",
    channel: "voice",
    topic: "Dues query",
    durationSec: 55,
    sentiment: 0.02,
    sentimentTrend: 0.0,
    risk: "low",
    lastLine: "Your next EMI of ₹6,540 is due on 5 August.",
    language: "EN-IN",
  },
  {
    id: "c-12",
    handler: { kind: "human", name: "Aisha P.", initials: "AP" },
    customer: "Reena Joshi",
    accountTail: "7742",
    channel: "voice",
    topic: "EMI restructure",
    durationSec: 267,
    sentiment: 0.18,
    sentimentTrend: 0.06,
    risk: "medium",
    lastLine: "I'll email the revised schedule within the hour.",
    language: "EN-IN",
  },
  {
    id: "c-13",
    handler: { kind: "bot", name: "BigBound v2.4" },
    customer: "Prakash G.",
    accountTail: "1178",
    channel: "whatsapp",
    topic: "Payment failed",
    durationSec: 41,
    sentiment: -0.15,
    sentimentTrend: -0.05,
    risk: "medium",
    lastLine: "Let me check the gateway status for that UTR…",
    language: "EN-IN",
  },
  {
    id: "c-14",
    handler: { kind: "bot", name: "BigBound v2.4" },
    customer: "Kavya Reddy",
    accountTail: "9931",
    channel: "voice",
    topic: "Waiver request",
    durationSec: 176,
    sentiment: 0.08,
    sentimentTrend: 0.04,
    risk: "low",
    lastLine:
      "I've logged a fee-waiver review against the authority ceiling — I won't quote an amount until that's back.",
    language: "TE-IN",
    authorityPolicy: {
      status: "shadow",
      mode: "shadow",
      feeType: "late_fee",
      verdict: "cap_inr",
      approvedAmount: 500,
      capAmount: 500,
      reason: "cap_available",
      reasonLabel: "In-policy goodwill ceiling",
      talkTrack:
        "Goodwill ceiling is ₹500. You may reverse up to that. If they insist on more, escalate without quoting a larger number.",
      reasonCodes: ["cap_available"],
    },
  },
  {
    id: "c-15",
    handler: { kind: "human", name: "Nikhil V.", initials: "NV" },
    customer: "Ajay Malhotra",
    accountTail: "4408",
    channel: "voice",
    topic: "Dues query",
    durationSec: 89,
    sentiment: 0.25,
    sentimentTrend: 0.1,
    risk: "low",
    lastLine: "Yes sir, that's your correct outstanding.",
    language: "EN-IN",
  },
  {
    id: "c-16",
    handler: { kind: "bot", name: "BigBound v2.4" },
    customer: "Pooja S.",
    accountTail: "2255",
    channel: "sms",
    topic: "Statement request",
    durationSec: 12,
    sentiment: 0.3,
    sentimentTrend: 0.0,
    risk: "low",
    lastLine: "Statement link sent via SMS.",
    language: "EN-IN",
  },
];

export const activeCalls: ActiveCall[] = _rawCalls.map(hydrate);

export const baselineStats = {
  callsInProgress: activeCalls.length,
  avgSentiment: 0.06,
  criticalAlerts: 2,
  queueDepth: 3,
  agentsAvailable: 2,
  agentsOnCall: 6,
  botAtRisk: 2,
  longestWaitSec: 143,
};

export const initialAlerts: FloorAlert[] = [
  {
    id: "a-01",
    callId: "c-09",
    kind: "sentiment_drop",
    severity: 3,
    reason: "Sentiment −0.7 · customer threatening ombudsman",
    at: "just now",
    recommendedAction: "barge",
  },
  {
    id: "a-02",
    callId: "c-06",
    kind: "sentiment_drop",
    severity: 3,
    reason: "3 negative turns in 20s · raised voice detected",
    at: "22s ago",
    recommendedAction: "whisper",
  },
  {
    id: "a-03",
    callId: "c-03",
    kind: "loop_detected",
    severity: 2,
    reason: "Bot loop suspected · customer repeating phrase",
    at: "48s ago",
    recommendedAction: "barge",
  },
  {
    id: "a-04",
    callId: "c-04",
    kind: "long_hold",
    severity: 1,
    reason: "Call exceeds 8m — check if hold time is compliant",
    at: "1m ago",
    recommendedAction: "listen",
  },
];

export const seedAgents: FloorAgent[] = [
  {
    userId: "aarav",
    name: "Aarav K.",
    initials: "AK",
    status: "on_call",
    sinceAt: new Date().toISOString(),
    interactionId: "c-01",
    customer: "Priya Menon",
  },
  {
    userId: "meera",
    name: "Meera D.",
    initials: "MD",
    status: "on_call",
    sinceAt: new Date().toISOString(),
    interactionId: "c-04",
    customer: "Anil Kapoor",
  },
  {
    userId: "karan",
    name: "Karan S.",
    initials: "KS",
    status: "on_call",
    sinceAt: new Date().toISOString(),
    interactionId: "c-06",
    customer: "Vikram Rathi",
  },
  {
    userId: "ritu",
    name: "Ritu B.",
    initials: "RB",
    status: "on_call",
    sinceAt: new Date().toISOString(),
    interactionId: "c-09",
    customer: "Farhan Qureshi",
  },
  {
    userId: "aisha",
    name: "Aisha P.",
    initials: "AP",
    status: "on_call",
    sinceAt: new Date().toISOString(),
    interactionId: "c-12",
    customer: "Reena Joshi",
  },
  {
    userId: "nikhil",
    name: "Nikhil V.",
    initials: "NV",
    status: "on_call",
    sinceAt: new Date().toISOString(),
    interactionId: "c-15",
    customer: "Ajay Malhotra",
  },
  {
    userId: "sara",
    name: "Sara Khan",
    initials: "SK",
    status: "available",
    sinceAt: new Date().toISOString(),
  },
  {
    userId: "arjun",
    name: "Arjun Mehta",
    initials: "AM",
    status: "wrap_up",
    sinceAt: new Date().toISOString(),
  },
  {
    userId: "neha",
    name: "Neha Iyer",
    initials: "NI",
    status: "on_break",
    sinceAt: new Date().toISOString(),
  },
];

export const channelLabel: Record<Channel, string> = {
  voice: "Voice",
  whatsapp: "WhatsApp",
  sms: "SMS",
};
