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
}
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
export interface ContactableSummary {
  status: "green" | "amber" | "red";
  reasons: string[];
}
export interface ConsentFilterState {
  q: string;
  channel: "all" | ConsentChannel;
  status: "all" | "contactable" | "dnd" | "expiring" | "opted_out";
  segment: "all" | ConsentRecord["segment"];
}
