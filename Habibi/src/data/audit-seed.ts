// Audit Trail (Call History) — synthetic immutable log of interactions.
// All records are read-only; helpers here are pure filters/formatters.

export type Channel = "voice" | "whatsapp" | "sms";
export type Direction = "inbound" | "outbound";
export type HandlerKind = "bot" | "human" | "handoff";
export type Speaker = "bot" | "agent" | "customer" | "system";
export type SentimentBucket = "positive" | "neutral" | "negative";

export type Disposition =
  | "PTP Captured"
  | "Payment Made"
  | "Info Query Resolved"
  | "Dispute Raised"
  | "Callback Scheduled"
  | "Escalated"
  | "No Answer"
  | "Voicemail"
  | "DND — Not Contacted";

export type CallFlag =
  | "compliance-miss"
  | "sentiment-drop"
  | "escalation"
  | "silence"
  | "abuse-detected"
  | "high-value";

export interface DisclosureCheck {
  id: string;
  label: string;
  read: boolean;
  atSec?: number;
}

export interface TranscriptTurn {
  id: string;
  t: number; // seconds from call start
  speaker: Speaker;
  text: string;
}

export interface SentimentPoint {
  t: number; // seconds
  v: number; // -1..+1
}

export interface CallRecord {
  id: string;
  startedAt: string; // ISO
  duration: number; // seconds
  channel: Channel;
  direction: Direction;
  handledBy: { kind: HandlerKind; agent?: string; bot?: string };
  customerId: string;
  customerName: string;
  phoneMasked: string;
  accountId: string;
  disposition: Disposition;
  summary: string;
  tags: string[];
  flags: CallFlag[];
  avgSentiment: number; // -1..+1
  sentimentSeries: SentimentPoint[];
  disclosures: DisclosureCheck[];
  transcript: TranscriptTurn[];
  redactionApplied: boolean;
  hash: string;
  ragHits: number;
  latencyMs: number;
  routing: string[];
}

// ---------- helpers ----------

const CUSTOMERS: Array<{ id: string; name: string; phone: string; account: string }> = [
  { id: "vikram-rao", name: "Vikram Rao", phone: "+91 98••••2210", account: "HDFC-CC-4487" },
  { id: "anita-desai", name: "Anita Desai", phone: "+91 90••••7745", account: "HDFC-PL-9902" },
  { id: "priya-menon", name: "Priya Menon", phone: "+91 98••••3421", account: "HDFC-RL-8842" },
  { id: "rahul-shetty", name: "Rahul Shetty", phone: "+91 99••••1128", account: "HDFC-AL-3390" },
  { id: "kavya-iyer", name: "Kavya Iyer", phone: "+91 87••••6612", account: "HDFC-CC-7781" },
  { id: "sameer-khan", name: "Sameer Khan", phone: "+91 96••••4408", account: "HDFC-PL-2216" },
  { id: "neha-gupta", name: "Neha Gupta", phone: "+91 88••••9903", account: "HDFC-CC-1194" },
  { id: "arjun-nair", name: "Arjun Nair", phone: "+91 97••••3378", account: "HDFC-RL-5540" },
];

const AGENTS = ["Aarav K.", "Priya Nair", "Arjun Mehta", "Sara Khan", "Rohit Verma", "Meera Joshi"];
const BOTS = ["BigBound v2.4", "CollectionsBot v2.4", "WebChatBot"];

const DISPOSITIONS: Disposition[] = [
  "PTP Captured",
  "Payment Made",
  "Info Query Resolved",
  "Dispute Raised",
  "Callback Scheduled",
  "Escalated",
  "No Answer",
  "Voicemail",
  "DND — Not Contacted",
];

const DISCLOSURE_TEMPLATE: Array<{ id: string; label: string }> = [
  { id: "recording", label: "Call recording notice" },
  { id: "mini-miranda", label: "Mini-Miranda debt collection disclosure" },
  { id: "dnd", label: "DND / opt-out reminder" },
  { id: "dispute-rights", label: "Right-to-dispute notice" },
];

// Deterministic PRNG so seed data is stable across reloads.
function rng(seedStr: string) {
  let h = 2166136261;
  for (let i = 0; i < seedStr.length; i++) {
    h ^= seedStr.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return () => {
    h += 0x6d2b79f5;
    let t = h;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pick<T>(rand: () => number, arr: T[]): T {
  return arr[Math.floor(rand() * arr.length)]!;
}

function hashLike(seed: string): string {
  const r = rng(seed + "-hash");
  const hex = "0123456789abcdef";
  let out = "";
  for (let i = 0; i < 12; i++) out += hex[Math.floor(r() * 16)];
  return out;
}

function buildTranscript(
  rand: () => number,
  duration: number,
  handler: HandlerKind,
  disposition: Disposition,
): TranscriptTurn[] {
  const turns: TranscriptTurn[] = [];
  let t = 0;
  const agentSpeaker: Speaker = handler === "bot" ? "bot" : "agent";
  const openings: Record<Speaker, string[]> = {
    bot: [
      "Hello, this is BigBound calling from HDFC Retail Collections on a recorded line. Am I speaking with the account holder?",
      "Hi, I'm BigBound, an AI assistant from HDFC. This call is recorded for training and compliance.",
    ],
    agent: [
      "Good afternoon, this is a recorded call from HDFC Collections. My name is Aarav — may I confirm your identity?",
      "Hi, calling from HDFC Retail. This is a recorded line — could I verify your date of birth?",
    ],
    customer: ["Yes, speaking.", "Yes, that's me."],
    system: [""],
  };
  turns.push({ id: "t0", t: 0, speaker: agentSpeaker, text: pick(rand, openings[agentSpeaker]) });
  t += 6 + Math.floor(rand() * 4);
  turns.push({ id: "t1", t, speaker: "customer", text: pick(rand, openings.customer) });
  t += 4;

  const body: Array<{ speaker: Speaker; text: string }> = [];
  if (disposition === "PTP Captured") {
    body.push(
      { speaker: agentSpeaker, text: "Your account shows an overdue amount of ₹12,180 due since 5 Aug. Can we agree on a date for the payment?" },
      { speaker: "customer", text: "Yes, I'll pay by the 20th — salary is credited on the 18th." },
      { speaker: agentSpeaker, text: "Noted. I'll set up a promise-to-pay for 20 Aug for ₹12,180. You'll receive a WhatsApp reminder two days before." },
      { speaker: "customer", text: "That works. Please don't call before 10 AM." },
      { speaker: agentSpeaker, text: "Understood — I've updated your preferred contact window." },
    );
  } else if (disposition === "Dispute Raised") {
    body.push(
      { speaker: "customer", text: "I already paid on the 3rd but you're showing overdue. This is the second time." },
      { speaker: agentSpeaker, text: "I'm sorry for the trouble. Could you share the UTR or reference number for the payment?" },
      { speaker: "customer", text: "UTR is HDFC0043221198. It was ₹12,180 exactly." },
      { speaker: agentSpeaker, text: "Thank you. I'm raising a dispute now — you'll get an SMS with the ticket ID within five minutes. Late fees are paused while we investigate." },
    );
  } else if (disposition === "Info Query Resolved") {
    body.push(
      { speaker: "customer", text: "I just wanted to know my outstanding balance and next EMI date." },
      { speaker: agentSpeaker, text: "Your current outstanding is ₹48,720. The next EMI of ₹12,180 is due on 5 Aug." },
      { speaker: "customer", text: "Can I get a statement on WhatsApp?" },
      { speaker: agentSpeaker, text: "Sure — I've sent the six-month statement to your registered WhatsApp number." },
    );
  } else if (disposition === "Escalated") {
    body.push(
      { speaker: "customer", text: "I don't want to talk to a bot. Get me a person." },
      { speaker: "bot", text: "Absolutely, transferring you to a human agent now — please hold." },
      { speaker: "system", text: "— Call transferred to Aarav K. —" },
      { speaker: "agent", text: "Hi, this is Aarav. I've reviewed the notes — how can I help?" },
      { speaker: "customer", text: "Your reminders are too frequent. Stop them or I'm closing the card." },
      { speaker: "agent", text: "I've registered a DND for voice reminders and reduced SMS to weekly only." },
    );
  } else if (disposition === "Callback Scheduled") {
    body.push(
      { speaker: "customer", text: "I'm in a meeting — call me back at 4 PM tomorrow." },
      { speaker: agentSpeaker, text: "No problem — I've scheduled a callback for tomorrow at 4 PM on this number." },
    );
  } else if (disposition === "Payment Made") {
    body.push(
      { speaker: agentSpeaker, text: "You have an outstanding of ₹4,220. Would you like to pay now via UPI link?" },
      { speaker: "customer", text: "Yes, send it." },
      { speaker: "system", text: "— Payment link sent via SMS —" },
      { speaker: "customer", text: "Done." },
      { speaker: agentSpeaker, text: "Payment of ₹4,220 confirmed. Thank you — your account is now current." },
    );
  } else if (disposition === "DND — Not Contacted") {
    body.push(
      { speaker: "system", text: "— DND window active. Call ended before outreach. —" },
    );
  } else if (disposition === "Voicemail" || disposition === "No Answer") {
    body.push(
      { speaker: "system", text: "— No answer after 4 rings. Call ended. —" },
    );
  }

  for (let i = 0; i < body.length; i++) {
    const gap = 6 + Math.floor(rand() * 8);
    t += gap;
    if (t >= duration - 3) break;
    turns.push({ id: `t${i + 2}`, t, speaker: body[i].speaker, text: body[i].text });
  }

  if (t < duration - 4 && disposition !== "No Answer" && disposition !== "Voicemail") {
    turns.push({
      id: `tend`,
      t: Math.max(t + 4, duration - 3),
      speaker: agentSpeaker,
      text: "Is there anything else I can help you with today? Thank you for your time.",
    });
  }
  return turns;
}

function buildSentiment(rand: () => number, duration: number, disposition: Disposition): SentimentPoint[] {
  const pts: SentimentPoint[] = [];
  const step = 4;
  let v = 0.1 + (rand() - 0.5) * 0.2;
  const target =
    disposition === "Escalated" || disposition === "Dispute Raised"
      ? -0.5
      : disposition === "Payment Made" || disposition === "PTP Captured"
        ? 0.5
        : 0.05;
  for (let t = 0; t <= duration; t += step) {
    const drift = (target - v) * 0.12;
    v = Math.max(-1, Math.min(1, v + drift + (rand() - 0.5) * 0.15));
    pts.push({ t, v: Number(v.toFixed(2)) });
  }
  return pts;
}

function makeCall(i: number): CallRecord {
  const rand = rng(`call-${i}`);
  const cust = CUSTOMERS[i % CUSTOMERS.length]!;
  const duration = 40 + Math.floor(rand() * 380); // 40s–7m
  const daysAgo = Math.floor(rand() * 30);
  const started = new Date(Date.now() - daysAgo * 86400_000 - Math.floor(rand() * 86400_000));
  const channel: Channel = rand() < 0.75 ? "voice" : rand() < 0.6 ? "whatsapp" : "sms";
  const disposition = pick(rand, DISPOSITIONS);
  const handlerKind: HandlerKind =
    disposition === "Escalated" ? "handoff" : rand() < 0.55 ? "bot" : "human";
  const handledBy =
    handlerKind === "bot"
      ? { kind: "bot" as const, bot: pick(rand, BOTS) }
      : handlerKind === "human"
        ? { kind: "human" as const, agent: pick(rand, AGENTS) }
        : { kind: "handoff" as const, bot: pick(rand, BOTS), agent: pick(rand, AGENTS) };

  const sentimentSeries = buildSentiment(rand, duration, disposition);
  const avgSentiment = Number(
    (sentimentSeries.reduce((s, p) => s + p.v, 0) / Math.max(1, sentimentSeries.length)).toFixed(2),
  );

  const flags: CallFlag[] = [];
  if (avgSentiment < -0.3) flags.push("sentiment-drop");
  if (disposition === "Escalated") flags.push("escalation");
  if (rand() < 0.15) flags.push("compliance-miss");
  if (duration < 60 && (disposition === "No Answer" || disposition === "Voicemail")) flags.push("silence");
  if (rand() < 0.08) flags.push("abuse-detected");
  if (rand() < 0.12) flags.push("high-value");

  const disclosures: DisclosureCheck[] = DISCLOSURE_TEMPLATE.map((d, di) => {
    const shouldRead =
      disposition !== "No Answer" && disposition !== "Voicemail" && disposition !== "DND — Not Contacted";
    const read = shouldRead && rand() > (flags.includes("compliance-miss") && di < 2 ? 0.5 : 0.08);
    return {
      ...d,
      read,
      atSec: read ? Math.floor(2 + di * 6 + rand() * 4) : undefined,
    };
  });

  const transcript = buildTranscript(rand, duration, handlerKind, disposition);

  const summary = (() => {
    switch (disposition) {
      case "PTP Captured":
        return `Customer confirmed identity and agreed to pay ₹${(8000 + Math.floor(rand() * 8000)).toLocaleString()} by end of month. Preferred WhatsApp reminder set.`;
      case "Payment Made":
        return "Customer paid outstanding in full via UPI link during the call. Account is now current.";
      case "Info Query Resolved":
        return "Customer requested balance and next EMI date. Six-month statement sent on WhatsApp.";
      case "Dispute Raised":
        return "Customer disputes a payment showing as unposted. Dispute raised, late fees paused pending review.";
      case "Escalated":
        return "Customer refused bot interaction; transferred to human. DND for voice reminders registered.";
      case "Callback Scheduled":
        return "Customer was busy; callback scheduled for the following afternoon.";
      case "No Answer":
        return "No answer after 4 rings. Retry scheduled per policy.";
      case "Voicemail":
        return "Voicemail reached; no message left per compliance policy.";
      case "DND — Not Contacted":
        return "DND window active at dial time. No outreach attempted.";
    }
  })();

  const tags: string[] = [];
  if (disposition === "PTP Captured") tags.push("PTP", "reminder-set");
  if (disposition === "Dispute Raised") tags.push("dispute", "late-fee-hold");
  if (disposition === "Payment Made") tags.push("upi", "paid-in-full");
  if (flags.includes("compliance-miss")) tags.push("QA-review");
  if (flags.includes("sentiment-drop")) tags.push("empathy-coach");

  return {
    id: `CL-${(100000 + i).toString()}`,
    startedAt: started.toISOString(),
    duration,
    channel,
    direction: rand() < 0.7 ? "outbound" : "inbound",
    handledBy,
    customerId: cust.id,
    customerName: cust.name,
    phoneMasked: cust.phone,
    accountId: cust.account,
    disposition,
    summary,
    tags,
    flags,
    avgSentiment,
    sentimentSeries,
    disclosures,
    transcript,
    redactionApplied: true,
    hash: hashLike(`call-${i}`),
    ragHits: Math.floor(rand() * 6),
    latencyMs: 320 + Math.floor(rand() * 640),
    routing:
      handlerKind === "handoff"
        ? ["IVR", "Bot: BigBound", "Handoff: Aarav"]
        : handlerKind === "bot"
          ? ["IVR", "Bot: BigBound"]
          : ["IVR", "Agent Queue"],
  };
}

export const calls: CallRecord[] = Array.from({ length: 42 }, (_, i) => makeCall(i)).sort(
  (a, b) => new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime(),
);

// ---------- filters ----------

export type DateRange = "today" | "7d" | "30d" | "all";

export interface AuditFilterState {
  q: string;
  dateRange: DateRange;
  channel: "all" | Channel;
  handler: "all" | HandlerKind;
  agent: "all" | string;
  disposition: "all" | Disposition;
  sentiment: "all" | SentimentBucket;
  flaggedOnly: boolean;
}

export const defaultFilters: AuditFilterState = {
  q: "",
  dateRange: "30d",
  channel: "all",
  handler: "all",
  agent: "all",
  disposition: "all",
  sentiment: "all",
  flaggedOnly: false,
};

export function sentimentBucket(v: number): SentimentBucket {
  if (v >= 0.2) return "positive";
  if (v <= -0.2) return "negative";
  return "neutral";
}

export function filterCalls(all: CallRecord[], f: AuditFilterState): CallRecord[] {
  const now = Date.now();
  const cutoff =
    f.dateRange === "today"
      ? now - 86400_000
      : f.dateRange === "7d"
        ? now - 7 * 86400_000
        : f.dateRange === "30d"
          ? now - 30 * 86400_000
          : 0;
  const q = f.q.trim().toLowerCase();
  return all.filter((c) => {
    if (cutoff && new Date(c.startedAt).getTime() < cutoff) return false;
    if (f.channel !== "all" && c.channel !== f.channel) return false;
    if (f.handler !== "all" && c.handledBy.kind !== f.handler) return false;
    if (f.agent !== "all" && c.handledBy.agent !== f.agent) return false;
    if (f.disposition !== "all" && c.disposition !== f.disposition) return false;
    if (f.sentiment !== "all" && sentimentBucket(c.avgSentiment) !== f.sentiment) return false;
    if (f.flaggedOnly && c.flags.length === 0) return false;
    if (q) {
      const hay =
        `${c.id} ${c.customerName} ${c.phoneMasked} ${c.accountId} ${c.disposition} ${c.summary} ${c.transcript.map((t) => t.text).join(" ")}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

export function listAgents(): string[] {
  const s = new Set<string>();
  for (const c of calls) if (c.handledBy.agent) s.add(c.handledBy.agent);
  return Array.from(s).sort();
}

export const ALL_DISPOSITIONS = DISPOSITIONS;

// ---------- formatters ----------

export function formatDuration(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function sentimentColor(v: number): string {
  if (v >= 0.2) return "var(--sentiment-positive)";
  if (v <= -0.2) return "var(--sentiment-negative)";
  return "var(--sentiment-neutral)";
}
