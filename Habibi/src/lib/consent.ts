import type {
  AllowedWindow,
  ChannelConsent,
  ConsentChannel,
  ConsentFilterState,
  ConsentImportRow,
  ConsentRecord,
} from "@/api/types/consent";

export function allowedWindowsEqual(a: AllowedWindow, b: AllowedWindow): boolean {
  if (a.startHour !== b.startHour || a.endHour !== b.endHour) return false;
  if (a.days.length !== b.days.length) return false;
  const left = [...a.days].sort((x, y) => x - y);
  const right = [...b.days].sort((x, y) => x - y);
  return left.every((day, i) => day === right[i]);
}

// ---- domain helpers ----

export function channelStatus(
  rec: ConsentRecord,
  channel: ConsentChannel,
): ChannelConsent | undefined {
  return rec.channels.find((c) => c.channel === channel);
}

// ---- filters ----

export const defaultConsentFilters: ConsentFilterState = {
  q: "",
  channel: "all",
  status: "all",
  segment: "all",
};

export function daysUntil(iso: string): number {
  return Math.round((new Date(iso).getTime() - Date.now()) / 86400000);
}

// ---- CSV import ----

/** `POST /consent/import`'s ceiling; checked here so a big file fails before upload. */
export const MAX_CONSENT_IMPORT_ROWS = 5000;
const IMPORT_COLUMNS = ["customer_id", "channel", "status", "purpose", "dnd", "note"] as const;
const REQUIRED_COLUMNS = ["customer_id", "channel", "status"] as const;

/** RFC 4180: quoted cells, doubled quotes, commas and newlines inside quotes, CRLF. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  const src = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"' && src[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && src[i + 1] === "\n") i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else cell += ch;
  }
  if (cell !== "" || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows.filter((r) => r.some((c) => c.trim() !== ""));
}

/** A consent CSV → import rows, or the reason the file cannot be read at all. */
export function parseConsentCsv(
  text: string,
): { rows: ConsentImportRow[]; error: null } | { rows: null; error: string } {
  const [header, ...body] = parseCsv(text);
  if (!header) return { rows: null, error: "The file is empty." };
  const cols = header.map((h) => h.trim().toLowerCase());
  const missing = REQUIRED_COLUMNS.filter((c) => !cols.includes(c));
  if (missing.length) {
    return {
      rows: null,
      error: `Missing column${missing.length > 1 ? "s" : ""}: ${missing.join(", ")}`,
    };
  }
  if (!body.length) return { rows: null, error: "The file has a header but no rows." };
  if (body.length > MAX_CONSENT_IMPORT_ROWS) {
    return {
      rows: null,
      error: `${body.length} rows — the limit is ${MAX_CONSENT_IMPORT_ROWS} per import. Split the file.`,
    };
  }
  const cell = (r: string[], c: (typeof IMPORT_COLUMNS)[number]) => {
    const at = cols.indexOf(c);
    return at >= 0 ? (r[at] ?? "").trim() : "";
  };
  return {
    rows: body.map((r) => ({
      customer_id: cell(r, "customer_id"),
      channel: cell(r, "channel"),
      status: cell(r, "status"),
      purpose: cell(r, "purpose"),
      dnd: cell(r, "dnd"),
      note: cell(r, "note"),
    })),
    error: null,
  };
}

export const CHANNEL_LABEL: Record<ConsentChannel, string> = {
  call: "Call",
  whatsapp: "WhatsApp",
  sms: "SMS",
  email: "Email",
};
