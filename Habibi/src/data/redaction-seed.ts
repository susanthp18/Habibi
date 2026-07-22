// Redaction & Export Hub — synthetic PII detection, rules, and export audit log.

export type PiiEntityType =
  | "card"
  | "pan"
  | "phone"
  | "email"
  | "address"
  | "dob"
  | "account"
  | "ifsc"
  | "aadhaar"
  | "custom";

export interface PiiFinding {
  id: string;
  turnId: string;
  type: PiiEntityType;
  start: number; // char offset in turn.text
  end: number;
  text: string;
  masked: string;
  confidence: number; // 0..1
  source: "auto" | "manual";
  accepted: boolean;
}

export interface RedactionTurn {
  id: string;
  t: number;
  speaker: "bot" | "agent" | "customer" | "system";
  text: string;
}

export interface AudioSegment {
  atSec: number;
  durSec: number;
  type: PiiEntityType;
  findingId: string;
  muted: boolean;
}

export interface RedactionRecord {
  id: string;
  callId: string;
  customer: string;
  customerId: string;
  channel: "voice" | "whatsapp" | "sms";
  handler: string;
  occurredAt: string;
  durationSec: number;
  transcript: RedactionTurn[];
  findings: PiiFinding[];
  audioSegments: AudioSegment[];
  reviewed: boolean;
}

export type ExportFormat = "pdf" | "csv" | "audio-zip";
export type ExportScope = "transcript" | "audio" | "metadata";

export interface ExportJob {
  id: string;
  at: string;
  actor: string;
  actorRole: string;
  recordIds: string[];
  format: ExportFormat;
  scope: ExportScope[];
  watermark: string;
  status: "queued" | "ready" | "failed";
  downloadCount: number;
  entitiesRedacted: number;
}

export interface RuleConfig {
  enabled: boolean;
  replacement: string;
  label: string;
}

export type RedactionRules = Record<PiiEntityType, RuleConfig>;

export const DEFAULT_RULES: RedactionRules = {
  card:    { enabled: true,  replacement: "**** **** **** ####", label: "Card number" },
  pan:     { enabled: true,  replacement: "[REDACTED-PAN]",       label: "PAN / SSN" },
  phone:   { enabled: true,  replacement: "+91 ••••••••##",       label: "Phone" },
  email:   { enabled: true,  replacement: "[REDACTED-EMAIL]",     label: "Email" },
  address: { enabled: false, replacement: "[REDACTED-ADDRESS]",   label: "Address" },
  dob:     { enabled: true,  replacement: "[REDACTED-DOB]",       label: "Date of birth" },
  account: { enabled: true,  replacement: "••••####",             label: "Account #" },
  ifsc:    { enabled: false, replacement: "[REDACTED-IFSC]",      label: "IFSC" },
  aadhaar: { enabled: true,  replacement: "•••• •••• ####",       label: "Aadhaar" },
  custom:  { enabled: false, replacement: "[REDACTED]",           label: "Custom pattern" },
};

export const ENTITY_TYPES: PiiEntityType[] = [
  "card", "pan", "phone", "email", "address", "dob", "account", "ifsc", "aadhaar", "custom",
];

// Colors reuse existing tokens; hue per type kept subtle.
export const ENTITY_COLORS: Record<PiiEntityType, string> = {
  card:    "#d93025",
  pan:     "#0a4da6",
  phone:   "#1877f2",
  email:   "#7c3aed",
  address: "#0891b2",
  dob:     "#b45309",
  account: "#2e7d32",
  ifsc:    "#65676b",
  aadhaar: "#be185d",
  custom:  "#8a8d91",
};

const AUDIO_ELIGIBLE: PiiEntityType[] = ["card", "phone", "account", "aadhaar", "dob"];

const CUSTOMERS = [
  { id: "vikram-rao",   name: "Vikram Rao",   handler: "Kaia v2.4",   channel: "voice"    as const },
  { id: "anita-desai",  name: "Anita Desai",  handler: "Aarav K.",    channel: "voice"    as const },
  { id: "priya-menon",  name: "Priya Menon",  handler: "Kaia v2.4",   channel: "whatsapp" as const },
  { id: "rahul-shetty", name: "Rahul Shetty", handler: "Priya Nair",  channel: "voice"    as const },
  { id: "kavya-iyer",   name: "Kavya Iyer",   handler: "Kaia v2.4",   channel: "voice"    as const },
  { id: "sameer-khan",  name: "Sameer Khan",  handler: "Arjun Mehta", channel: "voice"    as const },
  { id: "neha-gupta",   name: "Neha Gupta",   handler: "WebChatBot",  channel: "whatsapp" as const },
  { id: "arjun-nair",   name: "Arjun Nair",   handler: "Sara Khan",   channel: "voice"    as const },
  { id: "divya-shah",   name: "Divya Shah",   handler: "Kaia v2.4",   channel: "voice"    as const },
  { id: "rohit-verma",  name: "Rohit Verma",  handler: "Meera Joshi", channel: "voice"    as const },
  { id: "isha-kapoor",  name: "Isha Kapoor",  handler: "Kaia v2.4",   channel: "sms"      as const },
  { id: "manoj-pillai", name: "Manoj Pillai", handler: "Aarav K.",    channel: "voice"    as const },
  { id: "sneha-jain",   name: "Sneha Jain",   handler: "Kaia v2.4",   channel: "voice"    as const },
  { id: "kunal-bose",   name: "Kunal Bose",   handler: "Priya Nair",  channel: "voice"    as const },
];

// Regex-driven synthetic detector — deterministic against the seeded transcript text.
const DETECTORS: Array<{ type: PiiEntityType; re: RegExp; mask: (s: string) => string }> = [
  { type: "card",    re: /\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b/g, mask: (s) => `**** **** **** ${s.replace(/\D/g, "").slice(-4)}` },
  { type: "aadhaar", re: /\b\d{4}\s\d{4}\s\d{4}\b/g,                 mask: (s) => `•••• •••• ${s.slice(-4)}` },
  { type: "pan",     re: /\b[A-Z]{5}\d{4}[A-Z]\b/g,                  mask: () => "[REDACTED-PAN]" },
  { type: "ifsc",    re: /\bHDFC0\d{6}\b/g,                          mask: () => "[REDACTED-IFSC]" },
  { type: "phone",   re: /\+91[- ]?\d{5}[- ]?\d{5}\b/g,              mask: (s) => `+91 ••••••••${s.replace(/\D/g, "").slice(-2)}` },
  { type: "email",   re: /\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b/gi, mask: () => "[REDACTED-EMAIL]" },
  { type: "dob",     re: /\b(0?[1-9]|[12]\d|3[01])[-/](0?[1-9]|1[0-2])[-/](19|20)\d{2}\b/g, mask: () => "[REDACTED-DOB]" },
  { type: "account", re: /\bHDFC-(?:CC|PL|RL|AL)-\d{4}\b/g,           mask: (s) => `••••${s.slice(-4)}` },
  { type: "address", re: /\b\d{1,4}\s(?:MG Road|Anna Salai|Brigade Road|Nehru Nagar|Sector \d{1,2})[^,.]*/g, mask: () => "[REDACTED-ADDRESS]" },
];

export function detectPii(turns: RedactionTurn[]): PiiFinding[] {
  const out: PiiFinding[] = [];
  let n = 0;
  for (const turn of turns) {
    for (const det of DETECTORS) {
      det.re.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = det.re.exec(turn.text)) !== null) {
        out.push({
          id: `f-${turn.id}-${n++}`,
          turnId: turn.id,
          type: det.type,
          start: m.index,
          end: m.index + m[0].length,
          text: m[0],
          masked: det.mask(m[0]),
          confidence: 0.82 + ((n * 37) % 15) / 100,
          source: "auto",
          accepted: true,
        });
      }
    }
  }
  // Sort per-turn by start offset — needed for stable rendering.
  return out.sort((a, b) => (a.turnId === b.turnId ? a.start - b.start : a.turnId.localeCompare(b.turnId)));
}

// ---- seed transcripts (embed realistic PII the detectors above will pick up) ----

function makeTranscript(seed: number): RedactionTurn[] {
  // Pool of turns; each record uses a rotating subset so different customers
  // exercise different combinations of PII types.
  const pool: Array<Omit<RedactionTurn, "id" | "t">> = [
    { speaker: "agent",    text: "This call is recorded for compliance. May I confirm your card number ending 4487? Please read the full 16 digits." },
    { speaker: "customer", text: "Sure — it's 4485 1200 3390 4487, expiry March 2027." },
    { speaker: "agent",    text: "Thank you. Could you also confirm your date of birth for verification?" },
    { speaker: "customer", text: "Yes, 14/09/1988." },
    { speaker: "agent",    text: "And your PAN, please — for tax record matching." },
    { speaker: "customer", text: "BXPPK4471M. Do you also need my Aadhaar?" },
    { speaker: "agent",    text: "Aadhaar isn't required today, but I do have 4821 6640 9912 on file — please tell me if the last four match." },
    { speaker: "customer", text: "That's correct." },
    { speaker: "agent",    text: "Your account HDFC-CC-4487 currently shows ₹48,720 outstanding. Would you like the statement on email or WhatsApp?" },
    { speaker: "customer", text: "Email is fine — vikram.rao88@gmail.com. Also please update my number: +91 98221 04487." },
    { speaker: "agent",    text: "Noted. For the refund we'll credit to HDFC0043221 branch, IFSC HDFC0000123. Your registered address is 402 MG Road, Bengaluru — still correct?" },
    { speaker: "customer", text: "Yes, 402 MG Road Sector 4, Bengaluru works." },
    { speaker: "system",   text: "— Compliance disclosure: Mini-Miranda read at 00:12 —" },
    { speaker: "agent",    text: "One last thing — the callback number should be +91 87665 61102 or the primary?" },
    { speaker: "customer", text: "Primary. Thanks." },
  ];
  const startIdx = seed % pool.length;
  const length = 8 + (seed % 5); // 8..12 turns
  const out: RedactionTurn[] = [];
  let t = 0;
  for (let i = 0; i < length; i++) {
    const src = pool[(startIdx + i) % pool.length]!;
    out.push({ id: `${seed}-t${i}`, t, ...src });
    t += 6 + ((seed + i) % 5);
  }
  return out;
}

function makeRecord(i: number): RedactionRecord {
  const cust = CUSTOMERS[i % CUSTOMERS.length]!;
  const transcript = makeTranscript(i + 3);
  const findings = detectPii(transcript);
  const audioSegments: AudioSegment[] = findings
    .filter((f) => AUDIO_ELIGIBLE.includes(f.type))
    .map((f) => {
      const turn = transcript.find((t) => t.id === f.turnId)!;
      // approximate offset within turn based on char position
      const frac = turn.text.length ? f.start / turn.text.length : 0;
      return {
        atSec: turn.t + Math.floor(frac * 4) + 1,
        durSec: 1.5 + (f.text.length > 12 ? 1 : 0),
        type: f.type,
        findingId: f.id,
        muted: true,
      };
    });
  const started = new Date(Date.UTC(2026, 6, 18 - (i % 14), 10 + (i % 6), (i * 7) % 60));
  return {
    id: `RX-${(1000 + i).toString()}`,
    callId: `CL-${(100000 + i).toString()}`,
    customer: cust.name,
    customerId: cust.id,
    channel: cust.channel,
    handler: cust.handler,
    occurredAt: started.toISOString(),
    durationSec: transcript[transcript.length - 1]!.t + 8,
    transcript,
    findings,
    audioSegments,
    reviewed: false,
  };
}

export const records: RedactionRecord[] = Array.from({ length: 14 }, (_, i) => makeRecord(i));

// ---- filters ----

export interface RecordFilter {
  q: string;
  channel: "all" | "voice" | "whatsapp" | "sms";
  hasPiiOnly: boolean;
}

export const defaultFilter: RecordFilter = { q: "", channel: "all", hasPiiOnly: true };

export function filterRecords(all: RedactionRecord[], f: RecordFilter): RedactionRecord[] {
  const q = f.q.trim().toLowerCase();
  return all.filter((r) => {
    if (f.channel !== "all" && r.channel !== f.channel) return false;
    if (f.hasPiiOnly && r.findings.length === 0) return false;
    if (q) {
      const hay = `${r.id} ${r.callId} ${r.customer} ${r.handler}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

// ---- initial audit log ----

export const initialExports: ExportJob[] = [
  {
    id: "EX-2041",
    at: new Date(Date.UTC(2026, 6, 20, 11, 32)).toISOString(),
    actor: "Meera Joshi",
    actorRole: "Compliance Officer",
    recordIds: ["RX-1000", "RX-1003", "RX-1005"],
    format: "pdf",
    scope: ["transcript", "metadata"],
    watermark: "HDFC-CONFIDENTIAL · RBI Audit Q2",
    status: "ready",
    downloadCount: 2,
    entitiesRedacted: 34,
  },
  {
    id: "EX-2040",
    at: new Date(Date.UTC(2026, 6, 19, 16, 4)).toISOString(),
    actor: "Ravi Subramanian",
    actorRole: "DPO",
    recordIds: ["RX-1007"],
    format: "audio-zip",
    scope: ["audio"],
    watermark: "DSAR request — Ticket #DSAR-118",
    status: "ready",
    downloadCount: 1,
    entitiesRedacted: 8,
  },
  {
    id: "EX-2038",
    at: new Date(Date.UTC(2026, 6, 18, 9, 12)).toISOString(),
    actor: "Meera Joshi",
    actorRole: "Compliance Officer",
    recordIds: ["RX-1002", "RX-1004"],
    format: "csv",
    scope: ["metadata"],
    watermark: "Internal QA sample",
    status: "failed",
    downloadCount: 0,
    entitiesRedacted: 0,
  },
];

// ---- stat helpers ----

export function statsFor(records: RedactionRecord[], exports_: ExportJob[]) {
  const totalFindings = records.reduce((s, r) => s + r.findings.length, 0);
  const pendingReview = records.filter((r) => !r.reviewed && r.findings.length > 0).length;
  const monthlyExports = exports_.length;
  const entitiesMasked = exports_.reduce((s, e) => s + e.entitiesRedacted, 0);
  const failed = exports_.filter((e) => e.status === "failed").length;
  return { totalFindings, pendingReview, monthlyExports, entitiesMasked, failed };
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false,
  });
}

export function formatDuration(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
