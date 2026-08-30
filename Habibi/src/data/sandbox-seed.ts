import { chunks as kbChunks, documents as kbDocs } from "./kb-seed";
import type { Guardrails, PersonaState } from "./prompt-studio-seed";

export type Difficulty = "easy" | "medium" | "hard";
export type Role = "bot" | "customer" | "system";

export const INTENT_KEYS = [
  "balance_query",
  "dispute",
  "hardship",
  "waiver_request",
  "payment_intent",
  "upsell_opportunity",
  "escalation",
  "out_of_scope",
] as const;

export type IntentKey = (typeof INTENT_KEYS)[number];

export type SandboxChunkMeta = {
  docTitle?: string | null;
  heading?: string | null;
  snippet?: string | null;
};

declare global {
  interface Window {
    __sandboxChunkMeta?: Record<string, SandboxChunkMeta>;
  }
}

/** Cache live RAG chunk titles for seed fallback lookups. */
export function mergeSandboxChunkMeta(
  hits: Array<{
    chunkId: string;
    docTitle?: string | null;
    heading?: string | null;
    snippet?: string | null;
  }>,
): void {
  if (typeof window === "undefined" || hits.length === 0) return;
  const map = (window.__sandboxChunkMeta ??= {});
  for (const c of hits) {
    if (!c.chunkId) continue;
    map[c.chunkId] = {
      docTitle: c.docTitle ?? null,
      heading: c.heading ?? null,
      snippet: c.snippet ?? null,
    };
  }
}

export const INTENT_LABEL: Record<IntentKey, string> = {
  balance_query: "Balance / dues query",
  dispute: "Dispute",
  hardship: "Hardship",
  waiver_request: "Waiver request",
  payment_intent: "Payment intent",
  upsell_opportunity: "Upsell opportunity",
  escalation: "Escalation",
  out_of_scope: "Out of scope",
};

export type Persona = {
  name: string;
  phoneLast4: string;
  product: string;
  dpd: number;
  overdue: number;
  mood: string;
  language: string;
};

export type ScenarioTurn = {
  customer: string;
  expectedIntent: IntentKey;
  expectedSentiment: number; // -1..1
  botTemplate: string; // {trait} placeholders resolved at runtime
  chunkIds?: string[];
};

export type Scenario = {
  id: string;
  title: string;
  summary: string;
  difficulty: Difficulty;
  intents: IntentKey[];
  persona: Persona;
  openingBot: string;
  turns: ScenarioTurn[];
};

export type KbSnapshot = { id: string; label: string; note: string };

export const KB_SNAPSHOTS: KbSnapshot[] = [
  { id: "current", label: "Current", note: "Live index" },
  { id: "2026-07-15", label: "2026-07-15 snapshot", note: "Post FAQ refresh" },
  { id: "2026-07-01", label: "2026-07-01 snapshot", note: "Baseline" },
];

export type SandboxTurn = {
  id: string;
  role: Role;
  text: string;
  ts: number;
  intent?: IntentKey;
  intentScores?: Record<IntentKey, number>;
  sentiment?: number;
  chunkIds?: string[];
  /** Live RAG hits with doc titles — preferred over seed chunkTitle lookup. */
  chunks?: Array<{
    chunkId: string;
    docId?: string | null;
    docTitle?: string | null;
    heading?: string | null;
    snippet?: string | null;
    score?: number | null;
  }>;
  latencyMs?: number;
  tokens?: number;
  guardrailFlags?: string[];
  systemKind?: "info" | "warn" | "success";
};

// ---------- pick some real chunk ids from KB ----------
function pickChunks(match: string, n = 3): string[] {
  const m = match.toLowerCase();
  const hits = kbChunks.filter(
    (c) => c.text.toLowerCase().includes(m) || c.heading.toLowerCase().includes(m),
  );
  const pool = hits.length > 0 ? hits : kbChunks;
  return pool.slice(0, n).map((c) => c.id);
}

export function chunkTitle(id: string): { doc: string; heading: string; snippet: string } | null {
  const live = (typeof window !== "undefined" ? window.__sandboxChunkMeta : undefined)?.[id];
  if (live) {
    return {
      doc: live.docTitle || id,
      heading: live.heading || "",
      snippet: (live.snippet || "").slice(0, 160),
    };
  }
  const c = kbChunks.find((k) => k.id === id);
  if (!c) return null;
  const d = kbDocs.find((x) => x.id === c.docId);
  return { doc: d?.title ?? c.docId, heading: c.heading, snippet: c.text.slice(0, 160) };
}

// ---------- scenarios ----------
export const SCENARIOS: Scenario[] = [
  {
    id: "angry-waiver",
    title: "Angry customer — waiver dispute",
    summary: "Customer is furious about a late fee and demands it be waived immediately.",
    difficulty: "hard",
    intents: ["waiver_request", "escalation"],
    persona: {
      name: "Rahul Sharma",
      phoneLast4: "4821",
      product: "Personal Loan",
      dpd: 12,
      overdue: 18450,
      mood: "angry",
      language: "English",
    },
    openingBot:
      "Hello, this is {agent_name} calling from {bank_name} regarding your loan account. This call is recorded for quality. Am I speaking with {customer_name}?",
    turns: [
      {
        customer: "Yes it's me. Why are you charging me a late fee? This is ridiculous!",
        expectedIntent: "waiver_request",
        expectedSentiment: -0.7,
        botTemplate:
          "I hear you, and I'm sorry for the frustration. Your EMI of ₹18,450 was due on the 5th and the late fee is ₹450 per our policy. Let me see how I can help.",
        chunkIds: pickChunks("late fee"),
      },
      {
        customer: "I want it waived. I've been a customer for 5 years.",
        expectedIntent: "waiver_request",
        expectedSentiment: -0.6,
        botTemplate:
          "I completely understand loyalty matters. I'm not able to waive it directly, but I can request a one-time goodwill review from our team if you settle the EMI today.",
        chunkIds: pickChunks("goodwill"),
      },
      {
        customer: "That's not good enough. Transfer me to your manager.",
        expectedIntent: "escalation",
        expectedSentiment: -0.8,
        botTemplate:
          "Absolutely. I'm routing you to a senior specialist now. Please stay on the line.",
        chunkIds: [],
      },
    ],
  },
  {
    id: "confused-first",
    title: "Confused first-time defaulter",
    summary: "Customer doesn't understand what they owe or why.",
    difficulty: "easy",
    intents: ["balance_query"],
    persona: {
      name: "Priya Iyer",
      phoneLast4: "9034",
      product: "Credit Card",
      dpd: 4,
      overdue: 6320,
      mood: "confused",
      language: "English",
    },
    openingBot:
      "Hi, this is {agent_name} from {bank_name}. This call is recorded. Am I speaking with {customer_name}?",
    turns: [
      {
        customer: "Yes, but I don't understand why you're calling.",
        expectedIntent: "balance_query",
        expectedSentiment: -0.1,
        botTemplate:
          "No problem. Your credit card ending 9034 has an outstanding of ₹6,320 due on the 8th. Would you like a quick breakdown?",
        chunkIds: pickChunks("outstanding balance"),
      },
      {
        customer: "Yes please, what does it include?",
        expectedIntent: "balance_query",
        expectedSentiment: 0.1,
        botTemplate:
          "It's ₹5,900 minimum due plus ₹420 in interest. Paying the full statement balance avoids further interest.",
        chunkIds: pickChunks("minimum due"),
      },
      {
        customer: "Okay, how can I pay it?",
        expectedIntent: "payment_intent",
        expectedSentiment: 0.4,
        botTemplate:
          "You can pay via UPI, net-banking, or I can SMS you a secure payment link right now. Which do you prefer?",
        chunkIds: pickChunks("payment methods"),
      },
    ],
  },
  {
    id: "hardship",
    title: "Hardship — recent job loss",
    summary: "Customer lost their job and can't pay this month.",
    difficulty: "hard",
    intents: ["hardship", "escalation"],
    persona: {
      name: "Anil Kumar",
      phoneLast4: "1177",
      product: "Home Loan",
      dpd: 22,
      overdue: 42800,
      mood: "distressed",
      language: "English",
    },
    openingBot:
      "Hello, this is {agent_name} from {bank_name}. This call is recorded. Am I speaking with {customer_name}?",
    turns: [
      {
        customer: "Yes. Look, I lost my job last month. I can't pay right now.",
        expectedIntent: "hardship",
        expectedSentiment: -0.7,
        botTemplate:
          "I'm really sorry to hear that, {customer_name}. Let's find something workable together. We have hardship options like a short-term deferral or EMI restructuring.",
        chunkIds: pickChunks("hardship"),
      },
      {
        customer: "How does the deferral work?",
        expectedIntent: "hardship",
        expectedSentiment: -0.2,
        botTemplate:
          "A deferral pauses your EMI for up to 3 months; interest accrues but no late fee. It needs a quick eligibility check. Would you like me to start it?",
        chunkIds: pickChunks("deferral"),
      },
      {
        customer: "Yes please, start it.",
        expectedIntent: "payment_intent",
        expectedSentiment: 0.2,
        botTemplate:
          "I'll route you to a hardship specialist who can complete the paperwork with you now.",
        chunkIds: [],
      },
    ],
  },
  {
    id: "pay-today",
    title: "Wants to pay today (happy path)",
    summary: "Straightforward: customer wants to clear dues on the call.",
    difficulty: "easy",
    intents: ["payment_intent"],
    persona: {
      name: "Neha Verma",
      phoneLast4: "5522",
      product: "Auto Loan",
      dpd: 3,
      overdue: 12200,
      mood: "cooperative",
      language: "English",
    },
    openingBot:
      "Hi {customer_name}, this is {agent_name} from {bank_name}. This call is recorded. Calling about your auto loan EMI.",
    turns: [
      {
        customer: "Yes, I want to clear it right now.",
        expectedIntent: "payment_intent",
        expectedSentiment: 0.6,
        botTemplate:
          "Wonderful. The amount due is ₹12,200. I can send a UPI link to your registered mobile. Shall I proceed?",
        chunkIds: pickChunks("payment link"),
      },
      {
        customer: "Yes, send it.",
        expectedIntent: "payment_intent",
        expectedSentiment: 0.7,
        botTemplate:
          "Link sent. Once you pay, you'll get an SMS confirmation. Is there anything else I can help you with today?",
        chunkIds: [],
      },
    ],
  },
  {
    id: "dispute-txn",
    title: "Disputed card transaction",
    summary: "Customer claims a transaction was not made by them.",
    difficulty: "medium",
    intents: ["dispute"],
    persona: {
      name: "Sanjay Menon",
      phoneLast4: "7710",
      product: "Credit Card",
      dpd: 0,
      overdue: 0,
      mood: "concerned",
      language: "English",
    },
    openingBot:
      "Hello, this is {agent_name} from {bank_name}. This call is recorded. How can I help?",
    turns: [
      {
        customer: "There's a ₹8,000 charge I did not make.",
        expectedIntent: "dispute",
        expectedSentiment: -0.5,
        botTemplate:
          "I understand, and I'll help you dispute it. Can you tell me the merchant name and approximate date?",
        chunkIds: pickChunks("dispute"),
      },
      {
        customer: "It says GLOBAL-EMART, three days ago.",
        expectedIntent: "dispute",
        expectedSentiment: -0.3,
        botTemplate:
          "Got it. I'm raising a chargeback ticket. You'll get a reference number by SMS within a minute. The temporary credit will appear in 3–5 business days.",
        chunkIds: pickChunks("chargeback"),
      },
    ],
  },
  {
    id: "emi-restructure",
    title: "EMI restructure request",
    summary: "Customer wants to reduce monthly EMI by extending tenure.",
    difficulty: "medium",
    intents: ["hardship"],
    persona: {
      name: "Rekha Nair",
      phoneLast4: "3390",
      product: "Personal Loan",
      dpd: 8,
      overdue: 21000,
      mood: "worried",
      language: "English",
    },
    openingBot:
      "Hi {customer_name}, {agent_name} from {bank_name} here. Call is recorded. How can I help?",
    turns: [
      {
        customer: "My EMI is too high. Can I extend the tenure to reduce it?",
        expectedIntent: "hardship",
        expectedSentiment: -0.3,
        botTemplate:
          "Yes, we can look at that. Extending tenure lowers monthly EMI but increases total interest. Want me to walk through a sample restructure?",
        chunkIds: pickChunks("tenure"),
      },
      {
        customer: "Yes, show me.",
        expectedIntent: "hardship",
        expectedSentiment: 0.1,
        botTemplate:
          "For your outstanding of ₹2.4L: current EMI ~₹21,000 for 12 months, restructured to 18 months ~₹14,500. I can transfer you to a specialist to finalise.",
        chunkIds: pickChunks("restructure"),
      },
    ],
  },
  {
    id: "wrong-number",
    title: "Wrong number / verification fails",
    summary: "The person on the line is not the customer of record.",
    difficulty: "easy",
    intents: ["out_of_scope"],
    persona: {
      name: "Unknown",
      phoneLast4: "0000",
      product: "—",
      dpd: 0,
      overdue: 0,
      mood: "neutral",
      language: "English",
    },
    openingBot:
      "Hello, this is {agent_name} from {bank_name}. This call is recorded. Am I speaking with Rahul Sharma?",
    turns: [
      {
        customer: "No, you have the wrong number.",
        expectedIntent: "out_of_scope",
        expectedSentiment: -0.2,
        botTemplate:
          "I apologise for the disturbance. I'll update our records to prevent further calls. Thank you and have a good day.",
        chunkIds: pickChunks("wrong number"),
      },
    ],
  },
  {
    id: "legal-threat",
    title: "Legal threat — auto-escalation trigger",
    summary: "Customer threatens legal action; bot should escalate immediately.",
    difficulty: "hard",
    intents: ["escalation"],
    persona: {
      name: "Vikram Joshi",
      phoneLast4: "8804",
      product: "Credit Card",
      dpd: 45,
      overdue: 62100,
      mood: "hostile",
      language: "English",
    },
    openingBot:
      "Hello {customer_name}, {agent_name} from {bank_name}. This call is recorded. Calling regarding your outstanding balance.",
    turns: [
      {
        customer: "If you call me again I'll take you to court!",
        expectedIntent: "escalation",
        expectedSentiment: -0.9,
        botTemplate:
          "I understand you're upset. I'll immediately escalate this to our resolution team so they can assist you directly.",
        chunkIds: pickChunks("escalation"),
      },
    ],
  },
  {
    id: "vernacular",
    title: "Vernacular speaker (Hindi)",
    summary: "Customer prefers Hindi; bot should switch languages.",
    difficulty: "medium",
    intents: ["balance_query"],
    persona: {
      name: "Kavita Devi",
      phoneLast4: "2245",
      product: "Home Loan",
      dpd: 5,
      overdue: 15600,
      mood: "neutral",
      language: "Hindi",
    },
    openingBot:
      "Hello {customer_name}, {agent_name} from {bank_name}. Call recorded. Am I speaking with {customer_name}?",
    turns: [
      {
        customer: "Haan, lekin mujhe Hindi mein baat karni hai.",
        expectedIntent: "balance_query",
        expectedSentiment: 0.0,
        botTemplate:
          "Bilkul, {customer_name} ji. Aapke home loan ki ₹15,600 ki EMI 5 tareek ko baaki hai. Kya main aapko bhugtaan link bhej doon?",
        chunkIds: pickChunks("home loan"),
      },
      {
        customer: "Haan, bhej dijiye.",
        expectedIntent: "payment_intent",
        expectedSentiment: 0.5,
        botTemplate: "Link bhej diya hai. Bhugtaan ke baad SMS aa jayega. Aur kuch madad chahiye?",
        chunkIds: [],
      },
    ],
  },
  {
    id: "upsell-good",
    title: "Upsell — pre-approved good payer",
    summary: "Customer is current on dues and eligible for a top-up loan.",
    difficulty: "medium",
    intents: ["upsell_opportunity", "payment_intent"],
    persona: {
      name: "Arjun Reddy",
      phoneLast4: "6631",
      product: "Personal Loan",
      dpd: 0,
      overdue: 0,
      mood: "positive",
      language: "English",
    },
    openingBot:
      "Hi {customer_name}, {agent_name} from {bank_name}. Call is recorded. Just a quick courtesy call.",
    turns: [
      {
        customer: "Sure, what's up?",
        expectedIntent: "balance_query",
        expectedSentiment: 0.4,
        botTemplate:
          "Thanks for keeping your account in great standing. Based on your history, you're pre-approved for a top-up of ₹1.5L at a special rate. Would you like details?",
        chunkIds: pickChunks("top-up"),
      },
      {
        customer: "Interesting, tell me more.",
        expectedIntent: "upsell_opportunity",
        expectedSentiment: 0.6,
        botTemplate:
          "It's a 12-month top-up, no additional paperwork, disbursal same day. I can email the offer letter. Shall I?",
        chunkIds: pickChunks("offer"),
      },
      {
        customer: "Yes, email me.",
        expectedIntent: "payment_intent",
        expectedSentiment: 0.7,
        botTemplate: "Sent. You'll receive it in a minute. Anything else I can help with?",
        chunkIds: [],
      },
    ],
  },
];

// ---------- intent classifier (keyword-based) ----------
const INTENT_KEYWORDS: Record<IntentKey, string[]> = {
  balance_query: ["balance", "outstanding", "how much", "what do i owe", "dues"],
  dispute: [
    "dispute",
    "didn't make",
    "not me",
    "unauthorised",
    "unauthorized",
    "wrong charge",
    "chargeback",
  ],
  hardship: [
    "job",
    "lost",
    "cannot pay",
    "can't pay",
    "difficult",
    "hardship",
    "defer",
    "restructure",
    "tenure",
  ],
  waiver_request: ["waive", "waiver", "remove fee", "cancel fee", "goodwill"],
  payment_intent: ["pay", "settle", "clear", "upi", "link", "net banking", "netbanking"],
  upsell_opportunity: ["top-up", "top up", "offer", "loan", "credit limit", "upgrade"],
  escalation: ["manager", "supervisor", "court", "legal", "lawyer", "ombudsman", "police"],
  out_of_scope: ["wrong number", "not me", "who is this"],
};

const ALL_INTENTS: IntentKey[] = Object.keys(INTENT_KEYWORDS) as IntentKey[];

export function classifyIntent(text: string): {
  top: IntentKey;
  scores: Record<IntentKey, number>;
} {
  const t = text.toLowerCase();
  const raw = {} as Record<IntentKey, number>;
  let total = 0;
  for (const k of ALL_INTENTS) {
    let s = 0;
    for (const kw of INTENT_KEYWORDS[k]) if (t.includes(kw)) s += 1;
    raw[k] = s;
    total += s;
  }
  if (total === 0) {
    ALL_INTENTS.forEach((k) => (raw[k] = k === "out_of_scope" ? 0.35 : 0.09));
  } else {
    ALL_INTENTS.forEach((k) => (raw[k] = raw[k] / total));
  }
  const top = ALL_INTENTS.reduce((a, b) => (raw[a] >= raw[b] ? a : b));
  return { top, scores: raw };
}

// ---------- sentiment (lexicon) ----------
const POS = [
  "thanks",
  "thank you",
  "great",
  "wonderful",
  "yes",
  "please",
  "good",
  "happy",
  "ok",
  "okay",
  "sure",
  "interesting",
];
const NEG = [
  "angry",
  "ridiculous",
  "terrible",
  "hate",
  "never",
  "won't",
  "cannot",
  "can't",
  "difficult",
  "wrong",
  "court",
  "legal",
  "lawyer",
  "manager",
  "no",
];

export function estimateSentiment(text: string): number {
  const t = ` ${text.toLowerCase()} `;
  let s = 0;
  POS.forEach((w) => {
    if (t.includes(` ${w} `) || t.includes(`${w},`) || t.includes(`${w}.`)) s += 0.2;
  });
  NEG.forEach((w) => {
    if (t.includes(` ${w} `) || t.includes(`${w},`) || t.includes(`${w}.`) || t.includes(`${w}!`))
      s -= 0.25;
  });
  if (text.includes("!")) s -= 0.15;
  return Math.max(-1, Math.min(1, Number(s.toFixed(2))));
}

// ---------- bot reply generator ----------
export type BotReply = {
  text: string;
  chunkIds: string[];
  latencyMs: number;
  tokens: number;
  guardrailFlags: string[];
  intent: IntentKey;
  intentScores: Record<IntentKey, number>;
};

function fillTemplate(t: string, persona: Persona): string {
  return t
    .replaceAll("{customer_name}", persona.name)
    .replaceAll("{agent_name}", "Priya")
    .replaceAll("{bank_name}", "HDFC Bank")
    .replaceAll("{language}", persona.language);
}

export function generateBotReply(
  scenario: Scenario,
  turnIndex: number,
  customerText: string,
  personaState: PersonaState,
  guardrails: Guardrails,
): BotReply {
  const turn = scenario.turns[turnIndex];
  const { top, scores } = classifyIntent(customerText);
  const guardrailFlags: string[] = [];
  let text = turn
    ? fillTemplate(turn.botTemplate, scenario.persona)
    : "I understand. Let me help you with that.";
  const chunkIds = turn?.chunkIds ?? [];

  // guardrails
  if (guardrails.neverPromiseWaiver && top === "waiver_request") {
    text =
      "I hear you. I'm not able to promise a waiver — but I can raise a goodwill review request for you if you settle today.";
    guardrailFlags.push("waiver-blocked");
  }
  if (guardrails.escalateLegal && top === "escalation") {
    guardrailFlags.push("auto-escalate");
  }
  if (
    guardrails.alwaysDiscloseRecording &&
    turnIndex === 0 &&
    !text.toLowerCase().includes("recorded")
  ) {
    text = "This call is recorded for quality and compliance. " + text;
  }

  // persona tone tweaks
  const empathy = personaState.traits.empathy;
  if (empathy > 70 && !text.toLowerCase().includes("understand") && top !== "payment_intent") {
    text = "I understand. " + text;
  }
  const upsell = personaState.traits.upsell;
  if (upsell > 60 && top === "payment_intent" && scenario.id !== "legal-threat") {
    text =
      text + " By the way, you may also be pre-approved for a small top-up — I can share details.";
  }

  const tokens = Math.round(text.length / 4) + chunkIds.length * 40;
  const latencyMs = Math.round(180 + Math.random() * 420);
  return { text, chunkIds, latencyMs, tokens, guardrailFlags, intent: top, intentScores: scores };
}
