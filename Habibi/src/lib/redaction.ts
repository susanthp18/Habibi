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
  "pincode",
  "name",
  "upi",
  "passport",
  "voter_id",
  "driving_licence",
  "secret",
  "custom",
];

// Design spec (styles.css) accent ramp, "-bolder" tier — one distinct hue per PII type.
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
  pincode: "#A54800", // accent-orange-boldest
  name: "#0055CC", // accent-blue-boldest
  upi: "#4C6B1F", // accent-lime-boldest
  passport: "#5E4DB2", // accent-purple-boldest
  voter_id: "#206A83", // accent-teal-boldest
  driving_licence: "#7F5F01", // accent-yellow-boldest
  secret: "#AE2E24", // accent-red-boldest
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

const DAY_MS = 86_400_000;

export function statsFor(records: RedactionRecord[], exports_: ExportJob[], now = Date.now()) {
  const totalFindings = records.reduce((s, r) => s + r.findings.length, 0);
  // Waiting on a person: a low-confidence mask nobody has confirmed yet.
  const pendingReview = records.filter(
    (r) => !r.reviewed && r.findings.some((f) => f.needsReview),
  ).length;
  const recent = exports_.filter((e) => now - new Date(e.at).getTime() <= 30 * DAY_MS);
  const monthlyExports = recent.length;
  const entitiesMasked = recent.reduce((s, e) => s + e.entitiesRedacted, 0);
  const failed = recent.filter((e) => e.status === "failed").length;
  return { totalFindings, pendingReview, monthlyExports, entitiesMasked, failed };
}
