// Customer 360 synthetic data
// One rich file so every tab in the detail view reads from the same source
// and the numbers stay internally consistent.

export type RiskLevel = "critical" | "high" | "medium" | "low";
export type Channel = "voice" | "whatsapp" | "chat" | "email" | "sms";
export type Sentiment = "positive" | "neutral" | "negative";
export type LedgerType = "charge" | "payment" | "fee" | "adjustment" | "waiver";
export type EmiStatus = "paid" | "upcoming" | "overdue" | "partial";
export type PtpStatus = "upcoming" | "kept" | "broken" | "partial";
export type DisputeStatus = "new" | "under_review" | "awaiting_customer" | "resolved" | "rejected";
export type DocStatus = "requested" | "generating" | "sent" | "failed";
export type Product = "Credit Card" | "Personal Loan" | "Auto Loan";

export interface LedgerEntry {
  id: string;
  date: string; // ISO
  description: string;
  type: LedgerType;
  amount: number; // signed; charges +, payments -
  balance: number;
  invoiceId?: string;
}

export interface EmiRow {
  id: string;
  index: number;
  dueDate: string;
  amount: number;
  paidOn?: string;
  paidAmount?: number;
  status: EmiStatus;
  balanceCarried: number;
}

export interface Interaction {
  id: string;
  channel: Channel;
  handler: { kind: "bot" | "human"; name: string };
  startedAt: string; // ISO
  duration: string;
  disposition: string;
  sentiment: Sentiment;
  sentimentDelta: "up" | "down" | "flat";
  summary: string;
  intents: { queryResolved?: boolean; upsellPresented?: boolean; ptpCaptured?: boolean };
  transcript?: string[];
}

export interface Promise {
  id: string;
  amount: number;
  promisedDate: string;
  createdAt: string;
  channel: Channel;
  handler: string;
  status: PtpStatus;
  reminderStatus: "queued" | "sent" | "acknowledged" | "off";
}

export interface Dispute {
  id: string;
  type: string;
  amount: number;
  transcriptSnippet: string;
  status: DisputeStatus;
  slaLabel: string;
  filedAt: string;
  assignee?: string;
}

export interface DocumentRequest {
  id: string;
  type: string;
  requestedVia: Channel;
  requestedAt: string;
  deliveryChannel: "email" | "whatsapp";
  status: DocStatus;
  source?: string;
}

export interface CustomerNote {
  id: string;
  author: string;
  at: string;
  text: string;
  pinned?: boolean;
}

export interface Consent {
  channel: "call" | "whatsapp" | "sms" | "email";
  optedIn: boolean;
  source: "self-serve" | "bot-captured" | "agent-captured";
  capturedAt: string;
}

export interface Contact {
  phonePrimary: string;
  phoneAlt?: string;
  email: string;
  address: string;
  timezone: string;
  language: string;
  preferredWindow: string; // e.g. "10:00–19:00 IST"
  dnd: boolean;
}

export interface AccountFacts {
  product: Product;
  openedOn: string;
  apr: number;
  sanctionedAmount: number;
  bucket: "0-30" | "31-60" | "61-90" | "91+";
  dpd: number;
  riskScore: number; // 300-900
}

export interface Customer {
  id: string;
  name: string;
  accountId: string;
  risk: RiskLevel;
  outstanding: number;
  minimumDue: number;
  lastContact: string;
  assignedTo: string;
  contact: Contact;
  account: AccountFacts;
  consent: Consent[];
  ledger: LedgerEntry[];
  emi: EmiRow[];
  interactions: Interaction[];
  promises: Promise[];
  disputes: Dispute[];
  documents: DocumentRequest[];
  notes: CustomerNote[];
}

// ---- helpers ----
const now = new Date();
function iso(daysAgo: number, hour = 10) {
  const d = new Date(now);
  d.setDate(d.getDate() - daysAgo);
  d.setHours(hour, 15, 0, 0);
  return d.toISOString();
}
function isoFuture(daysAhead: number, hour = 10) {
  return iso(-daysAhead, hour);
}

// ---- ledger builder ----
function buildLedger(seed: number, monthly: number): LedgerEntry[] {
  const rows: Omit<LedgerEntry, "balance">[] = [];
  let daysBack = 180;
  for (let i = 0; i < 6; i++) {
    rows.push({
      id: `L${seed}-c${i}`,
      date: iso(daysBack),
      description: `EMI installment #${i + 1}`,
      type: "charge",
      amount: monthly,
      invoiceId: `INV-${seed}-${1000 + i}`,
    });
    // 4 out of 6 paid
    if (i < 4) {
      rows.push({
        id: `L${seed}-p${i}`,
        date: iso(daysBack - 3),
        description: `UPI payment — reference ${seed}${i}${i}${i}`,
        type: "payment",
        amount: -monthly,
      });
    }
    daysBack -= 30;
  }
  // Fees + waivers sprinkled
  rows.push({
    id: `L${seed}-f1`,
    date: iso(35),
    description: "Late payment fee",
    type: "fee",
    amount: Math.round(monthly * 0.05),
  });
  rows.push({
    id: `L${seed}-w1`,
    date: iso(28),
    description: "Goodwill fee waiver (agent: Priya Nair)",
    type: "waiver",
    amount: -Math.round(monthly * 0.05),
  });
  rows.push({
    id: `L${seed}-adj1`,
    date: iso(12),
    description: "Interest capitalization",
    type: "adjustment",
    amount: Math.round(monthly * 0.03),
  });

  rows.sort((a, b) => a.date.localeCompare(b.date));
  let running = 0;
  return rows.map((r) => {
    running += r.amount;
    return { ...r, balance: running };
  }).reverse(); // newest first for display
}

function buildEmi(seed: number, monthly: number): EmiRow[] {
  const rows: EmiRow[] = [];
  for (let i = 0; i < 12; i++) {
    const daysFromNow = -150 + i * 30;
    const due = isoFuture(-daysFromNow, 9);
    let status: EmiStatus;
    let paidOn: string | undefined;
    let paidAmount: number | undefined;
    if (i < 4) {
      status = "paid";
      paidOn = isoFuture(-daysFromNow + 2, 11);
      paidAmount = monthly;
    } else if (i === 4) {
      status = "partial";
      paidOn = isoFuture(-daysFromNow + 5, 11);
      paidAmount = Math.round(monthly * 0.4);
    } else if (i === 5) {
      status = "overdue";
    } else {
      status = "upcoming";
    }
    const balanceCarried = monthly * (12 - i) - (paidAmount ?? 0);
    rows.push({
      id: `E${seed}-${i}`,
      index: i + 1,
      dueDate: due,
      amount: monthly,
      paidOn,
      paidAmount,
      status,
      balanceCarried: Math.max(0, Math.round(balanceCarried)),
    });
  }
  return rows;
}

// ---- Customers ----
const _customers: Customer[] = [
  {
    id: "vikram-rao",
    name: "Vikram Rao",
    accountId: "AC-77410",
    risk: "critical",
    outstanding: 8640,
    minimumDue: 1240,
    lastContact: iso(0, 8),
    assignedTo: "Priya Nair",
    contact: {
      phonePrimary: "+91 98•••• ••42",
      phoneAlt: "+91 80•••• ••11",
      email: "v.rao@mail.co.in",
      address: "Flat 12B, Whitefield, Bengaluru 560066",
      timezone: "Asia/Kolkata (IST)",
      language: "English + Hindi",
      preferredWindow: "10:00–19:00 IST",
      dnd: false,
    },
    account: {
      product: "Credit Card",
      openedOn: iso(720),
      apr: 36.9,
      sanctionedAmount: 150000,
      bucket: "61-90",
      dpd: 74,
      riskScore: 512,
    },
    consent: [
      { channel: "call", optedIn: true, source: "self-serve", capturedAt: iso(720) },
      { channel: "whatsapp", optedIn: true, source: "bot-captured", capturedAt: iso(120) },
      { channel: "sms", optedIn: true, source: "self-serve", capturedAt: iso(720) },
      { channel: "email", optedIn: false, source: "self-serve", capturedAt: iso(90) },
    ],
    ledger: buildLedger(1, 2200),
    emi: buildEmi(1, 2200),
    interactions: [
      {
        id: "i1",
        channel: "voice",
        handler: { kind: "human", name: "Priya Nair" },
        startedAt: iso(0, 8),
        duration: "4m 51s",
        disposition: "PTP captured",
        sentiment: "positive",
        sentimentDelta: "up",
        summary: "Customer confirmed EMI 5 shortfall. Committed to pay ₹1,240 by Fri via UPI. Agreed to consolidation callback next week.",
        intents: { queryResolved: true, upsellPresented: true, ptpCaptured: true },
      },
      {
        id: "i2",
        channel: "whatsapp",
        handler: { kind: "bot", name: "CollectionsBot v2.4" },
        startedAt: iso(2, 14),
        duration: "3m 02s",
        disposition: "Bot contained",
        sentiment: "neutral",
        sentimentDelta: "flat",
        summary: "Bot answered outstanding-balance and next-EMI-date queries. No handoff required.",
        intents: { queryResolved: true },
      },
      {
        id: "i3",
        channel: "voice",
        handler: { kind: "bot", name: "CollectionsBot v2.4" },
        startedAt: iso(5, 11),
        duration: "5m 40s",
        disposition: "Escalated → human",
        sentiment: "negative",
        sentimentDelta: "down",
        summary: "Customer disputed late fee. Bot captured dispute D-4821 and routed to Priya Nair.",
        intents: { queryResolved: false },
      },
      {
        id: "i4",
        channel: "chat",
        handler: { kind: "bot", name: "WebChatBot" },
        startedAt: iso(9, 20),
        duration: "1m 22s",
        disposition: "Bot contained",
        sentiment: "neutral",
        sentimentDelta: "flat",
        summary: "FAQ about auto-debit schedule.",
        intents: { queryResolved: true },
      },
      {
        id: "i5",
        channel: "voice",
        handler: { kind: "human", name: "Arjun Mehta" },
        startedAt: iso(21, 15),
        duration: "6m 12s",
        disposition: "PTP captured (broken)",
        sentiment: "neutral",
        sentimentDelta: "flat",
        summary: "Customer committed to ₹2,200 by 10th. Promise later broken.",
        intents: { ptpCaptured: true },
      },
    ],
    promises: [
      { id: "p1", amount: 1240, promisedDate: isoFuture(3), createdAt: iso(0), channel: "voice", handler: "Priya Nair", status: "upcoming", reminderStatus: "queued" },
      { id: "p2", amount: 2200, promisedDate: iso(11), createdAt: iso(21), channel: "voice", handler: "Arjun Mehta", status: "broken", reminderStatus: "sent" },
      { id: "p3", amount: 1500, promisedDate: iso(45), createdAt: iso(60), channel: "whatsapp", handler: "CollectionsBot", status: "kept", reminderStatus: "acknowledged" },
      { id: "p4", amount: 800, promisedDate: iso(75), createdAt: iso(90), channel: "voice", handler: "Sara Khan", status: "partial", reminderStatus: "sent" },
    ],
    disputes: [
      {
        id: "D-4821",
        type: "Late fee waiver",
        amount: 110,
        transcriptSnippet: "\"…I paid on time, why is there a late fee? Please waive this off.\"",
        status: "under_review",
        slaLabel: "1h 12m left",
        filedAt: iso(5),
        assignee: "Priya Nair",
      },
    ],
    documents: [
      { id: "doc1", type: "6-month account statement", requestedVia: "voice", requestedAt: iso(2), deliveryChannel: "email", status: "sent" },
      { id: "doc2", type: "No-dues certificate", requestedVia: "whatsapp", requestedAt: iso(30), deliveryChannel: "whatsapp", status: "sent" },
    ],
    notes: [
      { id: "n1", author: "Priya Nair", at: iso(0, 9), text: "Customer prefers WhatsApp for reminders. Salary credit on 5th — align reminders accordingly.", pinned: true },
      { id: "n2", author: "Arjun Mehta", at: iso(21), text: "Discussed debt consolidation. Interested but wants to see numbers first — send offer sheet." },
    ],
  },
  {
    id: "anita-desai",
    name: "Anita Desai",
    accountId: "AC-88214",
    risk: "critical",
    outstanding: 12480,
    minimumDue: 2100,
    lastContact: iso(2, 14),
    assignedTo: "Meera Iyer",
    contact: {
      phonePrimary: "+91 99•••• ••07",
      email: "anita.d@mail.co.in",
      address: "22 Palm Grove, Andheri West, Mumbai 400058",
      timezone: "Asia/Kolkata (IST)",
      language: "English",
      preferredWindow: "11:00–18:00 IST",
      dnd: false,
    },
    account: {
      product: "Personal Loan",
      openedOn: iso(900),
      apr: 14.5,
      sanctionedAmount: 300000,
      bucket: "91+",
      dpd: 92,
      riskScore: 468,
    },
    consent: [
      { channel: "call", optedIn: true, source: "self-serve", capturedAt: iso(900) },
      { channel: "whatsapp", optedIn: true, source: "self-serve", capturedAt: iso(900) },
      { channel: "sms", optedIn: true, source: "self-serve", capturedAt: iso(900) },
      { channel: "email", optedIn: true, source: "self-serve", capturedAt: iso(900) },
    ],
    ledger: buildLedger(2, 3400),
    emi: buildEmi(2, 3400),
    interactions: [
      {
        id: "ai1",
        channel: "voice",
        handler: { kind: "bot", name: "CollectionsBot v2.4" },
        startedAt: iso(2, 14),
        duration: "6m 20s",
        disposition: "Escalated → human",
        sentiment: "negative",
        sentimentDelta: "down",
        summary: "Customer expressed hardship (job loss). Bot escalated to Meera Iyer for restructuring conversation.",
        intents: { queryResolved: false },
      },
      {
        id: "ai2",
        channel: "voice",
        handler: { kind: "human", name: "Meera Iyer" },
        startedAt: iso(2, 15),
        duration: "12m 04s",
        disposition: "Restructuring proposed",
        sentiment: "neutral",
        sentimentDelta: "up",
        summary: "Discussed 6-month step-up plan. Customer to review and revert by 20th.",
        intents: { queryResolved: true, upsellPresented: false, ptpCaptured: true },
      },
      {
        id: "ai3",
        channel: "whatsapp",
        handler: { kind: "bot", name: "CollectionsBot" },
        startedAt: iso(9),
        duration: "0m 55s",
        disposition: "Bot contained",
        sentiment: "neutral",
        sentimentDelta: "flat",
        summary: "Sent 6-month statement per customer request.",
        intents: { queryResolved: true },
      },
    ],
    promises: [
      { id: "ap1", amount: 5000, promisedDate: isoFuture(9), createdAt: iso(2), channel: "voice", handler: "Meera Iyer", status: "upcoming", reminderStatus: "queued" },
      { id: "ap2", amount: 3400, promisedDate: iso(30), createdAt: iso(40), channel: "voice", handler: "Meera Iyer", status: "broken", reminderStatus: "sent" },
    ],
    disputes: [],
    documents: [
      { id: "adoc1", type: "6-month account statement", requestedVia: "whatsapp", requestedAt: iso(9), deliveryChannel: "whatsapp", status: "sent" },
      { id: "adoc2", type: "Restructuring quote", requestedVia: "voice", requestedAt: iso(2), deliveryChannel: "email", status: "generating" },
    ],
    notes: [
      { id: "an1", author: "Meera Iyer", at: iso(2), text: "Job loss (Jun). Wife earning. Requested 3-month EMI break — awaiting credit review.", pinned: true },
    ],
  },
  {
    id: "neha-kapoor",
    name: "Neha Kapoor",
    accountId: "AC-90112",
    risk: "high",
    outstanding: 5210,
    minimumDue: 620,
    lastContact: iso(1, 16),
    assignedTo: "Priya Nair",
    contact: {
      phonePrimary: "+91 91•••• ••55",
      email: "neha.k@mail.co.in",
      address: "Sector 45, Gurugram 122003",
      timezone: "Asia/Kolkata (IST)",
      language: "English + Hindi",
      preferredWindow: "18:00–21:00 IST",
      dnd: false,
    },
    account: {
      product: "Credit Card",
      openedOn: iso(420),
      apr: 42.5,
      sanctionedAmount: 80000,
      bucket: "31-60",
      dpd: 61,
      riskScore: 604,
    },
    consent: [
      { channel: "call", optedIn: true, source: "self-serve", capturedAt: iso(420) },
      { channel: "whatsapp", optedIn: true, source: "bot-captured", capturedAt: iso(200) },
      { channel: "sms", optedIn: false, source: "self-serve", capturedAt: iso(60) },
      { channel: "email", optedIn: true, source: "self-serve", capturedAt: iso(420) },
    ],
    ledger: buildLedger(3, 1600),
    emi: buildEmi(3, 1600),
    interactions: [
      {
        id: "ni1",
        channel: "whatsapp",
        handler: { kind: "bot", name: "CollectionsBot" },
        startedAt: iso(1, 16),
        duration: "2m 10s",
        disposition: "PTP captured (bot)",
        sentiment: "positive",
        sentimentDelta: "up",
        summary: "Customer promised ₹620 by 25th via UPI. Bot upsold consolidation — not interested.",
        intents: { queryResolved: true, upsellPresented: true, ptpCaptured: true },
      },
    ],
    promises: [
      { id: "np1", amount: 620, promisedDate: isoFuture(4), createdAt: iso(1), channel: "whatsapp", handler: "CollectionsBot", status: "upcoming", reminderStatus: "queued" },
    ],
    disputes: [],
    documents: [],
    notes: [],
  },
  {
    id: "james-patel",
    name: "James Patel",
    accountId: "AC-66803",
    risk: "high",
    outstanding: 22100,
    minimumDue: 4200,
    lastContact: iso(3, 13),
    assignedTo: "David Chen",
    contact: {
      phonePrimary: "+91 97•••• ••88",
      email: "j.patel@mail.co.in",
      address: "56 Rosewood Ave, Pune 411045",
      timezone: "Asia/Kolkata (IST)",
      language: "English",
      preferredWindow: "09:00–13:00 IST",
      dnd: false,
    },
    account: {
      product: "Auto Loan",
      openedOn: iso(1080),
      apr: 10.9,
      sanctionedAmount: 850000,
      bucket: "31-60",
      dpd: 58,
      riskScore: 588,
    },
    consent: [
      { channel: "call", optedIn: true, source: "self-serve", capturedAt: iso(1080) },
      { channel: "whatsapp", optedIn: true, source: "self-serve", capturedAt: iso(1080) },
      { channel: "sms", optedIn: true, source: "self-serve", capturedAt: iso(1080) },
      { channel: "email", optedIn: true, source: "self-serve", capturedAt: iso(1080) },
    ],
    ledger: buildLedger(4, 8500),
    emi: buildEmi(4, 8500),
    interactions: [
      {
        id: "ji1",
        channel: "voice",
        handler: { kind: "human", name: "David Chen" },
        startedAt: iso(3, 13),
        duration: "8m 44s",
        disposition: "Payment plan proposed",
        sentiment: "neutral",
        sentimentDelta: "flat",
        summary: "Customer travelling this week. Will confirm 2-installment plan on return.",
        intents: { queryResolved: true, ptpCaptured: false },
      },
    ],
    promises: [
      { id: "jp1", amount: 10000, promisedDate: isoFuture(12), createdAt: iso(3), channel: "voice", handler: "David Chen", status: "upcoming", reminderStatus: "queued" },
    ],
    disputes: [
      {
        id: "D-4805",
        type: "Incorrect EMI",
        amount: 7200,
        transcriptSnippet: "\"…the EMI got debited twice in October — please refund the extra one.\"",
        status: "awaiting_customer",
        slaLabel: "6h 40m left",
        filedAt: iso(19),
        assignee: "David Chen",
      },
    ],
    documents: [
      { id: "jdoc1", type: "Payment schedule", requestedVia: "voice", requestedAt: iso(3), deliveryChannel: "email", status: "sent" },
    ],
    notes: [],
  },
  {
    id: "farah-ahmed",
    name: "Farah Ahmed",
    accountId: "AC-71992",
    risk: "high",
    outstanding: 3980,
    minimumDue: 480,
    lastContact: iso(0, 17),
    assignedTo: "Sara Khan",
    contact: {
      phonePrimary: "+91 90•••• ••14",
      email: "farah.a@mail.co.in",
      address: "Jubilee Hills, Hyderabad 500033",
      timezone: "Asia/Kolkata (IST)",
      language: "English + Urdu",
      preferredWindow: "10:00–17:00 IST",
      dnd: true,
    },
    account: {
      product: "Credit Card",
      openedOn: iso(280),
      apr: 39.9,
      sanctionedAmount: 60000,
      bucket: "31-60",
      dpd: 45,
      riskScore: 621,
    },
    consent: [
      { channel: "call", optedIn: false, source: "self-serve", capturedAt: iso(10) },
      { channel: "whatsapp", optedIn: true, source: "self-serve", capturedAt: iso(280) },
      { channel: "sms", optedIn: false, source: "self-serve", capturedAt: iso(10) },
      { channel: "email", optedIn: true, source: "self-serve", capturedAt: iso(280) },
    ],
    ledger: buildLedger(5, 1400),
    emi: buildEmi(5, 1400),
    interactions: [
      {
        id: "fi1",
        channel: "whatsapp",
        handler: { kind: "bot", name: "CollectionsBot" },
        startedAt: iso(0, 17),
        duration: "1m 45s",
        disposition: "Bot contained",
        sentiment: "positive",
        sentimentDelta: "up",
        summary: "Sent payment link. Customer completed ₹480 payment on link.",
        intents: { queryResolved: true },
      },
    ],
    promises: [
      { id: "fp1", amount: 480, promisedDate: iso(0), createdAt: iso(0), channel: "whatsapp", handler: "CollectionsBot", status: "kept", reminderStatus: "acknowledged" },
    ],
    disputes: [],
    documents: [],
    notes: [
      { id: "fn1", author: "Sara Khan", at: iso(10), text: "Customer opted out of calls after complaint. WhatsApp-only.", pinned: true },
    ],
  },
  {
    id: "rahul-sinha",
    name: "Rahul Sinha",
    accountId: "AC-58004",
    risk: "medium",
    outstanding: 15300,
    minimumDue: 2800,
    lastContact: iso(4),
    assignedTo: "Rohan Verma",
    contact: {
      phonePrimary: "+91 88•••• ••31",
      email: "rahul.s@mail.co.in",
      address: "Salt Lake, Kolkata 700091",
      timezone: "Asia/Kolkata (IST)",
      language: "English + Bengali",
      preferredWindow: "10:00–19:00 IST",
      dnd: false,
    },
    account: {
      product: "Personal Loan",
      openedOn: iso(540),
      apr: 16.2,
      sanctionedAmount: 250000,
      bucket: "0-30",
      dpd: 38,
      riskScore: 671,
    },
    consent: [
      { channel: "call", optedIn: true, source: "self-serve", capturedAt: iso(540) },
      { channel: "whatsapp", optedIn: true, source: "self-serve", capturedAt: iso(540) },
      { channel: "sms", optedIn: true, source: "self-serve", capturedAt: iso(540) },
      { channel: "email", optedIn: true, source: "self-serve", capturedAt: iso(540) },
    ],
    ledger: buildLedger(6, 3800),
    emi: buildEmi(6, 3800),
    interactions: [],
    promises: [],
    disputes: [],
    documents: [],
    notes: [],
  },
  {
    id: "cust-susanth",
    name: "Susanth",
    accountId: "AC-SUSANTH",
    risk: "medium",
    outstanding: 62400,
    minimumDue: 4800,
    lastContact: iso(0, 14),
    assignedTo: "Priya Nair",
    contact: {
      phonePrimary: "+91 98•••• ••01",
      phoneAlt: "+91 98•••• ••02",
      email: "susanth@example.com",
      address: "12, MG Road, Chennai 600002",
      timezone: "Asia/Kolkata (IST)",
      language: "English + Tamil",
      preferredWindow: "10:00–19:00 IST",
      dnd: false,
    },
    account: {
      product: "Personal Loan",
      openedOn: iso(420),
      apr: 14.5,
      sanctionedAmount: 250000,
      bucket: "31-60",
      dpd: 32,
      riskScore: 58,
    },
    consent: [
      { channel: "call", optedIn: true, source: "self-serve", capturedAt: iso(420) },
      { channel: "whatsapp", optedIn: true, source: "bot-captured", capturedAt: iso(14) },
      { channel: "sms", optedIn: true, source: "self-serve", capturedAt: iso(420) },
      { channel: "email", optedIn: false, source: "self-serve", capturedAt: iso(90) },
    ],
    ledger: [
      { id: "LED-SUSANTH-1", date: iso(90), description: "EMI due #1", type: "charge", amount: 4800, balance: 72000 },
      { id: "LED-SUSANTH-2", date: iso(85), description: "UPI payment", type: "payment", amount: -4800, balance: 67200 },
      { id: "LED-SUSANTH-3", date: iso(60), description: "EMI due #2", type: "charge", amount: 4800, balance: 72000 },
      { id: "LED-SUSANTH-4", date: iso(55), description: "UPI payment", type: "payment", amount: -4800, balance: 67200 },
      { id: "LED-SUSANTH-5", date: iso(40), description: "EMI due", type: "charge", amount: 4800, balance: 72000 },
      { id: "LED-SUSANTH-6", date: iso(37), description: "UPI payment", type: "payment", amount: -4800, balance: 67200 },
      { id: "LED-SUSANTH-7", date: iso(35), description: "Late fee", type: "fee", amount: 350, balance: 67550 },
      { id: "LED-SUSANTH-8", date: iso(32), description: "Goodwill late-fee waiver", type: "waiver", amount: -350, balance: 67200 },
      { id: "LED-SUSANTH-9", date: iso(10), description: "EMI due (current)", type: "charge", amount: 4800, balance: 72000 },
      { id: "LED-SUSANTH-10", date: iso(8), description: "Partial UPI", type: "payment", amount: -4800, balance: 67200 },
      { id: "LED-SUSANTH-11", date: iso(5), description: "Interest capitalization", type: "adjustment", amount: 200, balance: 67400 },
      { id: "LED-SUSANTH-12", date: iso(2), description: "Goodwill adjustment settle", type: "payment", amount: -1000, balance: 62400 },
    ],
    emi: [
      { id: "EMI-SUSANTH-1", index: 1, dueDate: iso(60), amount: 4800, paidOn: iso(55), paidAmount: 4800, status: "paid", balanceCarried: 0 },
      { id: "EMI-SUSANTH-2", index: 2, dueDate: iso(30), amount: 4800, paidOn: iso(28), paidAmount: 4800, status: "paid", balanceCarried: 0 },
      { id: "EMI-SUSANTH-3", index: 3, dueDate: iso(0), amount: 4800, status: "overdue", balanceCarried: 4800 },
      { id: "EMI-SUSANTH-4", index: 4, dueDate: isoFuture(30), amount: 4800, status: "upcoming", balanceCarried: 9600 },
    ],
    interactions: [
      {
        id: "IX-SUSANTH-WA1",
        channel: "whatsapp",
        handler: { kind: "bot", name: "CollectionsBot v2.4" },
        startedAt: iso(0, 14),
        duration: "4m 10s",
        disposition: "PTP captured",
        sentiment: "neutral",
        sentimentDelta: "flat",
        summary: "WhatsApp bot thread — Susanth asking about EMI options. Logged Friday promise.",
        intents: { queryResolved: false, ptpCaptured: true },
      },
      {
        id: "IX-SUSANTH-WA2",
        channel: "whatsapp",
        handler: { kind: "bot", name: "CollectionsBot v2.4" },
        startedAt: iso(12, 11),
        duration: "3m 00s",
        disposition: "Bot contained",
        sentiment: "neutral",
        sentimentDelta: "flat",
        summary: "Balance and late-fee FAQ. Customer asked about fee waiver — dispute later filed.",
        intents: { queryResolved: true },
      },
      {
        id: "IX-SUSANTH-VOICE1",
        channel: "voice",
        handler: { kind: "human", name: "Priya Nair" },
        startedAt: iso(28, 16),
        duration: "5m 12s",
        disposition: "PTP captured (broken)",
        sentiment: "negative",
        sentimentDelta: "down",
        summary: "Outbound call — Susanth committed ₹4,800 by month-end then missed. Prefers WhatsApp follow-ups.",
        intents: { ptpCaptured: true },
      },
    ],
    promises: [
      { id: "PTP-SUSANTH-1", amount: 4800, promisedDate: isoFuture(5), createdAt: iso(0), channel: "whatsapp", handler: "CollectionsBot v2.4", status: "upcoming", reminderStatus: "queued" },
      { id: "PTP-SUSANTH-2", amount: 4800, promisedDate: iso(20), createdAt: iso(28), channel: "voice", handler: "Priya Nair", status: "broken", reminderStatus: "sent" },
      { id: "PTP-SUSANTH-3", amount: 2400, promisedDate: iso(45), createdAt: iso(52), channel: "whatsapp", handler: "CollectionsBot v2.4", status: "kept", reminderStatus: "acknowledged" },
    ],
    disputes: [
      {
        id: "D-SUSANTH-1",
        type: "fee_waiver",
        amount: 350,
        transcriptSnippet: "Can you waive the late fee from last month?",
        status: "under_review",
        slaLabel: "2d left",
        filedAt: iso(10),
        assignee: "Priya Nair",
      },
    ],
    documents: [
      {
        id: "DOC-SUSANTH-1",
        type: "statement",
        requestedVia: "whatsapp",
        requestedAt: iso(9),
        deliveryChannel: "whatsapp",
        status: "sent",
      },
    ],
    notes: [
      {
        id: "NOTE-SUSANTH-1",
        author: "Priya Nair",
        at: iso(0, 15),
        text: "WhatsApp-preferred customer. EMI date flexibility OK within 7 days.",
        pinned: true,
      },
      {
        id: "NOTE-SUSANTH-2",
        author: "Priya Nair",
        at: iso(12),
        text: "Broken PTP on file — start with smaller commitment on next touch.",
      },
    ],
  },
];

export const customers = _customers;

export function getCustomer(id: string): Customer | undefined {
  return _customers.find((c) => c.id === id);
}

// ---- utility formatters ----
export function fmtMoney(n: number | null | undefined) {
  const value = typeof n === "number" && Number.isFinite(n) ? n : 0;
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  return `${sign}₹${abs.toLocaleString("en-IN")}`;
}

export function fmtDate(iso: string | null | undefined, opts?: Intl.DateTimeFormatOptions) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", ...(opts ?? { month: "short", day: "numeric", year: "numeric" }) });
}

export function fmtDateTime(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function fmtRelative(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  const days = Math.floor(diff / 86400);
  if (days < 7) return `${days}d ago`;
  return fmtDate(iso, { month: "short", day: "numeric" });
}
