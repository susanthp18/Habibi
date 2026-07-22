// Disputes & Exceptions Queue seed data
// Mutable in-memory store — mirrors the promises-seed pattern.

import { customers as _customers, fmtMoney as _fmtMoney, fmtDate as _fmtDate } from "./customer360-seed";

export const fmtMoney = _fmtMoney;
export const fmtDate = _fmtDate;

export type DisputeStatus =
  | "new"
  | "under_review"
  | "awaiting_customer"
  | "resolved"
  | "rejected";

export type DisputeType =
  | "paid_already"
  | "wrong_amount"
  | "not_my_account"
  | "fee_waiver"
  | "duplicate_charge"
  | "fraud";

export type DisputeSource = "bot_voice" | "bot_chat" | "agent";
export type DisputePriority = "low" | "normal" | "high" | "urgent";

export type ResolutionCode =
  | "valid_waive_fee"
  | "valid_reverse_charge"
  | "invalid_no_action"
  | "duplicate"
  | "needs_more_info";

export interface DisputeEvent {
  at: string;
  label: string;
  actor?: string;
  tone?: "info" | "success" | "warn" | "danger";
}

export interface Evidence {
  id: string;
  name: string;
  kind: "screenshot" | "receipt" | "statement" | "audio" | "other";
  uploadedAt: string;
  uploadedBy: string;
}

export interface Dispute {
  id: string;
  customerId: string;
  customerName: string;
  accountId: string;
  accountTail: string;
  type: DisputeType;
  disputedAmount: number;
  source: DisputeSource;
  transcriptSnippet: string;
  originConversationId?: string;
  capturedAt: string;
  slaDueAt: string;
  status: DisputeStatus;
  assignee: string;
  priority: DisputePriority;
  evidence: Evidence[];
  events: DisputeEvent[];
  resolutionCode?: ResolutionCode;
  resolutionNotes?: string;
}

export const STATUS_ORDER: DisputeStatus[] = [
  "new",
  "under_review",
  "awaiting_customer",
  "resolved",
  "rejected",
];

export const STATUS_LABELS: Record<DisputeStatus, string> = {
  new: "New",
  under_review: "Under Review",
  awaiting_customer: "Awaiting Customer",
  resolved: "Resolved",
  rejected: "Rejected",
};

export const TYPE_LABELS: Record<DisputeType, string> = {
  paid_already: "Paid already",
  wrong_amount: "Wrong amount",
  not_my_account: "Not my account",
  fee_waiver: "Fee waiver request",
  duplicate_charge: "Duplicate charge",
  fraud: "Fraud / unauthorised",
};

export const SOURCE_LABELS: Record<DisputeSource, string> = {
  bot_voice: "Bot · Voice",
  bot_chat: "Bot · Chat",
  agent: "Agent",
};

export const RESOLUTION_LABELS: Record<ResolutionCode, string> = {
  valid_waive_fee: "Valid — waive fee",
  valid_reverse_charge: "Valid — reverse charge",
  invalid_no_action: "Invalid — no action",
  duplicate: "Duplicate dispute",
  needs_more_info: "Needs more information",
};

// ---- helpers ----
const now = new Date();
function hoursISO(offsetHours: number) {
  const d = new Date(now);
  d.setHours(d.getHours() + offsetHours, 0, 0, 0);
  return d.toISOString();
}

const CUST_POOL = _customers.map((c) => ({
  id: c.id,
  name: c.name,
  accountId: c.accountId,
  outstanding: c.outstanding,
}));

// Fallback pool for extra volume
const EXTRA = [
  { id: "aditya-verma", name: "Aditya Verma", accountId: "AC-99201" },
  { id: "meera-joshi", name: "Meera Joshi", accountId: "AC-99202" },
  { id: "nikhil-bansal", name: "Nikhil Bansal", accountId: "AC-99203" },
  { id: "riya-chawla", name: "Riya Chawla", accountId: "AC-99204" },
  { id: "sneha-pillai", name: "Sneha Pillai", accountId: "AC-99205" },
  { id: "farhan-khan", name: "Farhan Khan", accountId: "AC-99206" },
  { id: "isha-kapoor", name: "Isha Kapoor", accountId: "AC-99207" },
  { id: "sameer-ahuja", name: "Sameer Ahuja", accountId: "AC-99208" },
];

const POOL = [...CUST_POOL, ...EXTRA.map((c) => ({ ...c, outstanding: 32000 }))];

const AGENTS = ["Priya Nair", "Rohan Sethi", "Ananya Iyer", "Kabir Rao", "Sana Kapoor", "Unassigned"];

interface Blueprint {
  type: DisputeType;
  amount: number;
  source: DisputeSource;
  snippet: string;
  capturedHoursAgo: number;
  slaHoursFromCapture: number; // SLA window
  status: DisputeStatus;
  priority: DisputePriority;
  assignee?: string;
}

const BLUEPRINTS: Blueprint[] = [
  // NEW (fresh, some breaching)
  { type: "paid_already", amount: 12400, source: "bot_voice", snippet: "I paid this on the 12th via UPI, reference 8827194. Why is it still showing due?", capturedHoursAgo: 2, slaHoursFromCapture: 24, status: "new", priority: "high" },
  { type: "wrong_amount", amount: 3200, source: "bot_chat", snippet: "The amount you're asking for is wrong — my EMI is 4,850, not 8,050.", capturedHoursAgo: 6, slaHoursFromCapture: 24, status: "new", priority: "normal" },
  { type: "fraud", amount: 18500, source: "bot_voice", snippet: "I never authorised this transaction. Please block the account immediately.", capturedHoursAgo: 1, slaHoursFromCapture: 4, status: "new", priority: "urgent" },
  { type: "not_my_account", amount: 5400, source: "bot_chat", snippet: "You keep calling me about an account I don't own. Please stop.", capturedHoursAgo: 22, slaHoursFromCapture: 24, status: "new", priority: "high" },
  { type: "duplicate_charge", amount: 2100, source: "agent", snippet: "You've charged me twice for the same month. Please refund one.", capturedHoursAgo: 30, slaHoursFromCapture: 24, status: "new", priority: "high" },

  // UNDER REVIEW
  { type: "paid_already", amount: 9800, source: "bot_voice", snippet: "Payment cleared from my bank on the 3rd, please check with your ops team.", capturedHoursAgo: 26, slaHoursFromCapture: 48, status: "under_review", priority: "normal", assignee: "Priya Nair" },
  { type: "fee_waiver", amount: 750, source: "bot_chat", snippet: "I've been a customer for 8 years, please waive the late fee this once.", capturedHoursAgo: 40, slaHoursFromCapture: 72, status: "under_review", priority: "low", assignee: "Rohan Sethi" },
  { type: "wrong_amount", amount: 4600, source: "bot_voice", snippet: "The interest calculation looks wrong — I need a breakdown.", capturedHoursAgo: 18, slaHoursFromCapture: 48, status: "under_review", priority: "normal", assignee: "Ananya Iyer" },
  { type: "fraud", amount: 22300, source: "agent", snippet: "Card was cloned in Dubai — I've filed a police complaint.", capturedHoursAgo: 12, slaHoursFromCapture: 24, status: "under_review", priority: "urgent", assignee: "Kabir Rao" },

  // AWAITING CUSTOMER
  { type: "paid_already", amount: 6700, source: "bot_chat", snippet: "Sent you the payment screenshot on WhatsApp yesterday.", capturedHoursAgo: 60, slaHoursFromCapture: 120, status: "awaiting_customer", priority: "normal", assignee: "Sana Kapoor" },
  { type: "not_my_account", amount: 11200, source: "bot_voice", snippet: "That number doesn't belong to me anymore — must be the previous owner.", capturedHoursAgo: 96, slaHoursFromCapture: 168, status: "awaiting_customer", priority: "normal", assignee: "Priya Nair" },
  { type: "fee_waiver", amount: 500, source: "bot_chat", snippet: "First-time offender, please consider waiving.", capturedHoursAgo: 72, slaHoursFromCapture: 120, status: "awaiting_customer", priority: "low", assignee: "Rohan Sethi" },

  // RESOLVED
  { type: "paid_already", amount: 8300, source: "bot_voice", snippet: "Payment was via NEFT on the 1st, reference NEFT-77281.", capturedHoursAgo: 120, slaHoursFromCapture: 48, status: "resolved", priority: "normal", assignee: "Ananya Iyer" },
  { type: "duplicate_charge", amount: 1500, source: "bot_chat", snippet: "Charged twice on the 20th, please refund.", capturedHoursAgo: 96, slaHoursFromCapture: 48, status: "resolved", priority: "normal", assignee: "Priya Nair" },
  { type: "fee_waiver", amount: 350, source: "agent", snippet: "Long-tenure customer requested one-time goodwill waiver.", capturedHoursAgo: 140, slaHoursFromCapture: 72, status: "resolved", priority: "low", assignee: "Sana Kapoor" },

  // REJECTED
  { type: "not_my_account", amount: 4200, source: "bot_voice", snippet: "This isn't my account.", capturedHoursAgo: 200, slaHoursFromCapture: 72, status: "rejected", priority: "normal", assignee: "Kabir Rao" },
  { type: "fee_waiver", amount: 1100, source: "bot_chat", snippet: "Please waive — I forgot to pay.", capturedHoursAgo: 240, slaHoursFromCapture: 72, status: "rejected", priority: "low", assignee: "Rohan Sethi" },
  { type: "wrong_amount", amount: 900, source: "agent", snippet: "You've over-charged me.", capturedHoursAgo: 180, slaHoursFromCapture: 48, status: "rejected", priority: "normal", assignee: "Ananya Iyer" },
];

function tailOf(accountId: string) {
  return accountId.slice(-4);
}

function eventsForStatus(bp: Blueprint, capturedAt: string): DisputeEvent[] {
  const evts: DisputeEvent[] = [
    { at: capturedAt, label: `Captured by ${SOURCE_LABELS[bp.source]}`, tone: "info" },
  ];
  if (bp.status !== "new") {
    evts.push({ at: capturedAt, label: `Assigned to ${bp.assignee ?? "queue"}`, actor: "System", tone: "info" });
    evts.push({ at: capturedAt, label: "Moved to Under Review", actor: bp.assignee, tone: "info" });
  }
  if (bp.status === "awaiting_customer") {
    evts.push({ at: capturedAt, label: "Requested evidence from customer via WhatsApp", actor: bp.assignee, tone: "info" });
  }
  if (bp.status === "resolved") {
    evts.push({ at: capturedAt, label: "Evidence reviewed — dispute upheld", actor: bp.assignee, tone: "success" });
    evts.push({ at: capturedAt, label: "Resolution written back to CRM", actor: "System", tone: "success" });
  }
  if (bp.status === "rejected") {
    evts.push({ at: capturedAt, label: "Insufficient evidence — dispute rejected", actor: bp.assignee, tone: "danger" });
  }
  return evts;
}

function evidenceForStatus(bp: Blueprint, capturedAt: string, seed: number): Evidence[] {
  if (bp.status === "new") return [];
  const list: Evidence[] = [];
  if (bp.type === "paid_already" || bp.type === "duplicate_charge") {
    list.push({
      id: `EV-${seed}-1`,
      name: `payment-receipt-${seed}.pdf`,
      kind: "receipt",
      uploadedAt: capturedAt,
      uploadedBy: "Customer",
    });
  }
  list.push({
    id: `EV-${seed}-2`,
    name: `call-recording-${seed}.mp3`,
    kind: "audio",
    uploadedAt: capturedAt,
    uploadedBy: "System",
  });
  if (bp.type === "fraud") {
    list.push({
      id: `EV-${seed}-3`,
      name: `police-complaint-${seed}.pdf`,
      kind: "other",
      uploadedAt: capturedAt,
      uploadedBy: "Customer",
    });
  }
  return list;
}

const _disputes: Dispute[] = BLUEPRINTS.map((bp, i) => {
  const c = POOL[i % POOL.length];
  const capturedAt = hoursISO(-bp.capturedHoursAgo);
  const slaDueAt = hoursISO(-bp.capturedHoursAgo + bp.slaHoursFromCapture);
  const assignee = bp.assignee ?? (bp.status === "new" ? "Unassigned" : AGENTS[i % (AGENTS.length - 1)]);
  return {
    id: `DSP-${(4001 + i).toString()}`,
    customerId: c.id,
    customerName: c.name,
    accountId: c.accountId,
    accountTail: tailOf(c.accountId),
    type: bp.type,
    disputedAmount: bp.amount,
    source: bp.source,
    transcriptSnippet: bp.snippet,
    originConversationId: bp.source !== "agent" ? `CONV-${5000 + i}` : undefined,
    capturedAt,
    slaDueAt,
    status: bp.status,
    assignee,
    priority: bp.priority,
    evidence: evidenceForStatus(bp, capturedAt, i),
    events: eventsForStatus(bp, capturedAt),
    resolutionCode: bp.status === "resolved" ? "valid_reverse_charge" : bp.status === "rejected" ? "invalid_no_action" : undefined,
    resolutionNotes:
      bp.status === "resolved"
        ? "Verified payment against core banking ledger — reversed the outstanding entry."
        : bp.status === "rejected"
          ? "No supporting evidence provided after two follow-ups."
          : undefined,
  };
});

export const disputes: Dispute[] = _disputes;

// ---- SLA helper ----
export type SlaTone = "ok" | "warn" | "breach" | "done";
export interface SlaInfo {
  tone: SlaTone;
  label: string;
  msRemaining: number;
}

export function slaInfo(d: Dispute): SlaInfo {
  if (d.status === "resolved" || d.status === "rejected") {
    return { tone: "done", label: "Closed", msRemaining: 0 };
  }
  const due = new Date(d.slaDueAt).getTime();
  const ms = due - Date.now();
  const totalWindow = due - new Date(d.capturedAt).getTime();
  const abs = Math.abs(ms);
  const hrs = Math.floor(abs / 3600000);
  const mins = Math.floor((abs % 3600000) / 60000);
  const label = `${hrs}h ${mins}m ${ms < 0 ? "over" : "left"}`;
  if (ms < 0) return { tone: "breach", label, msRemaining: ms };
  if (ms < totalWindow * 0.25) return { tone: "warn", label, msRemaining: ms };
  return { tone: "ok", label, msRemaining: ms };
}

// ---- Filters ----
export interface Filters {
  search: string;
  types: DisputeType[]; // empty = all
  sources: DisputeSource[]; // empty = all
  assignee: string | "all";
  sla: "all" | "at_risk" | "breached";
  amount: "any" | "lt5" | "5to25" | "gt25";
  myQueue: boolean;
}

export const defaultFilters: Filters = {
  search: "",
  types: [],
  sources: [],
  assignee: "all",
  sla: "all",
  amount: "any",
  myQueue: false,
};

export const CURRENT_AGENT = "Priya Nair";

export function filterDisputes(list: Dispute[], f: Filters): Dispute[] {
  return list.filter((d) => {
    if (f.myQueue && d.assignee !== CURRENT_AGENT) return false;
    if (f.assignee !== "all" && d.assignee !== f.assignee) return false;
    if (f.types.length > 0 && !f.types.includes(d.type)) return false;
    if (f.sources.length > 0 && !f.sources.includes(d.source)) return false;
    if (f.search) {
      const q = f.search.toLowerCase();
      const hay = `${d.customerName} ${d.accountId} ${d.id} ${d.transcriptSnippet}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    if (f.amount !== "any") {
      const a = d.disputedAmount;
      if (f.amount === "lt5" && a >= 5000) return false;
      if (f.amount === "5to25" && (a < 5000 || a > 25000)) return false;
      if (f.amount === "gt25" && a <= 25000) return false;
    }
    if (f.sla !== "all") {
      const s = slaInfo(d);
      if (f.sla === "at_risk" && s.tone !== "warn") return false;
      if (f.sla === "breached" && s.tone !== "breach") return false;
    }
    return true;
  });
}

export function listAssignees(): string[] {
  return Array.from(new Set(disputes.map((d) => d.assignee))).sort();
}

// ---- Metrics ----
export function computeMetrics(list: Dispute[]) {
  const open = list.filter((d) => d.status !== "resolved" && d.status !== "rejected");
  const breaching = open.filter((d) => slaInfo(d).tone === "breach");
  const ages = open.map((d) => (Date.now() - new Date(d.capturedAt).getTime()) / 3600000);
  const avgAgeHrs = ages.length === 0 ? 0 : Math.round(ages.reduce((a, b) => a + b, 0) / ages.length);
  const dayAgo = Date.now() - 86400000;
  const resolvedToday = list.filter(
    (d) => d.status === "resolved" && new Date(d.events[d.events.length - 1]?.at ?? d.capturedAt).getTime() >= dayAgo,
  ).length;
  const weekAgo = Date.now() - 7 * 86400000;
  const closedLast7 = list.filter(
    (d) =>
      (d.status === "resolved" || d.status === "rejected") &&
      new Date(d.events[d.events.length - 1]?.at ?? d.capturedAt).getTime() >= weekAgo,
  );
  const resolvedLast7 = closedLast7.filter((d) => d.status === "resolved").length;
  const resolutionRate = closedLast7.length === 0 ? 0 : Math.round((resolvedLast7 / closedLast7.length) * 100);

  const counts: Record<DisputeStatus, number> = {
    new: 0,
    under_review: 0,
    awaiting_customer: 0,
    resolved: 0,
    rejected: 0,
  };
  const subtotals: Record<DisputeStatus, number> = { ...counts };
  list.forEach((d) => {
    counts[d.status] += 1;
    subtotals[d.status] += d.disputedAmount;
  });

  return {
    openCount: open.length,
    openAmt: open.reduce((s, d) => s + d.disputedAmount, 0),
    breachingCount: breaching.length,
    avgAgeHrs,
    resolvedToday,
    resolutionRate,
    counts,
    subtotals,
  };
}

// ---- Mutations ----
export function moveDispute(id: string, next: DisputeStatus, opts?: { actor?: string; note?: string }) {
  const d = disputes.find((x) => x.id === id);
  if (!d) return;
  const at = new Date().toISOString();
  d.status = next;
  d.events.push({
    at,
    label: `Moved to ${STATUS_LABELS[next]}`,
    actor: opts?.actor ?? CURRENT_AGENT,
    tone: next === "resolved" ? "success" : next === "rejected" ? "danger" : "info",
  });
  if (opts?.note) {
    d.events.push({ at, label: opts.note, actor: opts?.actor ?? CURRENT_AGENT, tone: "info" });
  }
}

export function assignDispute(id: string, assignee: string) {
  const d = disputes.find((x) => x.id === id);
  if (!d) return;
  const from = d.assignee;
  d.assignee = assignee;
  d.events.push({
    at: new Date().toISOString(),
    label: `Reassigned ${from} → ${assignee}`,
    actor: CURRENT_AGENT,
    tone: "info",
  });
}

export function addNote(id: string, note: string) {
  const d = disputes.find((x) => x.id === id);
  if (!d || !note.trim()) return;
  d.events.push({
    at: new Date().toISOString(),
    label: note.trim(),
    actor: CURRENT_AGENT,
    tone: "info",
  });
}

export function attachEvidence(id: string, name: string, kind: Evidence["kind"] = "other") {
  const d = disputes.find((x) => x.id === id);
  if (!d) return;
  const at = new Date().toISOString();
  const ev: Evidence = {
    id: `EV-${Date.now().toString().slice(-6)}`,
    name,
    kind,
    uploadedAt: at,
    uploadedBy: CURRENT_AGENT,
  };
  d.evidence.unshift(ev);
  d.events.push({ at, label: `Evidence attached · ${name}`, actor: CURRENT_AGENT, tone: "info" });
}

export function resolveDispute(id: string, code: ResolutionCode, notes: string) {
  const d = disputes.find((x) => x.id === id);
  if (!d) return;
  const at = new Date().toISOString();
  d.status = "resolved";
  d.resolutionCode = code;
  d.resolutionNotes = notes;
  d.events.push({ at, label: `Resolved · ${RESOLUTION_LABELS[code]}`, actor: CURRENT_AGENT, tone: "success" });
  d.events.push({ at, label: "Written back to CRM (Customer 360 · Disputes)", actor: "System", tone: "success" });
}

export function rejectDispute(id: string, notes: string) {
  const d = disputes.find((x) => x.id === id);
  if (!d) return;
  const at = new Date().toISOString();
  d.status = "rejected";
  d.resolutionCode = "invalid_no_action";
  d.resolutionNotes = notes;
  d.events.push({ at, label: "Rejected", actor: CURRENT_AGENT, tone: "danger" });
  if (notes) d.events.push({ at, label: notes, actor: CURRENT_AGENT, tone: "info" });
}
