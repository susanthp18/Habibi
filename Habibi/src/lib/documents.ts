import { fmtDate } from "@/lib/format";
import type {
  DocStatus,
  DocChannel,
  RequestedVia,
  DocSource,
  DocType,
  DocEvent,
  DocRequest,
  Template,
  AgingTone,
  AgingInfo,
  DocumentFilters,
  NewRequestInput,
} from "@/api/types/documents";

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
/** The template a new request starts on. */
export const DEFAULT_TEMPLATE: Template = {
  id: "T-STMT-6M",
  name: "Statement · Last 6 months",
  docType: "account_statement",
  description: "Full transaction history for the past 6 months, with running balance.",
  previewLines: [
    "BigTapp Bank · Account Statement",
    "Account: {{account}} · Customer: {{name}}",
    "Period: {{period}}",
    "— Opening balance, transactions, interest, closing balance —",
    "Generated on {{today}} · System-signed PDF",
  ],
};

export const TEMPLATES: Template[] = [
  DEFAULT_TEMPLATE,
  {
    id: "T-STMT-12M",
    name: "Statement · Last 12 months",
    docType: "account_statement",
    description: "12-month statement for tax filing or income verification.",
    previewLines: [
      "BigTapp Bank · 12-Month Account Statement",
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
      "— Authorised Signatory, BigTapp Retail Collections —",
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

export const defaultFilters: DocumentFilters = {
  search: "",
  docTypes: [],
  channels: [],
  vias: [],
  statuses: [],
  range: "all",
  assignee: "all",
};

export function filterDocs(list: DocRequest[], f: DocumentFilters): DocRequest[] {
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
