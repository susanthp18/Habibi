/**
 * Domain / wire types for the customer360 surface.
 *
 * Lived in a `data/*-seed.ts` mock factory. Moved here so live `api/`
 * modules do not import their contract from fixtures (WP-048).
 *
 * Nullability follows `backend/schemas.py` (`CustomerResponse` and nested
 * models). A field the server sends as `str | None` is `string | null` here —
 * not `string`. `tsc` must fail a `.slice` on `Interaction.summary`.
 */

import type { DisputeSla } from "./dispute-sla";

export type RiskLevel = "critical" | "high" | "medium" | "low";
export type Channel = "voice" | "whatsapp" | "chat" | "email" | "sms";
export type Sentiment = "positive" | "neutral" | "negative";
export type LedgerType = "charge" | "payment" | "fee" | "adjustment" | "waiver";
export type EmiStatus = "paid" | "upcoming" | "overdue" | "partial";
export type PtpStatus = "upcoming" | "kept" | "broken" | "partial";
export type DisputeStatus = "new" | "under_review" | "awaiting_customer" | "resolved" | "rejected";
export type DocStatus = "requested" | "generating" | "sent" | "failed";
export interface LedgerEntry {
  id: string;
  date: string; // ISO
  description: string;
  type: LedgerType;
  amount: number; // signed; charges +, payments -
  balance: number | null;
  invoiceId?: string | null;
}
export interface EmiRow {
  id: string;
  index: number;
  dueDate: string;
  amount: number;
  paidOn?: string | null;
  paidAmount?: number | null;
  status: EmiStatus;
  balanceCarried: number | null;
}
/** Mirrors `InteractionResponse` — `startedAt` / `disposition` / `summary` are null on the wire. */
export interface Interaction {
  id: string;
  channel: Channel;
  handler: { kind: "bot" | "human"; name: string };
  startedAt: string | null;
  duration: string;
  disposition: string | null;
  sentiment: Sentiment;
  sentimentDelta: "up" | "down" | "flat";
  summary: string | null;
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
/**
 * The 360 contract for a dispute. `sla`/`slaLabel`/`slaMinutes` are the same
 * server-computed fields the disputes board renders (see data/dispute-sla.ts),
 * which is what keeps the two screens word-for-word identical.
 */
export interface Dispute extends DisputeSla {
  id: string;
  type: string;
  amount: number | null;
  transcriptSnippet: string;
  status: DisputeStatus;
  filedAt: string;
  assignee?: string | null;
}
export interface DocumentRequest {
  id: string;
  type: string;
  requestedVia: Channel;
  requestedAt: string;
  deliveryChannel: "email" | "whatsapp" | "sms";
  status: DocStatus;
  source?: string | null;
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
  /** Plain `str` on ConsentResponse (the seed rows say "seed"). */
  source: string;
  capturedAt: string | null;
}
export interface Contact {
  phonePrimary: string;
  phoneAlt?: string | null;
  email: string;
  address: string;
  timezone: string;
  language: string;
  preferredWindow: string; // e.g. "10:00–19:00 IST"
  /**
   * Days the borrower consented to be contacted on, e.g. "Mon–Sat".
   * Mirrors consent_records.allowed_days, which the live API resolves
   * server-side — mock-only, so optional and absent from CustomerResponse.
   */
  allowedDays?: string;
  dnd: boolean;
}
export interface AccountFacts {
  /** Plain `str` on AccountResponse — the wire is not limited to the seed's three. */
  product: string;
  openedOn: string | null;
  apr: number | null;
  sanctionedAmount: number | null;
  bucket: string | null;
  dpd: number;
  riskScore: number | null;
}
export interface Customer {
  id: string;
  name: string;
  accountId: string;
  risk: RiskLevel;
  outstanding: number;
  minimumDue: number | null;
  lastContact: string | null;
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
