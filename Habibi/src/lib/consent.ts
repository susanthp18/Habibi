import type {
  AllowedWindow,
  ChannelConsent,
  ConsentChannel,
  ConsentFilterState,
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
    if (f.status === "dnd" && !r.onDndRegistry && !r.channels.some((c) => c.status === "dnd"))
      return false;
    if (f.status === "opted_out" && !r.channels.some((c) => c.status === "opted_out")) return false;
    if (f.status === "expiring") {
      const days = (new Date(r.consentExpiresAt).getTime() - Date.now()) / 86400000;
      if (days > 30) return false;
    }
    if (f.status === "contactable" && r.contactable.status === "red") return false;
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
