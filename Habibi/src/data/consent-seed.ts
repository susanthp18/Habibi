// Consent & Communication Preferences seed
// BFSI-grade DND / opt-out registry. Consumed by /consent and (conceptually) by
// Callback + Inbox screens via `isContactableNow`.

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
  endHour: number;   // 0-23
}

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
}

// ---- helpers ----
const now = new Date();
function iso(daysAgo: number, hour = 10) {
  const d = new Date(now);
  d.setDate(d.getDate() - daysAgo);
  d.setHours(hour, 5, 0, 0);
  return d.toISOString();
}
function isoFuture(daysAhead: number) {
  return iso(-daysAhead);
}

const WEEKDAYS = [1, 2, 3, 4, 5];
const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6];

function ch(
  channel: ConsentChannel,
  status: ConsentStatus,
  capturedDaysAgo: number,
  cap: number,
  used: number,
  source: ChannelConsent["source"] = "Onboarding",
): ChannelConsent {
  return { channel, status, capturedAt: iso(capturedDaysAgo), source, frequencyCapPerWeek: cap, usedThisWeek: used };
}

let auditCounter = 0;
function audit(daysAgo: number, actor: string, action: string): ConsentAuditEntry {
  auditCounter += 1;
  return { id: `A${auditCounter}`, at: iso(daysAgo), actor, action };
}

let optCounter = 0;
function opt(
  daysAgo: number,
  channel: OptOutEvent["channel"],
  source: OptOutSource,
  actor: string,
  note: string,
): OptOutEvent {
  optCounter += 1;
  return { id: `O${optCounter}`, at: iso(daysAgo), channel, source, actor, note };
}

// ---- seed rows ----
export const consentRecords: ConsentRecord[] = [
  {
    id: "cn-vikram",
    customerId: "vikram-rao",
    customerName: "Vikram Rao",
    accountId: "AC-77410",
    phone: "+91 98200 11223",
    email: "vikram.rao@example.com",
    timezone: "Asia/Kolkata",
    segment: "Priority",
    channels: [
      ch("call", "opted_in", 210, 5, 4),
      ch("whatsapp", "opted_in", 210, 6, 2),
      ch("sms", "opted_in", 210, 4, 1),
      ch("email", "opted_in", 210, 3, 0),
    ],
    allowedWindow: { days: WEEKDAYS, startHour: 10, endHour: 19 },
    consentExpiresAt: isoFuture(240),
    onDndRegistry: false,
    optOutLog: [],
    audit: [audit(210, "Onboarding", "Consent captured on account opening"), audit(14, "Priya Nair", "Frequency cap raised on call to 5/wk")],
  },
  {
    id: "cn-anita",
    customerId: "anita-desai",
    customerName: "Anita Desai",
    accountId: "AC-88214",
    phone: "+91 98111 44556",
    email: "anita.desai@example.com",
    timezone: "Asia/Kolkata",
    segment: "Retail",
    channels: [
      ch("call", "dnd", 45, 3, 0, "Regulator"),
      ch("whatsapp", "opted_in", 300, 5, 3),
      ch("sms", "opted_out", 60, 4, 0, "IVR"),
      ch("email", "opted_in", 300, 3, 1),
    ],
    allowedWindow: { days: WEEKDAYS, startHour: 11, endHour: 18 },
    consentExpiresAt: isoFuture(18),
    onDndRegistry: true,
    optOutLog: [
      opt(45, "call", "Regulator", "TRAI DND sync", "Number listed on National DND registry."),
      opt(60, "sms", "IVR", "Customer", "Pressed 9 to opt out of SMS reminders."),
    ],
    audit: [audit(300, "Onboarding", "Consent captured"), audit(60, "System", "SMS opt-out via IVR"), audit(45, "System", "DND registry sync"), audit(3, "Meera Iyer", "Consent expiry alert sent to customer")],
  },
  {
    id: "cn-neha",
    customerId: "neha-kapoor",
    customerName: "Neha Kapoor",
    accountId: "AC-90112",
    phone: "+91 90040 22334",
    email: "neha.kapoor@example.com",
    timezone: "Asia/Kolkata",
    segment: "Retail",
    channels: [
      ch("call", "opted_in", 120, 4, 4),
      ch("whatsapp", "opted_in", 120, 6, 6),
      ch("sms", "opted_in", 120, 3, 1),
      ch("email", "opted_in", 120, 3, 0),
    ],
    allowedWindow: { days: ALL_DAYS, startHour: 9, endHour: 20 },
    consentExpiresAt: isoFuture(120),
    onDndRegistry: false,
    optOutLog: [],
    audit: [audit(120, "Onboarding", "Consent captured"), audit(2, "System", "WhatsApp cap reached (6/6) — messaging paused for the week")],
  },
  {
    id: "cn-james",
    customerId: "james-patel",
    customerName: "James Patel",
    accountId: "AC-66803",
    phone: "+91 98333 88774",
    email: "james.patel@example.com",
    timezone: "Asia/Kolkata",
    segment: "SME",
    channels: [
      ch("call", "opted_out", 22, 4, 0, "Agent"),
      ch("whatsapp", "opted_in", 400, 5, 2),
      ch("sms", "opted_out", 22, 3, 0, "Agent"),
      ch("email", "opted_in", 400, 3, 2),
    ],
    allowedWindow: { days: WEEKDAYS, startHour: 10, endHour: 17 },
    consentExpiresAt: isoFuture(65),
    onDndRegistry: false,
    optOutLog: [
      opt(22, "call", "Agent", "David Chen", "Customer requested no calls after dispute; email preferred."),
      opt(22, "sms", "Agent", "David Chen", "SMS opt-out captured in same conversation."),
    ],
    audit: [audit(400, "Onboarding", "Consent captured"), audit(22, "David Chen", "Captured multi-channel opt-out during dispute call")],
  },
  {
    id: "cn-farah",
    customerId: "farah-ahmed",
    customerName: "Farah Ahmed",
    accountId: "AC-71992",
    phone: "+91 98444 55667",
    email: "farah.ahmed@example.com",
    timezone: "Asia/Kolkata",
    segment: "Retail",
    channels: [
      ch("call", "opted_in", 180, 4, 1),
      ch("whatsapp", "opted_in", 180, 5, 0),
      ch("sms", "opted_in", 180, 3, 0),
      ch("email", "expired", 180, 3, 0),
    ],
    allowedWindow: { days: WEEKDAYS, startHour: 10, endHour: 19 },
    consentExpiresAt: isoFuture(-4), // expired 4 days ago
    onDndRegistry: false,
    optOutLog: [],
    audit: [audit(180, "Onboarding", "Consent captured"), audit(4, "System", "Consent window expired — renewal required")],
  },
  {
    id: "cn-rahul",
    customerId: "rahul-sinha",
    customerName: "Rahul Sinha",
    accountId: "AC-58004",
    phone: "+91 98007 66009",
    email: "rahul.sinha@example.com",
    timezone: "Asia/Kolkata",
    segment: "Retail",
    channels: [
      ch("call", "opted_in", 90, 5, 2),
      ch("whatsapp", "opted_out", 12, 5, 0, "WhatsApp Reply"),
      ch("sms", "opted_in", 90, 4, 1),
      ch("email", "opted_in", 90, 3, 0),
    ],
    allowedWindow: { days: ALL_DAYS, startHour: 10, endHour: 20 },
    consentExpiresAt: isoFuture(300),
    onDndRegistry: false,
    optOutLog: [opt(12, "whatsapp", "WhatsApp Reply", "Customer", 'Replied "STOP" to reminder thread.')],
    audit: [audit(90, "Onboarding", "Consent captured"), audit(12, "System", "WhatsApp STOP keyword — opt-out recorded")],
  },
  // Additional synthetic records to fill the registry
  ...Array.from({ length: 18 }, (_, i): ConsentRecord => {
    const idx = i + 1;
    const seg: ConsentRecord["segment"] = idx % 5 === 0 ? "Priority" : idx % 3 === 0 ? "SME" : "Retail";
    const dnd = idx % 7 === 0;
    const expiringSoon = idx % 6 === 0;
    const wa = idx % 4 === 0 ? "opted_out" : "opted_in";
    const smsUsed = idx % 3;
    return {
      id: `cn-syn-${idx}`,
      customerId: `syn-${idx}`,
      customerName: [
        "Aarav Shah", "Ishita Menon", "Kabir Reddy", "Diya Nair", "Rohit Bansal",
        "Sneha Iyer", "Aditya Kulkarni", "Priya Verma", "Kunal Bose", "Meera Joshi",
        "Sameer Khan", "Tanvi Kapoor", "Rajat Singh", "Aisha Sheikh", "Nikhil Rao",
        "Pooja Sharma", "Varun Malhotra", "Zoya Ali",
      ][i],
      accountId: `AC-${20000 + idx * 137}`,
      phone: `+91 9${String(80000000 + idx * 12345).padStart(9, "0").slice(0, 9)}`,
      email: `customer${idx}@example.com`,
      timezone: "Asia/Kolkata",
      segment: seg,
      channels: [
        ch("call", dnd ? "dnd" : "opted_in", 100 + idx, 4, idx % 4, dnd ? "Regulator" : "Onboarding"),
        ch("whatsapp", wa, 100 + idx, 5, wa === "opted_in" ? idx % 5 : 0),
        ch("sms", "opted_in", 100 + idx, 3, smsUsed),
        ch("email", "opted_in", 100 + idx, 3, idx % 3),
      ],
      allowedWindow: idx % 2 === 0 ? { days: WEEKDAYS, startHour: 10, endHour: 19 } : { days: ALL_DAYS, startHour: 9, endHour: 20 },
      consentExpiresAt: expiringSoon ? isoFuture(10 + (idx % 15)) : isoFuture(120 + idx * 5),
      onDndRegistry: dnd,
      optOutLog: wa === "opted_out"
        ? [opt(idx, "whatsapp", "WhatsApp Reply", "Customer", 'Replied "STOP".')]
        : [],
      audit: [audit(100 + idx, "Onboarding", "Consent captured")],
    };
  }),
];

// ---- domain helpers ----

export function channelStatus(rec: ConsentRecord, channel: ConsentChannel): ChannelConsent | undefined {
  return rec.channels.find((c) => c.channel === channel);
}

export function isWithinAllowedWindow(rec: ConsentRecord, at: Date = new Date()): boolean {
  const day = at.getDay();
  const hour = at.getHours();
  return rec.allowedWindow.days.includes(day) && hour >= rec.allowedWindow.startHour && hour < rec.allowedWindow.endHour;
}

export function isConsentExpired(rec: ConsentRecord, at: Date = new Date()): boolean {
  return new Date(rec.consentExpiresAt).getTime() < at.getTime();
}

export type ContactableReason =
  | "ok"
  | "channel_opted_out"
  | "channel_dnd"
  | "dnd_registry"
  | "outside_hours"
  | "frequency_cap"
  | "consent_expired";

export interface ContactableResult {
  ok: boolean;
  reason: ContactableReason;
  message: string;
}

export function isContactableNow(
  rec: ConsentRecord,
  channel: ConsentChannel,
  at: Date = new Date(),
): ContactableResult {
  if (isConsentExpired(rec, at)) return { ok: false, reason: "consent_expired", message: "Consent window expired — renew before contacting." };
  if (rec.onDndRegistry && channel === "call") return { ok: false, reason: "dnd_registry", message: "Customer is on national DND registry (calls only)." };
  const cc = channelStatus(rec, channel);
  if (!cc) return { ok: false, reason: "channel_opted_out", message: "Channel not configured." };
  if (cc.status === "dnd") return { ok: false, reason: "channel_dnd", message: `${channel} marked DND.` };
  if (cc.status === "opted_out") return { ok: false, reason: "channel_opted_out", message: `Customer opted out of ${channel}.` };
  if (cc.status === "expired") return { ok: false, reason: "consent_expired", message: `${channel} consent expired.` };
  if (cc.usedThisWeek >= cc.frequencyCapPerWeek) return { ok: false, reason: "frequency_cap", message: `Weekly cap reached (${cc.usedThisWeek}/${cc.frequencyCapPerWeek}).` };
  if (!isWithinAllowedWindow(rec, at)) return { ok: false, reason: "outside_hours", message: `Outside allowed hours (${rec.allowedWindow.startHour}:00–${rec.allowedWindow.endHour}:00).` };
  return { ok: true, reason: "ok", message: "Contactable now" };
}

export function contactableSummary(rec: ConsentRecord, at: Date = new Date()): {
  status: "green" | "amber" | "red";
  reasons: string[];
} {
  const channels: ConsentChannel[] = ["call", "whatsapp", "sms", "email"];
  const results = channels.map((c) => ({ c, r: isContactableNow(rec, c, at) }));
  const ok = results.filter((x) => x.r.ok);
  const reasons = results.filter((x) => !x.r.ok).map((x) => `${x.c}: ${x.r.message}`);
  if (ok.length === channels.length) return { status: "green", reasons: ["All channels available."] };
  if (ok.length === 0) return { status: "red", reasons };
  return { status: "amber", reasons };
}

// ---- filters ----

export interface ConsentFilterState {
  q: string;
  channel: "all" | ConsentChannel;
  status: "all" | "contactable" | "dnd" | "expiring" | "opted_out";
  segment: "all" | ConsentRecord["segment"];
}

export const defaultConsentFilters: ConsentFilterState = {
  q: "",
  channel: "all",
  status: "all",
  segment: "all",
};

export function filterConsents(rows: ConsentRecord[], f: ConsentFilterState): ConsentRecord[] {
  const q = f.q.trim().toLowerCase();
  return rows.filter((r) => {
    if (q) {
      const hay = `${r.customerName} ${r.accountId} ${r.phone} ${r.email}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    if (f.segment !== "all" && r.segment !== f.segment) return false;
    if (f.channel !== "all") {
      const cc = channelStatus(r, f.channel);
      if (!cc) return false;
    }
    if (f.status === "dnd" && !r.onDndRegistry && !r.channels.some((c) => c.status === "dnd")) return false;
    if (f.status === "opted_out" && !r.channels.some((c) => c.status === "opted_out")) return false;
    if (f.status === "expiring") {
      const days = (new Date(r.consentExpiresAt).getTime() - Date.now()) / 86400000;
      if (days > 30) return false;
    }
    if (f.status === "contactable") {
      const s = contactableSummary(r);
      if (s.status === "red") return false;
    }
    return true;
  });
}

export function daysUntil(iso: string): number {
  return Math.round((new Date(iso).getTime() - Date.now()) / 86400000);
}

export const CHANNEL_LABEL: Record<ConsentChannel, string> = {
  call: "Call",
  whatsapp: "WhatsApp",
  sms: "SMS",
  email: "Email",
};

// ---- in-memory mutators (mock branch of api/consent.ts) ----

function findOrThrow(id: string): ConsentRecord {
  const rec = consentRecords.find((r) => r.id === id);
  if (!rec) throw new Error(`consent not found: ${id}`);
  return rec;
}

function pushAudit(rec: ConsentRecord, action: string, actor = "You") {
  rec.audit = [...rec.audit, { id: `A${Date.now().toString(36)}`, at: new Date().toISOString(), actor, action }];
}

export function saveConsentPreferences(
  id: string,
  patch: { channels: ChannelConsent[]; allowedWindow: AllowedWindow },
  note: string,
): void {
  const rec = findOrThrow(id);
  rec.channels = patch.channels;
  rec.allowedWindow = patch.allowedWindow;
  pushAudit(rec, note || "Consent preferences updated.");
}

export function renewConsent(id: string): void {
  const rec = findOrThrow(id);
  const newExp = new Date();
  newExp.setFullYear(newExp.getFullYear() + 1);
  rec.consentExpiresAt = newExp.toISOString();
  rec.channels = rec.channels.map((c) => (c.status === "expired" ? { ...c, status: "opted_in" as const } : c));
  pushAudit(rec, "Consent renewed for 12 months.");
}

export function captureOptOut(
  id: string,
  evt: { channel: ConsentChannel | "all"; source: OptOutSource; note: string },
): void {
  const rec = findOrThrow(id);
  const nowIso = new Date().toISOString();
  const affected: ConsentChannel[] = evt.channel === "all" ? ["call", "whatsapp", "sms", "email"] : [evt.channel];
  rec.channels = rec.channels.map((c) =>
    affected.includes(c.channel) ? { ...c, status: "opted_out", capturedAt: nowIso, source: evt.source } : c,
  );
  rec.optOutLog = [
    ...rec.optOutLog,
    { id: `O${Date.now().toString(36)}`, at: nowIso, channel: evt.channel, source: evt.source, actor: "You", note: evt.note },
  ];
  pushAudit(rec, `Opt-out captured via ${evt.source} (${evt.channel}).`);
}

export function toggleDndRegistry(id: string, on: boolean): void {
  const rec = findOrThrow(id);
  rec.onDndRegistry = on;
  rec.channels = on
    ? rec.channels.map((c) => (c.channel === "call" ? { ...c, status: "dnd" as const } : c))
    : rec.channels.map((c) => (c.channel === "call" && c.status === "dnd" ? { ...c, status: "opted_in" as const } : c));
  pushAudit(rec, on ? "Added to DND registry (calls blocked)." : "Removed from DND registry.");
}

