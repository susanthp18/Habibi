import type {
  ExportJob,
  PiiEntityType,
  RecordFilter,
  RedactionRecord,
} from "@/api/types/redaction";

export const ENTITY_TYPES: PiiEntityType[] = [
  "card",
  "pan",
  "phone",
  "email",
  "address",
  "dob",
  "account",
  "ifsc",
  "aadhaar",
  "custom",
];

// Design.md accent ramp, "-bolder" tier — one distinct hue per PII type.
export const ENTITY_COLORS: Record<PiiEntityType, string> = {
  card: "#C9372C", // accent-red-bolder
  pan: "#1868DB", // accent-blue-bolder
  phone: "#227D9B", // accent-teal-bolder
  email: "#964AC0", // accent-purple-bolder
  address: "#BD5B00", // accent-orange-bolder
  dob: "#946F00", // accent-yellow-bolder
  account: "#1F845A", // accent-green-bolder
  ifsc: "#6B6E76", // accent-gray-bolder
  aadhaar: "#AE4787", // accent-magenta-bolder
  custom: "#5B7F24", // accent-lime-bolder
};

// ---- filters ----

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

// ---- stat helpers ----

export function statsFor(records: RedactionRecord[], exports_: ExportJob[]) {
  const totalFindings = records.reduce((s, r) => s + r.findings.length, 0);
  const pendingReview = records.filter((r) => !r.reviewed && r.findings.length > 0).length;
  const monthlyExports = exports_.length;
  const entitiesMasked = exports_.reduce((s, e) => s + e.entitiesRedacted, 0);
  const failed = exports_.filter((e) => e.status === "failed").length;
  return { totalFindings, pendingReview, monthlyExports, entitiesMasked, failed };
}
