// Upsell & Leads Manager — synthetic data + mutation helpers.
// Session-scoped in-memory store (no persistence).

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

// ---------- catalog ----------

export const products: Product[] = [
  {
    id: "topup-loan",
    name: "Top-up Loan",
    category: "Loan",
    minTicket: 50_000,
    maxTicket: 1_500_000,
    indicativeROI: "10.75% p.a.",
    description: "Additional loan on an existing personal loan account for eligible customers.",
  },
  {
    id: "debt-consolidation",
    name: "Debt Consolidation",
    category: "Loan",
    minTicket: 100_000,
    maxTicket: 2_500_000,
    indicativeROI: "11.5% p.a.",
    description: "Combine multiple outstanding balances into a single lower-EMI loan.",
  },
  {
    id: "cc-limit-upgrade",
    name: "Credit Card Limit Upgrade",
    category: "Card",
    minTicket: 25_000,
    maxTicket: 500_000,
    indicativeROI: "36% APR (revolving)",
    description:
      "Higher spend limit on an existing credit card; eligibility gated by utilisation and bureau score.",
  },
  {
    id: "personal-loan",
    name: "Personal Loan",
    category: "Loan",
    minTicket: 50_000,
    maxTicket: 2_000_000,
    indicativeROI: "12.5% p.a.",
    description: "Unsecured personal loan pre-approved for salaried customers.",
  },
  {
    id: "gold-loan",
    name: "Gold Loan",
    category: "Loan",
    minTicket: 25_000,
    maxTicket: 1_000_000,
    indicativeROI: "9.5% p.a.",
    description: "Secured loan against gold ornaments at branch valuation.",
  },
  {
    id: "bundled-insurance",
    name: "Bundled Insurance",
    category: "Insurance",
    minTicket: 5_000,
    maxTicket: 50_000,
    indicativeROI: "N/A (premium)",
    description: "Loan-linked accident + hospitalisation cover bundled with existing product.",
  },
];

export const productMap: Record<string, Product> = Object.fromEntries(
  products.map((p) => [p.id, p]),
);

// ---------- utilities ----------

const now = () => new Date();
const iso = (daysAgo: number, hour = 10, min = 0) => {
  const d = now();
  d.setDate(d.getDate() - daysAgo);
  d.setHours(hour, min, 0, 0);
  return d.toISOString();
};
const isoFuture = (daysAhead: number, hour = 10, min = 0) => iso(-daysAhead, hour, min);

/**
 * Format INR for display.
 *
 * Accepts null/undefined/NaN because the API legitimately returns them: a lead
 * captured against a product with no ticket band has no indicative value. This
 * used to be typed `number`, and a null went straight into
 * `n.toLocaleString()` — a TypeError that took the whole board down rather than
 * rendering one dash.
 */
export function fmtMoney(n: number | null | undefined) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (Math.abs(n) >= 1_00_00_000) return `₹${(n / 1_00_00_000).toFixed(2)} Cr`;
  if (Math.abs(n) >= 1_00_000) return `₹${(n / 1_00_000).toFixed(2)} L`;
  if (Math.abs(n) >= 1_000) return `₹${(n / 1_000).toFixed(1)}k`;
  return `₹${n.toLocaleString("en-IN")}`;
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

export function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { day: "2-digit", month: "short" });
}

export function fmtDateTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
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

// ---------- seed helpers ----------

const OWNERS = [
  "Priya Nair",
  "Arjun Mehta",
  "Sara Khan",
  "Meera Iyer",
  "Rahul Verma",
  "Unassigned",
];

const CUSTOMERS: Array<{ id: string; name: string; accountId: string; tail: string }> = [
  { id: "vikram-rao", name: "Vikram Rao", accountId: "AC-77410", tail: "7410" },
  { id: "anita-desai", name: "Anita Desai", accountId: "AC-88214", tail: "8214" },
  { id: "rohit-shah", name: "Rohit Shah", accountId: "AC-55129", tail: "5129" },
  { id: "kavya-menon", name: "Kavya Menon", accountId: "AC-66321", tail: "6321" },
  { id: "irfan-siddiqui", name: "Irfan Siddiqui", accountId: "AC-91002", tail: "1002" },
  { id: "sneha-kapoor", name: "Sneha Kapoor", accountId: "AC-42188", tail: "2188" },
  { id: "manish-agarwal", name: "Manish Agarwal", accountId: "AC-78033", tail: "8033" },
  { id: "deepa-iyer", name: "Deepa Iyer", accountId: "AC-33417", tail: "3417" },
];

function eligFor(productId: string, variant: "clean" | "one-warn" | "two-warn"): EligibilityFlag[] {
  const base: EligibilityFlag[] = [
    { label: "KYC current", ok: true, detail: "Aadhaar & PAN verified · 2024" },
    { label: "Bureau score ≥ 720", ok: true, detail: "Latest bureau: 748 (CIBIL)" },
    { label: "DPD-clean 12 months", ok: true, detail: "No 30+ DPD in last 12 cycles" },
    { label: "Income proof on file", ok: true, detail: "Latest 3 salary slips uploaded" },
    {
      label: "Existing product eligibility",
      ok: true,
      detail: `Eligible for ${productMap[productId]?.name}`,
    },
  ];
  if (variant === "one-warn") {
    base[2] = { label: "DPD-clean 12 months", ok: false, detail: "1× 30-DPD event 4 months ago" };
  }
  if (variant === "two-warn") {
    base[1] = { label: "Bureau score ≥ 720", ok: false, detail: "Bureau 692 — below threshold" };
    base[3] = { label: "Income proof on file", ok: false, detail: "Last slip 5 months old" };
  }
  return base;
}

const snippets: Record<string, string> = {
  "topup-loan":
    "Yeh EMI to theek hai, lekin agar 1 lakh aur mil sakta hai top-up mein toh mujhe interest hoga.",
  "debt-consolidation":
    "I have three cards outstanding — can we combine into one lower EMI? That would really help.",
  "cc-limit-upgrade":
    "My limit is only 80k, please increase it to 2 lakhs — I've been paying full every month.",
  "personal-loan":
    "Actually I need around 3 lakhs for my sister's wedding — what's the pre-approved offer?",
  "gold-loan": "Mere paas thoda gold hai, uspe loan ho jayega? Interest kitna hoga?",
  "bundled-insurance": "Is there any insurance I should add on this loan? Peace of mind types.",
};

interface SeedInput {
  id: string;
  cust: number;
  productId: string;
  stage: LeadStage;
  amount: number;
  team: Team;
  owner: string;
  source: LeadSource;
  sentiment: Sentiment;
  score: number;
  variant: "clean" | "one-warn" | "two-warn";
  priority: Priority;
  daysAgo: number;
  wonAmount?: number;
  lossReason?: string;
  nextFollowUpDaysAhead?: number;
  followUpChannel?: FollowUpChannel;
  followUpNote?: string;
}

/**
 * Seed scores were authored as 0..1 confidences, but the API returns polarity
 * in [-1, 1] — so a "negative" mock lead carried a positive number and mock
 * mode disagreed with live about what the same field meant. Map them onto the
 * real scale, keeping each row consistent with its own label
 * (negative < -0.15 < neutral < 0.15 < positive, as sentiment_label defines).
 */
function toPolarity(sentiment: Sentiment, score: number): number {
  if (sentiment === "negative") return -Math.abs(score);
  if (sentiment === "positive") return Math.abs(score);
  return Number((score - 0.5).toFixed(2));
}

function make(input: SeedInput): Lead {
  const cust = CUSTOMERS[input.cust % CUSTOMERS.length];
  const product = productMap[input.productId];
  const capturedAt = iso(input.daysAgo, 10 + (input.cust % 6));
  const events: LeadEvent[] = [
    {
      at: capturedAt,
      kind: "created",
      by: input.source === "agent" ? input.owner : "System",
      note: `Lead captured from ${input.source === "bot_voice" ? "voice call" : input.source === "bot_chat" ? "chat" : "agent"}`,
    },
  ];
  if (input.stage !== "interested") {
    events.push({
      at: iso(Math.max(0, input.daysAgo - 1), 12),
      kind: "stage_moved",
      by: input.owner,
      note: `Moved to ${input.stage}`,
    });
  }
  const followUps: FollowUp[] =
    input.nextFollowUpDaysAhead !== undefined
      ? [
          {
            at: isoFuture(input.nextFollowUpDaysAhead, 11, 0),
            channel: input.followUpChannel ?? "voice",
            note: input.followUpNote ?? "Discuss offer details and share document checklist.",
            done: false,
          },
        ]
      : [];
  const closedAt =
    input.stage === "won" || input.stage === "lost"
      ? iso(Math.max(0, input.daysAgo - 2), 15)
      : undefined;
  if (input.stage === "won") {
    events.push({
      at: closedAt!,
      kind: "won",
      by: input.owner,
      note: `Disbursed ${fmtMoney(input.wonAmount ?? input.amount)}`,
    });
  }
  if (input.stage === "lost") {
    events.push({
      at: closedAt!,
      kind: "lost",
      by: input.owner,
      note: input.lossReason ?? "Not interested",
    });
  }
  return {
    id: input.id,
    customerId: cust.id,
    customerName: cust.name,
    accountId: cust.accountId,
    accountTail: cust.tail,
    offer: {
      productId: input.productId,
      label: product.name,
      indicativeAmount: input.amount,
      indicativeROI: product.indicativeROI,
    },
    stage: input.stage,
    capturedAt,
    sourceCallId: input.source !== "agent" ? `CALL-${1000 + input.cust * 7}` : undefined,
    source: input.source,
    sentimentAtCapture: input.sentiment,
    sentimentScore: toPolarity(input.sentiment, input.score),
    transcriptSnippet: snippets[input.productId] ?? "Customer expressed interest in the offer.",
    eligibilityFlags: eligFor(input.productId, input.variant),
    owner: input.owner,
    team: input.team,
    nextFollowUpAt: followUps[0]?.at,
    followUps,
    priority: input.priority,
    estimatedValue: input.amount,
    closedAt,
    wonAmount: input.wonAmount,
    lossReason: input.lossReason,
    events,
  };
}

// ---------- store ----------

const _leads: Lead[] = [
  // Interested (top of funnel)
  make({
    id: "LD-1001",
    cust: 0,
    productId: "topup-loan",
    stage: "interested",
    amount: 150_000,
    team: "Retail Sales",
    owner: "Unassigned",
    source: "bot_voice",
    sentiment: "positive",
    score: 0.72,
    variant: "clean",
    priority: "high",
    daysAgo: 0,
  }),
  make({
    id: "LD-1002",
    cust: 1,
    productId: "debt-consolidation",
    stage: "interested",
    amount: 450_000,
    team: "Retail Sales",
    owner: "Priya Nair",
    source: "bot_voice",
    sentiment: "positive",
    score: 0.66,
    variant: "one-warn",
    priority: "high",
    daysAgo: 0,
  }),
  make({
    id: "LD-1003",
    cust: 2,
    productId: "cc-limit-upgrade",
    stage: "interested",
    amount: 200_000,
    team: "Cards Sales",
    owner: "Sara Khan",
    source: "bot_chat",
    sentiment: "neutral",
    score: 0.45,
    variant: "clean",
    priority: "normal",
    daysAgo: 1,
  }),
  make({
    id: "LD-1004",
    cust: 3,
    productId: "personal-loan",
    stage: "interested",
    amount: 300_000,
    team: "Retail Sales",
    owner: "Unassigned",
    source: "bot_voice",
    sentiment: "positive",
    score: 0.78,
    variant: "clean",
    priority: "high",
    daysAgo: 1,
  }),
  make({
    id: "LD-1005",
    cust: 4,
    productId: "gold-loan",
    stage: "interested",
    amount: 80_000,
    team: "Retail Sales",
    owner: "Arjun Mehta",
    source: "bot_chat",
    sentiment: "neutral",
    score: 0.5,
    variant: "clean",
    priority: "normal",
    daysAgo: 2,
  }),
  make({
    id: "LD-1006",
    cust: 5,
    productId: "bundled-insurance",
    stage: "interested",
    amount: 12_000,
    team: "Insurance",
    owner: "Unassigned",
    source: "bot_voice",
    sentiment: "neutral",
    score: 0.55,
    variant: "clean",
    priority: "low",
    daysAgo: 2,
  }),
  make({
    id: "LD-1007",
    cust: 6,
    productId: "topup-loan",
    stage: "interested",
    amount: 100_000,
    team: "Retail Sales",
    owner: "Meera Iyer",
    source: "agent",
    sentiment: "positive",
    score: 0.7,
    variant: "clean",
    priority: "normal",
    daysAgo: 3,
  }),

  // Contacted
  make({
    id: "LD-1008",
    cust: 7,
    productId: "debt-consolidation",
    stage: "contacted",
    amount: 600_000,
    team: "Retail Sales",
    owner: "Priya Nair",
    source: "bot_voice",
    sentiment: "positive",
    score: 0.68,
    variant: "clean",
    priority: "high",
    daysAgo: 3,
    nextFollowUpDaysAhead: 1,
    followUpChannel: "voice",
    followUpNote: "Confirm income docs and pull latest bureau.",
  }),
  make({
    id: "LD-1009",
    cust: 0,
    productId: "cc-limit-upgrade",
    stage: "contacted",
    amount: 100_000,
    team: "Cards Sales",
    owner: "Sara Khan",
    source: "agent",
    sentiment: "neutral",
    score: 0.5,
    variant: "clean",
    priority: "normal",
    daysAgo: 4,
    nextFollowUpDaysAhead: 2,
    followUpChannel: "whatsapp",
    followUpNote: "Send limit-upgrade brochure.",
  }),
  make({
    id: "LD-1010",
    cust: 2,
    productId: "personal-loan",
    stage: "contacted",
    amount: 250_000,
    team: "Retail Sales",
    owner: "Rahul Verma",
    source: "bot_voice",
    sentiment: "positive",
    score: 0.74,
    variant: "clean",
    priority: "high",
    daysAgo: 4,
    nextFollowUpDaysAhead: 0,
    followUpChannel: "voice",
    followUpNote: "Callback at 4pm as customer requested.",
  }),
  make({
    id: "LD-1011",
    cust: 4,
    productId: "topup-loan",
    stage: "contacted",
    amount: 200_000,
    team: "Retail Sales",
    owner: "Arjun Mehta",
    source: "bot_chat",
    sentiment: "positive",
    score: 0.62,
    variant: "one-warn",
    priority: "normal",
    daysAgo: 5,
    nextFollowUpDaysAhead: 3,
  }),

  // Qualified
  make({
    id: "LD-1012",
    cust: 1,
    productId: "debt-consolidation",
    stage: "qualified",
    amount: 550_000,
    team: "Retail Sales",
    owner: "Priya Nair",
    source: "bot_voice",
    sentiment: "positive",
    score: 0.8,
    variant: "clean",
    priority: "high",
    daysAgo: 6,
    nextFollowUpDaysAhead: 1,
    followUpChannel: "voice",
    followUpNote: "Present final offer and rate.",
  }),
  make({
    id: "LD-1013",
    cust: 5,
    productId: "cc-limit-upgrade",
    stage: "qualified",
    amount: 150_000,
    team: "Cards Sales",
    owner: "Sara Khan",
    source: "bot_chat",
    sentiment: "positive",
    score: 0.72,
    variant: "clean",
    priority: "normal",
    daysAgo: 7,
    nextFollowUpDaysAhead: 2,
    followUpChannel: "email",
  }),
  make({
    id: "LD-1014",
    cust: 3,
    productId: "gold-loan",
    stage: "qualified",
    amount: 120_000,
    team: "Retail Sales",
    owner: "Meera Iyer",
    source: "agent",
    sentiment: "positive",
    score: 0.75,
    variant: "clean",
    priority: "high",
    daysAgo: 8,
    nextFollowUpDaysAhead: 0,
    followUpChannel: "voice",
    followUpNote: "Branch valuation appointment today at 3pm.",
  }),

  // Won
  make({
    id: "LD-1015",
    cust: 6,
    productId: "personal-loan",
    stage: "won",
    amount: 400_000,
    wonAmount: 350_000,
    team: "Retail Sales",
    owner: "Rahul Verma",
    source: "bot_voice",
    sentiment: "positive",
    score: 0.82,
    variant: "clean",
    priority: "high",
    daysAgo: 3,
  }),
  make({
    id: "LD-1016",
    cust: 7,
    productId: "cc-limit-upgrade",
    stage: "won",
    amount: 100_000,
    wonAmount: 100_000,
    team: "Cards Sales",
    owner: "Sara Khan",
    source: "bot_chat",
    sentiment: "positive",
    score: 0.78,
    variant: "clean",
    priority: "normal",
    daysAgo: 5,
  }),
  make({
    id: "LD-1017",
    cust: 0,
    productId: "bundled-insurance",
    stage: "won",
    amount: 15_000,
    wonAmount: 15_000,
    team: "Insurance",
    owner: "Meera Iyer",
    source: "agent",
    sentiment: "positive",
    score: 0.7,
    variant: "clean",
    priority: "low",
    daysAgo: 9,
  }),
  make({
    id: "LD-1018",
    cust: 2,
    productId: "topup-loan",
    stage: "won",
    amount: 250_000,
    wonAmount: 250_000,
    team: "Retail Sales",
    owner: "Priya Nair",
    source: "bot_voice",
    sentiment: "positive",
    score: 0.85,
    variant: "clean",
    priority: "high",
    daysAgo: 12,
  }),

  // Lost
  make({
    id: "LD-1019",
    cust: 4,
    productId: "debt-consolidation",
    stage: "lost",
    amount: 500_000,
    team: "Retail Sales",
    owner: "Priya Nair",
    source: "bot_voice",
    sentiment: "negative",
    score: 0.28,
    variant: "two-warn",
    priority: "normal",
    daysAgo: 6,
    lossReason: "Rate not competitive vs competitor bank",
  }),
  make({
    id: "LD-1020",
    cust: 1,
    productId: "personal-loan",
    stage: "lost",
    amount: 200_000,
    team: "Retail Sales",
    owner: "Arjun Mehta",
    source: "bot_chat",
    sentiment: "neutral",
    score: 0.35,
    variant: "two-warn",
    priority: "low",
    daysAgo: 10,
    lossReason: "Ineligible — bureau score below policy",
  }),
  make({
    id: "LD-1021",
    cust: 3,
    productId: "cc-limit-upgrade",
    stage: "lost",
    amount: 150_000,
    team: "Cards Sales",
    owner: "Sara Khan",
    source: "agent",
    sentiment: "neutral",
    score: 0.4,
    variant: "one-warn",
    priority: "normal",
    daysAgo: 14,
    lossReason: "Customer withdrew request",
  }),
  make({
    id: "LD-1022",
    cust: 5,
    productId: "gold-loan",
    stage: "lost",
    amount: 60_000,
    team: "Retail Sales",
    owner: "Meera Iyer",
    source: "bot_voice",
    sentiment: "neutral",
    score: 0.42,
    variant: "clean",
    priority: "low",
    daysAgo: 18,
    lossReason: "Customer got funds elsewhere",
  }),
];

export const leads = _leads;

// ---------- filters ----------

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

export const CURRENT_AGENT = "Priya Nair";

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

export function filterLeads(list: Lead[], f: Filters): Lead[] {
  const q = f.search.trim().toLowerCase();
  return list.filter((l) => {
    if (q) {
      const hay =
        `${l.customerName} ${l.accountId} ${l.accountTail} ${l.offer.label} ${l.transcriptSnippet} ${l.id}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    if (f.team !== "all" && l.team !== f.team) return false;
    if (f.owner !== "all" && l.owner !== f.owner) return false;
    if (f.productId !== "all" && l.offer.productId !== f.productId) return false;
    if (f.source !== "all" && l.source !== f.source) return false;
    if (f.sentiments.length > 0 && !f.sentiments.includes(l.sentimentAtCapture)) return false;
    if (f.priorities.length > 0 && !f.priorities.includes(l.priority)) return false;
    if (f.myQueue && l.owner !== CURRENT_AGENT) return false;
    return true;
  });
}

export function listOwners(): string[] {
  return OWNERS;
}

export function listCustomers() {
  return CUSTOMERS;
}

// ---------- metrics ----------

export interface Metrics {
  openLeads: number;
  pipelineValue: number;
  wonWeek: number;
  wonWeekAmount: number;
  conversionRate: number; // 0..100
  avgDaysToClose: number;
  perStage: Record<LeadStage, { count: number; amount: number }>;
}

export function computeMetrics(list: Lead[]): Metrics {
  const perStage: Metrics["perStage"] = {
    interested: { count: 0, amount: 0 },
    contacted: { count: 0, amount: 0 },
    qualified: { count: 0, amount: 0 },
    won: { count: 0, amount: 0 },
    lost: { count: 0, amount: 0 },
  };
  for (const l of list) {
    perStage[l.stage].count += 1;
    perStage[l.stage].amount += leadValue(l);
  }
  const openStages: LeadStage[] = ["interested", "contacted", "qualified"];
  const openLeads = openStages.reduce((s, st) => s + perStage[st].count, 0);
  const pipelineValue = openStages.reduce((s, st) => s + perStage[st].amount, 0);
  const wkAgo = Date.now() - 7 * 86400 * 1000;
  const wonWeekList = list.filter(
    (l) => l.stage === "won" && l.closedAt && new Date(l.closedAt).getTime() >= wkAgo,
  );
  const wonWeek = wonWeekList.length;
  const wonWeekAmount = wonWeekList.reduce((s, l) => s + leadValue(l), 0);
  const monthAgo = Date.now() - 30 * 86400 * 1000;
  const capturedRecent = list.filter((l) => new Date(l.capturedAt).getTime() >= monthAgo);
  const wonRecent = capturedRecent.filter((l) => l.stage === "won").length;
  const conversionRate =
    capturedRecent.length === 0 ? 0 : Math.round((wonRecent / capturedRecent.length) * 100);
  const closed = list.filter((l) => l.closedAt);
  const avgDaysToClose =
    closed.length === 0
      ? 0
      : Math.round(
          closed.reduce(
            (s, l) =>
              s + (new Date(l.closedAt!).getTime() - new Date(l.capturedAt).getTime()) / 86400000,
            0,
          ) / closed.length,
        );
  return {
    openLeads,
    pipelineValue,
    wonWeek,
    wonWeekAmount,
    conversionRate,
    avgDaysToClose,
    perStage,
  };
}

// ---------- mutations ----------

function push(lead: Lead, ev: Omit<LeadEvent, "at"> & { at?: string }) {
  lead.events.unshift({
    at: ev.at ?? new Date().toISOString(),
    kind: ev.kind,
    by: ev.by,
    note: ev.note,
  });
}

export function moveStage(id: string, next: LeadStage, by = CURRENT_AGENT, note?: string) {
  const l = _leads.find((x) => x.id === id);
  if (!l || l.stage === next) return;
  l.stage = next;
  push(l, { kind: "stage_moved", by, note: note ?? `Moved to ${next}` });
  if (next === "won") {
    l.closedAt = new Date().toISOString();
    if (!l.wonAmount) l.wonAmount = l.estimatedValue;
    push(l, { kind: "won", by, note: `Marked won · ${fmtMoney(l.wonAmount)}` });
  } else if (next === "lost") {
    l.closedAt = new Date().toISOString();
    push(l, { kind: "lost", by, note: l.lossReason ?? "Marked lost" });
  } else {
    l.closedAt = undefined;
  }
}

export function assign(id: string, owner: string, by = CURRENT_AGENT) {
  const l = _leads.find((x) => x.id === id);
  if (!l) return;
  l.owner = owner;
  push(l, { kind: "assigned", by, note: `Assigned to ${owner}` });
}

export function reassignTeam(id: string, team: Team, by = CURRENT_AGENT) {
  const l = _leads.find((x) => x.id === id);
  if (!l) return;
  l.team = team;
  push(l, { kind: "team_changed", by, note: `Routed to ${team}` });
}

export function scheduleFollowUp(
  id: string,
  at: string,
  channel: FollowUpChannel,
  note: string,
  by = CURRENT_AGENT,
) {
  const l = _leads.find((x) => x.id === id);
  if (!l) return;
  l.followUps.push({ at, channel, note, done: false });
  l.followUps.sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());
  const nextOpen = l.followUps.find((f) => !f.done);
  l.nextFollowUpAt = nextOpen?.at;
  push(l, {
    kind: "followup_scheduled",
    by,
    note: `Follow-up on ${new Date(at).toLocaleString()} via ${channel}`,
  });
}

export function markFollowUpDone(id: string, idx: number, by = CURRENT_AGENT) {
  const l = _leads.find((x) => x.id === id);
  if (!l || !l.followUps[idx]) return;
  l.followUps[idx].done = true;
  const nextOpen = l.followUps.find((f) => !f.done);
  l.nextFollowUpAt = nextOpen?.at;
  push(l, { kind: "followup_done", by, note: `Completed follow-up (${l.followUps[idx].channel})` });
}

export function markWon(id: string, amount: number, by = CURRENT_AGENT) {
  const l = _leads.find((x) => x.id === id);
  if (!l) return;
  l.wonAmount = amount;
  l.stage = "won";
  l.closedAt = new Date().toISOString();
  push(l, { kind: "won", by, note: `Marked won · ${fmtMoney(amount)}` });
}

export function markLost(id: string, reason: string, by = CURRENT_AGENT) {
  const l = _leads.find((x) => x.id === id);
  if (!l) return;
  l.lossReason = reason;
  l.stage = "lost";
  l.closedAt = new Date().toISOString();
  push(l, { kind: "lost", by, note: `Lost · ${reason}` });
}

export function updateOffer(id: string, patch: Partial<LeadOffer>, by = CURRENT_AGENT) {
  const l = _leads.find((x) => x.id === id);
  if (!l) return;
  const nextOffer = { ...l.offer, ...patch };
  if (patch.productId && productMap[patch.productId]) {
    const p = productMap[patch.productId];
    nextOffer.label = p.name;
    if (!patch.indicativeROI) nextOffer.indicativeROI = p.indicativeROI;
  }
  l.offer = nextOffer;
  if (patch.indicativeAmount !== undefined) l.estimatedValue = patch.indicativeAmount;
  push(l, {
    kind: "offer_edited",
    by,
    note: `Offer updated · ${nextOffer.label} · ${fmtMoney(nextOffer.indicativeAmount)}`,
  });
}

let _seq = 2000;
export function createLead(input: {
  customerId: string;
  productId: string;
  indicativeAmount: number;
  team: Team;
  owner: string;
  source: LeadSource;
  priority: Priority;
  note: string;
}): Lead {
  const cust = CUSTOMERS.find((c) => c.id === input.customerId) ?? CUSTOMERS[0];
  const product = productMap[input.productId] ?? products[0];
  const id = `LD-${_seq++}`;
  const nowISO = new Date().toISOString();
  const lead: Lead = {
    id,
    customerId: cust.id,
    customerName: cust.name,
    accountId: cust.accountId,
    accountTail: cust.tail,
    offer: {
      productId: product.id,
      label: product.name,
      indicativeAmount: input.indicativeAmount,
      indicativeROI: product.indicativeROI,
    },
    stage: "interested",
    capturedAt: nowISO,
    source: input.source,
    sentimentAtCapture: "neutral",
    // Polarity, not confidence — neutral is 0.
    sentimentScore: 0,
    transcriptSnippet: input.note,
    eligibilityFlags: eligFor(product.id, "clean"),
    owner: input.owner,
    team: input.team,
    followUps: [],
    priority: input.priority,
    estimatedValue: input.indicativeAmount,
    events: [{ at: nowISO, kind: "created", by: input.owner, note: "Lead created manually" }],
  };
  _leads.unshift(lead);
  return lead;
}

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

export const TEAM_OPTIONS: Team[] = ["Retail Sales", "Cards Sales", "Insurance"];
