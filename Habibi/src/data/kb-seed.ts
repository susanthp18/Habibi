// Knowledge Base (RAG) — synthetic documents, chunks, FAQ pairs and mock retrieval.

export type KbDocType = "policy" | "sop" | "product" | "compliance" | "faq" | "benefits";
export type KbStatus = "indexed" | "indexing" | "stale" | "failed" | "draft";

export interface KbChunk {
  id: string;
  docId: string;
  index: number;
  heading: string;
  tokens: number;
  text: string;
  hits: number; // retrieval hits (mock)
}

export interface KbDocument {
  id: string;
  title: string;
  filename: string;
  type: KbDocType;
  version: string;
  status: KbStatus;
  enabled: boolean;
  chunks: number;
  chunkSize: number;
  overlap: number;
  embeddingModel: string;
  updatedBy: string;
  lastIndexed: string; // ISO
  tags: string[];
}

export interface FaqPair {
  id: string;
  question: string;
  answer: string;
  intent: string;
  enabled: boolean;
  updatedAt: string;
  linkedDocId?: string;
}

export interface RetrievalResult {
  chunkId: string;
  docId: string;
  docTitle: string;
  heading: string;
  snippet: string;
  score: number; // 0..1
  matchedTerms: string[];
}

// ----- helpers -----
function iso(daysAgo: number, hour = 10) {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  d.setHours(hour, 12, 0, 0);
  return d.toISOString();
}

const CHUNK_TEMPLATES = [
  "Late-fee is computed as 2% of the overdue principal or ₹450 flat, whichever is higher. Waivers require Tier-2 approval when the customer is within a 60-day delinquency bucket and has no prior waiver in the last 12 months.",
  "Customers may request an EMI restructure once every 12 months. Restructure eligibility depends on outstanding tenure > 6 months, no bounced instalment in the last 3 cycles, and completed KYC.",
  "For pre-closure of personal loans, foreclosure charges are 4% of the outstanding principal within the first 12 months, 3% between 13-24 months, and NIL thereafter. GST applies on the charge.",
  'The bot must always disclose the recording notice at the start of a call: "This call is being recorded for training and compliance purposes." Failure to do so is a P1 compliance violation.',
  "Do-Not-Disturb (DND) preferences override all outbound campaigns except regulatory disclosures. The bot must check consent state before initiating any promotional or upsell dialog.",
  "A top-up loan can be offered when: (a) 12+ EMIs paid on the parent loan, (b) no bounce in last 6 months, (c) CIBIL 720+, (d) internal risk grade A/B. The maximum top-up is 40% of the original sanction.",
  "For NOC (No-Objection Certificate) issuance post full closure, the request must be raised within 7 working days. The document is delivered via WhatsApp + Email; a physical copy is dispatched only on written request.",
  "Statement of account (SOA) requests are fulfilled instantly for periods up to 12 months. For older periods (> 12 months) the request is queued for back-office processing with a 48-hour SLA.",
  "If a customer disputes a transaction, the agent must (1) capture the transaction ID, (2) attach any voice snippet of the customer confirming the dispute, (3) mark the account 'in dispute' which pauses collection dialers for 5 working days.",
  "Vernacular language switching is supported for Hindi, Tamil, Telugu, Kannada, Marathi, Bengali and Gujarati. The bot should acknowledge the switch and repeat the last question in the new language.",
];

function makeChunks(docId: string, count: number, headingSeed: string): KbChunk[] {
  return Array.from({ length: count }, (_, i) => {
    const text = CHUNK_TEMPLATES[(i + docId.length) % CHUNK_TEMPLATES.length];
    return {
      id: `${docId}-c${i + 1}`,
      docId,
      index: i + 1,
      heading: `${headingSeed} · §${i + 1}`,
      tokens: 140 + ((i * 37) % 220),
      text,
      hits: Math.max(0, 42 - i * 3 + ((docId.length + i) % 7)),
    };
  });
}

// ----- documents -----
const DOC_META: Array<
  Omit<KbDocument, "chunks" | "lastIndexed" | "enabled" | "status"> & {
    chunkCount: number;
    daysAgo: number;
    status?: KbStatus;
    enabled?: boolean;
  }
> = [
  {
    id: "d1",
    title: "Late-Fee & Waiver Policy",
    filename: "late_fee_policy_v4.pdf",
    type: "policy",
    version: "v4.2",
    chunkCount: 22,
    chunkSize: 512,
    overlap: 64,
    embeddingModel: "text-embedding-3-small",
    updatedBy: "P. Iyer",
    tags: ["late-fee", "waiver"],
    daysAgo: 2,
  },
  {
    id: "d2",
    title: "EMI Restructure SOP",
    filename: "emi_restructure_sop.pdf",
    type: "sop",
    version: "v2.1",
    chunkCount: 18,
    chunkSize: 512,
    overlap: 64,
    embeddingModel: "text-embedding-3-small",
    updatedBy: "R. Menon",
    tags: ["emi", "restructure"],
    daysAgo: 5,
  },
  {
    id: "d3",
    title: "Foreclosure & Pre-Payment Rules",
    filename: "foreclosure_rules_v3.pdf",
    type: "policy",
    version: "v3.0",
    chunkCount: 14,
    chunkSize: 512,
    overlap: 64,
    embeddingModel: "text-embedding-3-small",
    updatedBy: "S. Ranganathan",
    tags: ["foreclosure", "pre-payment"],
    daysAgo: 12,
  },
  {
    id: "d4",
    title: "Recording & Disclosure Compliance",
    filename: "recording_disclosure.pdf",
    type: "compliance",
    version: "v1.4",
    chunkCount: 9,
    chunkSize: 384,
    overlap: 48,
    embeddingModel: "text-embedding-3-small",
    updatedBy: "Legal Ops",
    tags: ["compliance", "disclosure"],
    daysAgo: 30,
  },
  {
    id: "d5",
    title: "DND & Consent Framework",
    filename: "dnd_consent_v2.pdf",
    type: "compliance",
    version: "v2.0",
    chunkCount: 11,
    chunkSize: 384,
    overlap: 48,
    embeddingModel: "text-embedding-3-small",
    updatedBy: "Legal Ops",
    tags: ["dnd", "consent"],
    daysAgo: 20,
  },
  {
    id: "d6",
    title: "Product Catalog — Top-Up Loans",
    filename: "topup_catalog.pdf",
    type: "product",
    version: "v6.1",
    chunkCount: 16,
    chunkSize: 512,
    overlap: 64,
    embeddingModel: "text-embedding-3-small",
    updatedBy: "Product Team",
    tags: ["upsell", "topup"],
    daysAgo: 3,
  },
  {
    id: "d7",
    title: "NOC & Post-Closure Docs SOP",
    filename: "noc_post_closure_sop.pdf",
    type: "sop",
    version: "v1.3",
    chunkCount: 10,
    chunkSize: 384,
    overlap: 48,
    embeddingModel: "text-embedding-3-small",
    updatedBy: "Ops · Fulfilment",
    tags: ["noc", "documents"],
    daysAgo: 8,
  },
  {
    id: "d8",
    title: "Statement of Account — Handling",
    filename: "soa_handling.pdf",
    type: "sop",
    version: "v1.1",
    chunkCount: 8,
    chunkSize: 384,
    overlap: 48,
    embeddingModel: "text-embedding-3-small",
    updatedBy: "Ops · Fulfilment",
    tags: ["statement", "documents"],
    daysAgo: 6,
  },
  {
    id: "d9",
    title: "Dispute Capture Playbook",
    filename: "dispute_playbook.pdf",
    type: "sop",
    version: "v2.4",
    chunkCount: 13,
    chunkSize: 512,
    overlap: 64,
    embeddingModel: "text-embedding-3-small",
    updatedBy: "R. Menon",
    tags: ["dispute"],
    daysAgo: 4,
  },
  {
    id: "d10",
    title: "Vernacular Language Support",
    filename: "vernacular_support.pdf",
    type: "sop",
    version: "v1.0",
    chunkCount: 7,
    chunkSize: 384,
    overlap: 48,
    embeddingModel: "text-embedding-3-small",
    updatedBy: "AI Ops",
    tags: ["language", "i18n"],
    daysAgo: 45,
    status: "stale",
  },
  {
    id: "d11",
    title: "CIBIL Impact Disclosures",
    filename: "cibil_disclosure_v2.pdf",
    type: "compliance",
    version: "v2.2",
    chunkCount: 9,
    chunkSize: 384,
    overlap: 48,
    embeddingModel: "text-embedding-3-small",
    updatedBy: "Legal Ops",
    tags: ["cibil", "disclosure"],
    daysAgo: 15,
  },
  {
    id: "d12",
    title: "Hardship & Moratorium Guidelines",
    filename: "hardship_guidelines.pdf",
    type: "policy",
    version: "v1.1",
    chunkCount: 12,
    chunkSize: 512,
    overlap: 64,
    embeddingModel: "text-embedding-3-small",
    updatedBy: "Risk Ops",
    tags: ["hardship", "moratorium"],
    daysAgo: 60,
    status: "stale",
  },
  {
    id: "d13",
    title: "Bot Escalation & Handoff Rules",
    filename: "handoff_rules.pdf",
    type: "sop",
    version: "v3.0",
    chunkCount: 11,
    chunkSize: 512,
    overlap: 64,
    embeddingModel: "text-embedding-3-small",
    updatedBy: "AI Ops",
    tags: ["handoff"],
    daysAgo: 1,
  },
  {
    id: "d14",
    title: "Fair Practices Code — Collections",
    filename: "fpc_collections.pdf",
    type: "compliance",
    version: "v4.0",
    chunkCount: 15,
    chunkSize: 512,
    overlap: 64,
    embeddingModel: "text-embedding-3-small",
    updatedBy: "Legal Ops",
    tags: ["fpc", "compliance"],
    daysAgo: 90,
    status: "failed",
  },
];

export const documents: KbDocument[] = DOC_META.map((m) => ({
  id: m.id,
  title: m.title,
  filename: m.filename,
  type: m.type,
  version: m.version,
  status: m.status ?? "indexed",
  enabled: m.enabled ?? m.status !== "failed",
  chunks: m.chunkCount,
  chunkSize: m.chunkSize,
  overlap: m.overlap,
  embeddingModel: m.embeddingModel,
  updatedBy: m.updatedBy,
  lastIndexed: iso(m.daysAgo),
  tags: m.tags,
}));

export const chunks: KbChunk[] = documents.flatMap((d) => makeChunks(d.id, d.chunks, d.title));

// ----- FAQ pairs -----
export const faqs: FaqPair[] = [
  {
    id: "f1",
    question: "What is the current late fee amount?",
    answer:
      "Late fee is 2% of the overdue principal or ₹450 flat, whichever is higher. A one-time waiver may be granted per 12-month period subject to eligibility.",
    intent: "late-fee",
    enabled: true,
    updatedAt: iso(3),
    linkedDocId: "d1",
  },
  {
    id: "f2",
    question: "How can I restructure my EMI?",
    answer:
      "Raise a restructure request via the app or with an agent. Eligibility requires a tenure > 6 months remaining, no bounces in the last 3 cycles, and completed KYC.",
    intent: "emi",
    enabled: true,
    updatedAt: iso(5),
    linkedDocId: "d2",
  },
  {
    id: "f3",
    question: "What are the foreclosure charges?",
    answer:
      "4% within year 1, 3% between year 1 and 2, and NIL thereafter, plus GST — computed on the outstanding principal on the foreclosure date.",
    intent: "foreclosure",
    enabled: true,
    updatedAt: iso(10),
    linkedDocId: "d3",
  },
  {
    id: "f4",
    question: "How do I get a No-Objection Certificate (NOC)?",
    answer:
      "NOC is auto-issued within 7 working days of full closure, delivered via WhatsApp and Email. Physical copy on written request.",
    intent: "documents",
    enabled: true,
    updatedAt: iso(8),
    linkedDocId: "d7",
  },
  {
    id: "f5",
    question: "Can I get a statement of account?",
    answer:
      "Statements for the last 12 months are delivered instantly on WhatsApp/Email. Older statements are processed within 48 hours.",
    intent: "statement",
    enabled: true,
    updatedAt: iso(6),
    linkedDocId: "d8",
  },
  {
    id: "f6",
    question: "Am I eligible for a top-up loan?",
    answer:
      "Top-up eligibility needs 12+ EMIs paid, no bounces in last 6 months, CIBIL 720+, and internal risk grade A/B. Maximum top-up is 40% of the original sanction.",
    intent: "topup",
    enabled: true,
    updatedAt: iso(3),
    linkedDocId: "d6",
  },
  {
    id: "f7",
    question: "Will paying only the minimum affect my CIBIL?",
    answer:
      "Paying only the minimum keeps you current but continues to accrue interest on the revolving balance. It does not directly hurt CIBIL as long as no instalment is missed.",
    intent: "cibil",
    enabled: true,
    updatedAt: iso(11),
    linkedDocId: "d11",
  },
  {
    id: "f8",
    question: "How do I raise a dispute on a transaction?",
    answer:
      "Share the transaction ID with the agent or via chat. The account is marked 'in dispute', pausing collection contact for 5 working days while investigation completes.",
    intent: "dispute",
    enabled: true,
    updatedAt: iso(4),
    linkedDocId: "d9",
  },
  {
    id: "f9",
    question: "Can I switch language mid-call?",
    answer:
      'Yes — say the language name (e.g., "Tamil") and the bot will confirm and repeat the last question in the new language.',
    intent: "language",
    enabled: true,
    updatedAt: iso(45),
    linkedDocId: "d10",
  },
  {
    id: "f10",
    question: "What is DND and how do I enable it?",
    answer:
      "DND (Do-Not-Disturb) restricts promotional contact. You can enable it via app settings, IVR, or by asking any agent. Regulatory disclosures still apply.",
    intent: "consent",
    enabled: true,
    updatedAt: iso(20),
    linkedDocId: "d5",
  },
  {
    id: "f11",
    question: "Is my call being recorded?",
    answer:
      "Yes. All calls are recorded for training and compliance purposes; the disclosure is provided at the start of every call.",
    intent: "compliance",
    enabled: true,
    updatedAt: iso(30),
    linkedDocId: "d4",
  },
  {
    id: "f12",
    question: "Can I get a moratorium in case of job loss?",
    answer:
      "Hardship moratoriums are considered case-by-case with proof of hardship. Approvals typically extend tenure rather than waive dues.",
    intent: "hardship",
    enabled: false,
    updatedAt: iso(60),
    linkedDocId: "d12",
  },
  {
    id: "f13",
    question: "How do I change my EMI debit date?",
    answer:
      "Debit-date changes are allowed once per year and take effect from the next billing cycle. Raise the request via the app.",
    intent: "emi",
    enabled: true,
    updatedAt: iso(9),
  },
  {
    id: "f14",
    question: "Why was my late fee ₹599 vs standard ₹450?",
    answer:
      "The higher of ₹450 or 2% of overdue applies. If your overdue was above ₹22,500, the 2% computation yields more than ₹450.",
    intent: "late-fee",
    enabled: true,
    updatedAt: iso(2),
    linkedDocId: "d1",
  },
  {
    id: "f15",
    question: "How do I close my loan fully?",
    answer:
      "Request a foreclosure statement, pay the quoted amount including charges + GST, and NOC is issued within 7 working days.",
    intent: "foreclosure",
    enabled: true,
    updatedAt: iso(14),
    linkedDocId: "d3",
  },
  {
    id: "f16",
    question: "What is the interest rate on my loan?",
    answer:
      "Interest rate is disclosed on your sanction letter and monthly statement. Rates are subject to periodic revisions — see the latest statement for the current effective rate.",
    intent: "emi",
    enabled: true,
    updatedAt: iso(28),
  },
  {
    id: "f17",
    question: "Can I convert overdue to EMI?",
    answer:
      "Overdue-to-EMI conversion is offered subject to eligibility and Tier-2 approval. A one-time processing fee applies.",
    intent: "restructure",
    enabled: false,
    updatedAt: iso(40),
    linkedDocId: "d2",
  },
  {
    id: "f18",
    question: "What documents do I need for a top-up?",
    answer:
      "Latest 3 months' bank statements, updated income proof, and re-KYC if last KYC is > 3 years old.",
    intent: "topup",
    enabled: true,
    updatedAt: iso(3),
    linkedDocId: "d6",
  },
];

// ----- retrieval -----
const STOP = new Set([
  "the",
  "a",
  "an",
  "is",
  "to",
  "of",
  "and",
  "or",
  "in",
  "on",
  "for",
  "my",
  "i",
  "can",
  "how",
  "do",
  "what",
  "why",
  "be",
  "am",
  "are",
  "was",
  "were",
  "it",
  "with",
  "this",
  "that",
]);

function tokenize(s: string): string[] {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9\s%₹]/g, " ")
    .split(/\s+/)
    .filter((t) => t.length > 2 && !STOP.has(t));
}

export function runMockRetrieval(
  query: string,
  topK = 4,
): { results: RetrievalResult[]; latencyMs: number } {
  const q = tokenize(query);
  if (q.length === 0) return { results: [], latencyMs: 0 };
  const enabledDocIds = new Set(documents.filter((d) => d.enabled).map((d) => d.id));
  const scored: RetrievalResult[] = [];
  for (const ch of chunks) {
    if (!enabledDocIds.has(ch.docId)) continue;
    const chunkTokens = new Set(tokenize(ch.text + " " + ch.heading));
    const matched = q.filter((t) => chunkTokens.has(t));
    if (matched.length === 0) continue;
    const overlap = matched.length / q.length;
    const density = matched.length / Math.max(20, chunkTokens.size);
    const score = Math.min(0.98, 0.55 * overlap + 6.5 * density + ch.hits / 800);
    const doc = documents.find((d) => d.id === ch.docId)!;
    scored.push({
      chunkId: ch.id,
      docId: ch.docId,
      docTitle: doc.title,
      heading: ch.heading,
      snippet: ch.text,
      score,
      matchedTerms: Array.from(new Set(matched)),
    });
  }
  // include one FAQ match with boost if question overlap is high
  for (const f of faqs) {
    if (!f.enabled) continue;
    const fTokens = new Set(tokenize(f.question + " " + f.answer));
    const matched = q.filter((t) => fTokens.has(t));
    if (matched.length / q.length >= 0.5) {
      scored.push({
        chunkId: `faq-${f.id}`,
        docId: "faq",
        docTitle: `FAQ · ${f.intent}`,
        heading: f.question,
        snippet: f.answer,
        score: Math.min(0.99, 0.6 + 0.35 * (matched.length / q.length)),
        matchedTerms: matched,
      });
    }
  }
  scored.sort((a, b) => b.score - a.score);
  const latencyMs = 120 + Math.round((query.length * 3) % 180);
  return { results: scored.slice(0, topK), latencyMs };
}

export function chunkPreview(size: number, overlap: number): { count: number; samples: string[] } {
  // Simulated: assume ~4500 tokens of source content.
  const source = 4500;
  const step = Math.max(1, size - overlap);
  const count = Math.max(1, Math.ceil((source - overlap) / step));
  const samples = Array.from({ length: Math.min(5, count) }, (_, i) => {
    return CHUNK_TEMPLATES[i % CHUNK_TEMPLATES.length];
  });
  return { count, samples };
}

export function computeKbStats(docs: KbDocument[], faqList: FaqPair[], gaps: number) {
  const totalChunks = docs
    .filter((d) => d.enabled && d.status === "indexed")
    .reduce((s, d) => s + d.chunks, 0);
  const lastIndexed = docs
    .map((d) => d.lastIndexed)
    .sort()
    .reverse()[0];
  const avgScore = 0.78; // simulated aggregate
  return {
    docs: docs.length,
    activeDocs: docs.filter((d) => d.enabled && d.status === "indexed").length,
    faqs: faqList.filter((f) => f.enabled).length,
    chunks: totalChunks,
    gaps,
    lastIndexed,
    avgScore,
  };
}

export const DOC_TYPE_LABEL: Record<KbDocType, string> = {
  policy: "Policy",
  sop: "SOP",
  product: "Product",
  compliance: "Compliance",
  faq: "FAQ",
  benefits: "Benefits",
};

export const STATUS_LABEL: Record<KbStatus, string> = {
  indexed: "Indexed",
  indexing: "Indexing",
  stale: "Stale",
  failed: "Failed",
  draft: "Draft",
};
