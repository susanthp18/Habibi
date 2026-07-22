export type Channel = "voice" | "whatsapp" | "sms";
export type HandlerKind = "bot" | "human";
export type Risk = "low" | "medium" | "high";

export type ActiveCall = {
  id: string;
  handler: { kind: HandlerKind; name: string; initials?: string };
  customer: string;
  accountTail: string;
  channel: Channel;
  topic: string;
  durationSec: number;
  sentiment: number; // -1..1
  sentimentTrend: number; // recent delta
  risk: Risk;
  lastLine: string;
  language: string;
};

export type AlertKind = "sentiment_drop" | "compliance" | "long_hold" | "escalation";

export type FloorAlert = {
  id: string;
  callId: string;
  kind: AlertKind;
  severity: 1 | 2 | 3; // 3 = most severe
  reason: string;
  at: string; // relative time label
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

export const activeCalls: ActiveCall[] = [
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
  },
  {
    id: "c-02",
    handler: { kind: "bot", name: "Kaia v2.4" },
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
    handler: { kind: "bot", name: "Kaia v2.4" },
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
    handler: { kind: "bot", name: "Kaia v2.4" },
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
  },
  {
    id: "c-07",
    handler: { kind: "bot", name: "Kaia v2.4" },
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
  },
  {
    id: "c-08",
    handler: { kind: "bot", name: "Kaia v2.4" },
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
  },
  {
    id: "c-10",
    handler: { kind: "bot", name: "Kaia v2.4" },
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
    handler: { kind: "bot", name: "Kaia v2.4" },
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
    handler: { kind: "bot", name: "Kaia v2.4" },
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
    handler: { kind: "bot", name: "Kaia v2.4" },
    customer: "Kavya Reddy",
    accountTail: "9931",
    channel: "voice",
    topic: "Waiver request",
    durationSec: 176,
    sentiment: 0.08,
    sentimentTrend: 0.04,
    risk: "low",
    lastLine: "A one-time late-fee waiver of ₹450 is available.",
    language: "TE-IN",
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
    handler: { kind: "bot", name: "Kaia v2.4" },
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

export const baselineStats = {
  callsInProgress: activeCalls.length,
  avgSentiment: 0.06,
  escalationRate: 0.12, // 12%
  queueDepth: 7,
  botContainment: 0.78, // 78%
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
  },
  {
    id: "a-02",
    callId: "c-06",
    kind: "sentiment_drop",
    severity: 3,
    reason: "3 negative turns in 20s · raised voice detected",
    at: "22s ago",
  },
  {
    id: "a-03",
    callId: "c-03",
    kind: "sentiment_drop",
    severity: 2,
    reason: "Bot loop suspected · customer repeating phrase",
    at: "48s ago",
  },
  {
    id: "a-04",
    callId: "c-04",
    kind: "long_hold",
    severity: 1,
    reason: "Call exceeds 8m — check if hold time is compliant",
    at: "1m ago",
  },
];

export const channelLabel: Record<Channel, string> = {
  voice: "Voice",
  whatsapp: "WhatsApp",
  sms: "SMS",
};
