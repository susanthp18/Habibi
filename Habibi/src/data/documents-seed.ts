// Document Fulfillment Desk seed data
// Mutable in-memory store — mirrors the promises/disputes-seed pattern.

import {
  customers as _customers,
  fmtMoney as _fmtMoney,
  fmtDate as _fmtDate,
} from "./customer360-seed";

export const fmtMoney = _fmtMoney;
export const fmtDate = _fmtDate;

export type DocStatus = "requested" | "generating" | "sent" | "failed";
export type DocChannel = "whatsapp" | "email" | "sms";
export type RequestedVia =
  "bot_voice" | "bot_chat" | "agent" | "mcp" | "clerk" | "vision" | "inbox";
export type DocSource = "crm" | "vision" | "clerk" | "mcp";
export type DocType =
  | "account_statement"
  | "no_dues_certificate"
  | "interest_certificate"
  | "foreclosure_letter"
  | "loan_schedule"
  | "payment_receipt"
  | "kyc_letter";

export interface DocEvent {
  at: string;
  label: string;
  actor?: string;
  tone?: "info" | "success" | "warn" | "danger";
}

export interface DocRequest {
  id: string;
  customerId: string;
  customerName: string;
  accountId: string;
  accountTail: string;
  docType: DocType;
  period?: string;
  requestedVia: RequestedVia;
  requestedAt: string;
  deliveryChannel: DocChannel;
  deliveryTarget: string;
  status: DocStatus;
  source?: DocSource;
  templateId: string;
  generatedAt?: string;
  sentAt?: string;
  failedReason?: string;
  sizeKb?: number;
  attempts: number;
  assignee: string;
  events: DocEvent[];
}

export interface Template {
  id: string;
  name: string;
  docType: DocType;
  description: string;
  previewLines: string[];
}

export const STATUS_ORDER: DocStatus[] = ["requested", "generating", "sent", "failed"];

export const STATUS_LABELS: Record<DocStatus, string> = {
  requested: "Requested",
  generating: "Generating",
  sent: "Sent",
  failed: "Failed",
};

export const DOC_TYPE_LABELS: Record<DocType, string> = {
  account_statement: "Account statement",
  no_dues_certificate: "No-dues certificate",
  interest_certificate: "Interest certificate",
  foreclosure_letter: "Foreclosure letter",
  loan_schedule: "Loan schedule",
  payment_receipt: "Payment receipt",
  kyc_letter: "KYC letter",
};

export const CHANNEL_LABELS: Record<DocChannel, string> = {
  whatsapp: "WhatsApp",
  email: "Email",
  sms: "SMS link",
};

/**
 * Every origin a document request can have. Mirrors the backend's own list —
 * `schemas.py` `requestedVia` and the `document_requests_requested_via_check`
 * constraint — which has carried all seven since Phase 4.
 *
 * Four were missing here, and this map is not just labels: `FiltersBar` builds
 * the "Requested via" dropdown from `Object.keys(VIA_LABELS)`. So requests
 * arriving from MCP, the clerk card, the vision pipeline, and the inbox were
 * unfilterable — the rows existed and the column rendered, but there was no way
 * to select them, and no way to tell from the UI that the list was partial.
 */
export const VIA_LABELS: Record<RequestedVia, string> = {
  bot_voice: "Bot · Voice",
  bot_chat: "Bot · Chat",
  agent: "Agent",
  mcp: "MCP agent",
  clerk: "Clerk",
  vision: "Vision scan",
  inbox: "Inbox",
};

// ---- templates ----
export const TEMPLATES: Template[] = [
  {
    id: "T-STMT-6M",
    name: "Statement · Last 6 months",
    docType: "account_statement",
    description: "Full transaction history for the past 6 months, with running balance.",
    previewLines: [
      "HDFC Bank · Account Statement",
      "Account: {{account}} · Customer: {{name}}",
      "Period: {{period}}",
      "— Opening balance, transactions, interest, closing balance —",
      "Generated on {{today}} · System-signed PDF",
    ],
  },
  {
    id: "T-STMT-12M",
    name: "Statement · Last 12 months",
    docType: "account_statement",
    description: "12-month statement for tax filing or income verification.",
    previewLines: [
      "HDFC Bank · 12-Month Account Statement",
      "Account: {{account}} · Customer: {{name}}",
      "Period: {{period}}",
      "Includes month-wise summary and category totals.",
    ],
  },
  {
    id: "T-NODUES",
    name: "No-dues certificate",
    docType: "no_dues_certificate",
    description: "Confirms the loan is fully closed with zero outstanding.",
    previewLines: [
      "This is to certify that {{name}} (Account {{account}})",
      "has cleared all outstanding dues as on {{today}}.",
      "No further amounts are payable under this account.",
      "— Authorised Signatory, HDFC Retail Collections —",
    ],
  },
  {
    id: "T-INTCERT",
    name: "Interest certificate · FY 25-26",
    docType: "interest_certificate",
    description: "Interest paid during the financial year, for tax deduction.",
    previewLines: [
      "Interest Paid Certificate · FY 2025-26",
      "Customer: {{name}} · Account: {{account}}",
      "Principal repaid: ₹— · Interest paid: ₹—",
      "Eligible under Section 24(b) / 80C as applicable.",
    ],
  },
  {
    id: "T-FORECLOSE",
    name: "Foreclosure letter",
    docType: "foreclosure_letter",
    description: "Foreclosure amount, valid for 7 days from date of issue.",
    previewLines: [
      "Foreclosure Quote · {{account}}",
      "Principal outstanding: ₹— · Interest till date: ₹—",
      "Foreclosure charges: ₹— · Total payable: ₹—",
      "Quote valid till {{plus7}}.",
    ],
  },
  {
    id: "T-SCHEDULE",
    name: "Loan repayment schedule",
    docType: "loan_schedule",
    description: "Full amortisation schedule with EMI breakup.",
    previewLines: [
      "Loan Repayment Schedule · {{account}}",
      "EMI: ₹— · Tenure: — months · ROI: —%",
      "Month-wise principal, interest, and balance.",
    ],
  },
  {
    id: "T-RECEIPT",
    name: "Payment receipt",
    docType: "payment_receipt",
    description: "Confirms a specific payment with reference number.",
    previewLines: [
      "Payment Receipt · {{account}}",
      "Amount: ₹— · Mode: — · Ref: —",
      "Received on {{today}}. Thank you.",
    ],
  },
  {
    id: "T-KYC",
    name: "KYC confirmation letter",
    docType: "kyc_letter",
    description: "Confirms KYC on file is current and verified.",
    previewLines: [
      "This is to confirm that KYC documents for {{name}}",
      "(Account {{account}}) are current and verified as on {{today}}.",
    ],
  },
];

export function templatesFor(t: DocType): Template[] {
  return TEMPLATES.filter((tp) => tp.docType === t);
}

// ---- helpers ----
const now = new Date();
function hoursISO(offsetHours: number) {
  const d = new Date(now);
  d.setHours(d.getHours() + offsetHours, 0, 0, 0);
  return d.toISOString();
}
function tailOf(accountId: string) {
  return accountId.slice(-4);
}
function maskEmail(e: string) {
  const [u, d] = e.split("@");
  if (!u || !d) return e;
  return `${u.slice(0, 2)}•••@${d}`;
}

const CUST_POOL = _customers.map((c) => ({
  id: c.id,
  name: c.name,
  accountId: c.accountId,
  phone: c.contact.phonePrimary,
  email: c.contact.email,
}));

const EXTRA = [
  {
    id: "aditya-verma",
    name: "Aditya Verma",
    accountId: "AC-99201",
    phone: "+91 98•••• ••11",
    email: "aditya.v@mail.co.in",
  },
  {
    id: "meera-joshi",
    name: "Meera Joshi",
    accountId: "AC-99202",
    phone: "+91 98•••• ••22",
    email: "meera.j@mail.co.in",
  },
  {
    id: "nikhil-bansal",
    name: "Nikhil Bansal",
    accountId: "AC-99203",
    phone: "+91 98•••• ••33",
    email: "nikhil.b@mail.co.in",
  },
  {
    id: "riya-chawla",
    name: "Riya Chawla",
    accountId: "AC-99204",
    phone: "+91 98•••• ••44",
    email: "riya.c@mail.co.in",
  },
  {
    id: "sneha-pillai",
    name: "Sneha Pillai",
    accountId: "AC-99205",
    phone: "+91 98•••• ••55",
    email: "sneha.p@mail.co.in",
  },
  {
    id: "farhan-khan",
    name: "Farhan Khan",
    accountId: "AC-99206",
    phone: "+91 98•••• ••66",
    email: "farhan.k@mail.co.in",
  },
];

const POOL = [...CUST_POOL, ...EXTRA];

const AGENTS = [
  "Priya Nair",
  "Rohan Sethi",
  "Ananya Iyer",
  "Kabir Rao",
  "Sana Kapoor",
  "Unassigned",
];

export const CURRENT_AGENT = "Priya Nair";

interface Blueprint {
  docType: DocType;
  templateId: string;
  period?: string;
  via: RequestedVia;
  channel: DocChannel;
  hoursAgo: number;
  status: DocStatus;
  failedReason?: string;
  assignee?: string;
}

const BLUEPRINTS: Blueprint[] = [
  // Fresh requests — bias here
  {
    docType: "account_statement",
    templateId: "T-STMT-6M",
    period: "May–Oct 2026",
    via: "bot_voice",
    channel: "whatsapp",
    hoursAgo: 1,
    status: "requested",
  },
  {
    docType: "account_statement",
    templateId: "T-STMT-6M",
    period: "May–Oct 2026",
    via: "bot_chat",
    channel: "email",
    hoursAgo: 2,
    status: "requested",
  },
  {
    docType: "interest_certificate",
    templateId: "T-INTCERT",
    period: "FY 2025-26",
    via: "bot_voice",
    channel: "email",
    hoursAgo: 3,
    status: "requested",
  },
  {
    docType: "foreclosure_letter",
    templateId: "T-FORECLOSE",
    via: "agent",
    channel: "email",
    hoursAgo: 4,
    status: "requested",
  },
  {
    docType: "no_dues_certificate",
    templateId: "T-NODUES",
    via: "bot_voice",
    channel: "whatsapp",
    hoursAgo: 6,
    status: "requested",
  },
  {
    docType: "loan_schedule",
    templateId: "T-SCHEDULE",
    via: "bot_chat",
    channel: "email",
    hoursAgo: 12,
    status: "requested",
  },
  {
    docType: "payment_receipt",
    templateId: "T-RECEIPT",
    via: "bot_voice",
    channel: "whatsapp",
    hoursAgo: 20,
    status: "requested",
  },
  {
    docType: "kyc_letter",
    templateId: "T-KYC",
    via: "agent",
    channel: "email",
    hoursAgo: 28,
    status: "requested",
  },

  // Generating (in-flight)
  {
    docType: "account_statement",
    templateId: "T-STMT-12M",
    period: "Nov 2025–Oct 2026",
    via: "bot_voice",
    channel: "whatsapp",
    hoursAgo: 1,
    status: "generating",
    assignee: "Priya Nair",
  },
  {
    docType: "interest_certificate",
    templateId: "T-INTCERT",
    period: "FY 2025-26",
    via: "bot_chat",
    channel: "email",
    hoursAgo: 2,
    status: "generating",
    assignee: "Rohan Sethi",
  },
  {
    docType: "foreclosure_letter",
    templateId: "T-FORECLOSE",
    via: "agent",
    channel: "whatsapp",
    hoursAgo: 1,
    status: "generating",
    assignee: "Ananya Iyer",
  },

  // Sent today
  {
    docType: "account_statement",
    templateId: "T-STMT-6M",
    period: "Apr–Sep 2026",
    via: "bot_voice",
    channel: "email",
    hoursAgo: 5,
    status: "sent",
    assignee: "Priya Nair",
  },
  {
    docType: "no_dues_certificate",
    templateId: "T-NODUES",
    via: "bot_chat",
    channel: "whatsapp",
    hoursAgo: 8,
    status: "sent",
    assignee: "Sana Kapoor",
  },
  {
    docType: "payment_receipt",
    templateId: "T-RECEIPT",
    via: "bot_voice",
    channel: "whatsapp",
    hoursAgo: 10,
    status: "sent",
    assignee: "Kabir Rao",
  },
  {
    docType: "loan_schedule",
    templateId: "T-SCHEDULE",
    via: "agent",
    channel: "email",
    hoursAgo: 14,
    status: "sent",
    assignee: "Ananya Iyer",
  },
  {
    docType: "interest_certificate",
    templateId: "T-INTCERT",
    period: "FY 2024-25",
    via: "bot_chat",
    channel: "email",
    hoursAgo: 20,
    status: "sent",
    assignee: "Rohan Sethi",
  },

  // Sent earlier
  {
    docType: "account_statement",
    templateId: "T-STMT-12M",
    period: "FY 2024-25",
    via: "bot_voice",
    channel: "email",
    hoursAgo: 40,
    status: "sent",
    assignee: "Priya Nair",
  },
  {
    docType: "kyc_letter",
    templateId: "T-KYC",
    via: "agent",
    channel: "email",
    hoursAgo: 60,
    status: "sent",
    assignee: "Kabir Rao",
  },

  // Failed
  {
    docType: "account_statement",
    templateId: "T-STMT-6M",
    period: "May–Oct 2026",
    via: "bot_voice",
    channel: "whatsapp",
    hoursAgo: 3,
    status: "failed",
    failedReason: "WhatsApp opt-in expired — falling back to Email",
    assignee: "Priya Nair",
  },
  {
    docType: "foreclosure_letter",
    templateId: "T-FORECLOSE",
    via: "bot_chat",
    channel: "email",
    hoursAgo: 6,
    status: "failed",
    failedReason: "Email bounced · mailbox full",
    assignee: "Sana Kapoor",
  },
  {
    docType: "interest_certificate",
    templateId: "T-INTCERT",
    period: "FY 2025-26",
    via: "agent",
    channel: "email",
    hoursAgo: 18,
    status: "failed",
    failedReason: "PDF generator timed out",
    assignee: "Rohan Sethi",
  },
  {
    docType: "payment_receipt",
    templateId: "T-RECEIPT",
    via: "bot_voice",
    channel: "sms",
    hoursAgo: 22,
    status: "failed",
    failedReason: "SMS gateway 5xx",
    assignee: "Ananya Iyer",
  },
];

function eventsFor(bp: Blueprint, requestedAt: string): DocEvent[] {
  const evts: DocEvent[] = [
    { at: requestedAt, label: `Captured by ${VIA_LABELS[bp.via]}`, tone: "info" },
  ];
  if (bp.status !== "requested") {
    evts.push({
      at: requestedAt,
      label: `Assigned to ${bp.assignee ?? "queue"}`,
      actor: "System",
      tone: "info",
    });
    evts.push({ at: requestedAt, label: "Generation started", actor: "System", tone: "info" });
  }
  if (bp.status === "sent") {
    evts.push({
      at: requestedAt,
      label: `Delivered via ${CHANNEL_LABELS[bp.channel]}`,
      actor: "System",
      tone: "success",
    });
  }
  if (bp.status === "failed") {
    evts.push({
      at: requestedAt,
      label: bp.failedReason ?? "Delivery failed",
      actor: "System",
      tone: "danger",
    });
  }
  return evts;
}

const _docs: DocRequest[] = BLUEPRINTS.map((bp, i) => {
  const c = POOL[i % POOL.length];
  const requestedAt = hoursISO(-bp.hoursAgo);
  const target = bp.channel === "email" ? maskEmail(c.email) : c.phone;
  const assignee =
    bp.assignee ?? (bp.status === "requested" ? "Unassigned" : AGENTS[i % (AGENTS.length - 1)]);
  return {
    id: `DOC-${(7001 + i).toString()}`,
    customerId: c.id,
    customerName: c.name,
    accountId: c.accountId,
    accountTail: tailOf(c.accountId),
    docType: bp.docType,
    period: bp.period,
    requestedVia: bp.via,
    requestedAt,
    deliveryChannel: bp.channel,
    deliveryTarget: target,
    status: bp.status,
    templateId: bp.templateId,
    generatedAt: bp.status === "sent" || bp.status === "generating" ? requestedAt : undefined,
    sentAt: bp.status === "sent" ? requestedAt : undefined,
    failedReason: bp.failedReason,
    sizeKb: bp.status === "sent" ? 120 + ((i * 37) % 400) : undefined,
    attempts: bp.status === "failed" ? 1 : bp.status === "sent" ? 1 : 0,
    assignee,
    events: eventsFor(bp, requestedAt),
  };
});

export const documents: DocRequest[] = _docs;

// ---- Aging tone ----
export type AgingTone = "fresh" | "warn" | "stale" | "done";
export interface AgingInfo {
  tone: AgingTone;
  hours: number;
  label: string;
}
export function agingInfo(d: DocRequest): AgingInfo {
  if (d.status === "sent") return { tone: "done", hours: 0, label: "Delivered" };
  const hours = Math.max(0, (Date.now() - new Date(d.requestedAt).getTime()) / 3600000);
  const rounded = Math.round(hours);
  const label = hours < 1 ? `${Math.round(hours * 60)}m` : `${rounded}h`;
  if (d.status === "failed") return { tone: "stale", hours, label };
  if (hours < 4) return { tone: "fresh", hours, label };
  if (hours < 24) return { tone: "warn", hours, label };
  return { tone: "stale", hours, label };
}

// ---- Filters ----
export interface Filters {
  search: string;
  docTypes: DocType[]; // empty = all
  channels: DocChannel[];
  vias: RequestedVia[];
  statuses: DocStatus[];
  range: "today" | "7d" | "30d" | "all";
  assignee: string | "all";
}

export const defaultFilters: Filters = {
  search: "",
  docTypes: [],
  channels: [],
  vias: [],
  statuses: [],
  range: "all",
  assignee: "all",
};

export function filterDocs(list: DocRequest[], f: Filters): DocRequest[] {
  const now = Date.now();
  const cutoff =
    f.range === "today"
      ? now - 86400000
      : f.range === "7d"
        ? now - 7 * 86400000
        : f.range === "30d"
          ? now - 30 * 86400000
          : 0;
  return list.filter((d) => {
    if (f.assignee !== "all" && d.assignee !== f.assignee) return false;
    if (f.docTypes.length && !f.docTypes.includes(d.docType)) return false;
    if (f.channels.length && !f.channels.includes(d.deliveryChannel)) return false;
    if (f.vias.length && !f.vias.includes(d.requestedVia)) return false;
    if (f.statuses.length && !f.statuses.includes(d.status)) return false;
    if (cutoff && new Date(d.requestedAt).getTime() < cutoff) return false;
    if (f.search) {
      const q = f.search.toLowerCase();
      const hay =
        `${d.customerName} ${d.accountId} ${d.id} ${DOC_TYPE_LABELS[d.docType]} ${d.period ?? ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

export function listAssignees(): string[] {
  return Array.from(new Set(documents.map((d) => d.assignee))).sort();
}

// ---- Metrics ----
export function computeMetrics(list: DocRequest[]) {
  const dayAgo = Date.now() - 86400000;
  const open = list.filter((d) => d.status === "requested" || d.status === "generating");
  const generating = list.filter((d) => d.status === "generating");
  const sentToday = list.filter(
    (d) => d.status === "sent" && new Date(d.sentAt ?? d.requestedAt).getTime() >= dayAgo,
  );
  const failed = list.filter((d) => d.status === "failed");

  const sentSpans = list
    .filter((d) => d.status === "sent" && d.sentAt)
    .map((d) => (new Date(d.sentAt!).getTime() - new Date(d.requestedAt).getTime()) / 60000);
  const avgFulfilMins = sentSpans.length
    ? Math.round(sentSpans.reduce((a, b) => a + b, 0) / sentSpans.length)
    : 0;

  const counts: Record<DocStatus, number> = { requested: 0, generating: 0, sent: 0, failed: 0 };
  list.forEach((d) => (counts[d.status] += 1));

  return {
    openCount: open.length,
    generatingCount: generating.length,
    sentTodayCount: sentToday.length,
    failedCount: failed.length,
    avgFulfilMins,
    counts,
    total: list.length,
  };
}

// ---- Mutations ----
function appendEvent(d: DocRequest, e: DocEvent) {
  d.events.push(e);
}

export function setStatus(id: string, next: DocStatus, extra?: Partial<DocRequest>) {
  const d = documents.find((x) => x.id === id);
  if (!d) return;
  d.status = next;
  Object.assign(d, extra ?? {});
  const at = new Date().toISOString();
  appendEvent(d, {
    at,
    label: `Status → ${STATUS_LABELS[next]}`,
    actor: CURRENT_AGENT,
    tone: next === "sent" ? "success" : next === "failed" ? "danger" : "info",
  });
}

export function assign(id: string, assignee: string) {
  const d = documents.find((x) => x.id === id);
  if (!d) return;
  const from = d.assignee;
  d.assignee = assignee;
  appendEvent(d, {
    at: new Date().toISOString(),
    label: `Reassigned ${from} → ${assignee}`,
    actor: CURRENT_AGENT,
    tone: "info",
  });
}

export function reassignChannel(id: string, channel: DocChannel) {
  const d = documents.find((x) => x.id === id);
  if (!d) return;
  const from = d.deliveryChannel;
  d.deliveryChannel = channel;
  appendEvent(d, {
    at: new Date().toISOString(),
    label: `Channel ${CHANNEL_LABELS[from]} → ${CHANNEL_LABELS[channel]}`,
    actor: CURRENT_AGENT,
    tone: "info",
  });
}

export function changeTemplate(id: string, templateId: string) {
  const d = documents.find((x) => x.id === id);
  if (!d) return;
  const tpl = TEMPLATES.find((t) => t.id === templateId);
  if (!tpl) return;
  d.templateId = templateId;
  appendEvent(d, {
    at: new Date().toISOString(),
    label: `Template set · ${tpl.name}`,
    actor: CURRENT_AGENT,
    tone: "info",
  });
}

export function markGenerating(id: string) {
  const d = documents.find((x) => x.id === id);
  if (!d) return;
  d.status = "generating";
  d.generatedAt = new Date().toISOString();
  d.failedReason = undefined;
  d.attempts += 1;
  appendEvent(d, {
    at: d.generatedAt,
    label: "Generation started",
    actor: CURRENT_AGENT,
    tone: "info",
  });
}

export function markSent(id: string) {
  const d = documents.find((x) => x.id === id);
  if (!d) return;
  const at = new Date().toISOString();
  d.status = "sent";
  d.sentAt = at;
  d.sizeKb = d.sizeKb ?? 140 + Math.floor(Math.random() * 400);
  appendEvent(d, {
    at,
    label: `Delivered via ${CHANNEL_LABELS[d.deliveryChannel]} → ${d.deliveryTarget}`,
    actor: "System",
    tone: "success",
  });
}

export function markFailed(id: string, reason: string) {
  const d = documents.find((x) => x.id === id);
  if (!d) return;
  d.status = "failed";
  d.failedReason = reason;
  appendEvent(d, {
    at: new Date().toISOString(),
    label: `Failed · ${reason}`,
    actor: "System",
    tone: "danger",
  });
}

export function retry(id: string) {
  const d = documents.find((x) => x.id === id);
  if (!d) return;
  d.status = "requested";
  d.failedReason = undefined;
  appendEvent(d, {
    at: new Date().toISOString(),
    label: "Retry queued",
    actor: CURRENT_AGENT,
    tone: "info",
  });
}

export interface NewRequestInput {
  customerId: string;
  docType: DocType;
  period?: string;
  channel: DocChannel;
  templateId: string;
}

export function createRequest(input: NewRequestInput): DocRequest {
  const c = POOL.find((x) => x.id === input.customerId) ?? POOL[0];
  const at = new Date().toISOString();
  const target = input.channel === "email" ? maskEmail(c.email) : c.phone;
  const doc: DocRequest = {
    id: `DOC-${(7100 + documents.length).toString()}`,
    customerId: c.id,
    customerName: c.name,
    accountId: c.accountId,
    accountTail: tailOf(c.accountId),
    docType: input.docType,
    period: input.period,
    requestedVia: "agent",
    requestedAt: at,
    deliveryChannel: input.channel,
    deliveryTarget: target,
    status: "requested",
    templateId: input.templateId,
    attempts: 0,
    assignee: CURRENT_AGENT,
    events: [
      { at, label: "Captured by Agent", tone: "info" },
      { at, label: `Assigned to ${CURRENT_AGENT}`, actor: "System", tone: "info" },
    ],
  };
  documents.unshift(doc);
  return doc;
}

export function customerPool() {
  return POOL.map((c) => ({ id: c.id, name: c.name, accountId: c.accountId }));
}

export function renderPreview(tpl: Template, d: DocRequest): string[] {
  const today = fmtDate(new Date().toISOString(), { dateStyle: "medium" });
  const plus7 = fmtDate(new Date(Date.now() + 7 * 86400000).toISOString(), { dateStyle: "medium" });
  return tpl.previewLines.map((line) =>
    line
      .replaceAll("{{name}}", d.customerName)
      .replaceAll("{{account}}", d.accountId)
      .replaceAll("{{period}}", d.period ?? "—")
      .replaceAll("{{today}}", today)
      .replaceAll("{{plus7}}", plus7),
  );
}
