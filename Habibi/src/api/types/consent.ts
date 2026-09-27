/**
 * Domain / wire types for the consent surface.
 *
 * The wire shape the api/ module for this surface reads and writes.
 */

export type ConsentChannel = "call" | "whatsapp" | "sms" | "email";
export type ConsentStatus = "opted_in" | "opted_out" | "dnd" | "expired";
export type OptOutSource = "IVR" | "Agent" | "Web" | "Regulator" | "Bulk Import" | "WhatsApp Reply";
export interface ChannelConsent {
  channel: ConsentChannel;
  status: ConsentStatus;
  capturedAt: string;
  source: OptOutSource | "Onboarding";
  frequencyCapPerWeek: number;
  usedThisWeek: number;
  /** `status` is the servicing consent (what the contact Gate reads for
   *  collections contact); this is the promotional one, for offers — null
   *  when never captured. */
  promotional?: ConsentStatus | null;
}
/** One channel write in a consent PATCH. Absent `purpose` = servicing. */
export type ConsentChannelWrite = Partial<ChannelConsent> &
  Pick<ChannelConsent, "channel" | "status"> & { purpose?: "servicing" | "promotional" };
export interface AllowedWindow {
  // 0 = Sun ... 6 = Sat
  days: number[];
  startHour: number; // 0-23
  endHour: number; // 0-23
}
/** Channel-matrix save. `allowedWindow` is present only when the operator edited it. */
export type ConsentPreferencesPatch = {
  channels: ChannelConsent[];
  allowedWindow?: AllowedWindow;
};
export interface OptOutEvent {
  id: string;
  at: string;
  channel: ConsentChannel | "all";
  source: OptOutSource;
  actor: string; // agent name, "System", "Customer"
  note: string;
}
export interface ConsentAuditEntry {
  id: string;
  at: string;
  actor: string;
  action: string;
}
export interface ConsentRecord {
  id: string;
  customerId: string;
  customerName: string;
  accountId: string;
  phone: string;
  email: string;
  timezone: string;
  segment: "Retail" | "SME" | "Priority";
  channels: ChannelConsent[];
  allowedWindow: AllowedWindow;
  consentExpiresAt: string; // ISO
  onDndRegistry: boolean;
  optOutLog: OptOutEvent[];
  audit: ConsentAuditEntry[];
  outreachToday?: number;
  dailyCap?: number;
  lastDecisionReason?: string | null;
  /** The row's reading across the four channels, in the borrower's zone. */
  contactable: ContactableSummary;
}
/** One CSV row as parsed in the browser; the server validates every cell. */
export interface ConsentImportRow {
  customer_id: string;
  channel: string;
  status: string;
  purpose?: string;
  dnd?: string;
  note?: string;
}
export type ConsentImportChange = "none" | "opt_in" | "opt_out" | "dnd_on" | "dnd_off";
export interface ConsentImportRowResult {
  row: number;
  customerId: string;
  channel: ConsentChannel | null;
  status: string | null;
  purpose: string;
  dnd: boolean | null;
  note: string;
  ok: boolean;
  error: string | null;
  change: ConsentImportChange;
  dndChange: "dnd_on" | "dnd_off" | null;
}
export interface ConsentImportResult {
  dryRun: boolean;
  total: number;
  valid: number;
  invalid: number;
  changes: Record<ConsentImportChange, number>;
  applied: number;
  results: ConsentImportRowResult[];
}
export interface ContactableSummary {
  status: "green" | "amber" | "red";
  reasons: string[];
}
export interface ConsentFilterState {
  q: string;
  /** A channel narrows to customers opted in (servicing) on it. */
  channel: "all" | ConsentChannel;
  status: "all" | "contactable" | "dnd" | "expiring" | "opted_out";
  segment: "all" | ConsentRecord["segment"];
}
