// -----------------------------------------------------------------------------
// Contact policy — the authoritative "may we contact this borrower right now?"
// verdict.  GET /customers/:id/contact-policy  (backend/main.py).
//
// The answer is the backend's, never the browser's. It is computed in the
// BORROWER's timezone against the statutory calling window, their consent
// record, allowed days, cooling-off and the daily/weekly caps — none of which
// the client can see. Recomputing any part of it here produces a second opinion
// that disagrees with the veto the dialler will actually apply, which on this
// screen means telling an agent it is fine to ring someone at 03:00.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";

import { getCustomer, type Consent, type Contact } from "@/data/customer360-seed";
import { apiGet, mockDelay, USE_MOCK } from "./config";

/** Mirrors backend/schemas.py :: ContactPolicyResponse. */
export interface ContactPolicy {
  allowed: boolean;
  /** Veto code from contact_policy.py, or null when allowed. */
  reason: string | null;
  touchCounted: boolean;
  outreachToday: number;
  dailyCap: number;
  coalesced: boolean;
  channel: string;
  purpose: string;
}

export type ContactChannel = "voice" | "whatsapp" | "sms" | "email" | "chat" | "field";
export type ContactPurpose = "outreach" | "statutory" | "in_session";

export async function fetchContactPolicy(
  customerId: string,
  opts: { channel?: ContactChannel; purpose?: ContactPurpose; signal?: AbortSignal } = {},
): Promise<ContactPolicy> {
  const channel = opts.channel ?? "voice";
  const purpose = opts.purpose ?? "outreach";
  if (USE_MOCK) {
    return mockDelay(mockEvaluateContactPolicy(customerId, { channel, purpose }));
  }
  // The backend defaults this endpoint to channel=whatsapp, so both params are
  // always sent explicitly — the pill asks about voice.
  return apiGet<ContactPolicy>(
    `/customers/${encodeURIComponent(customerId)}/contact-policy?channel=${channel}&purpose=${purpose}`,
    { signal: opts.signal },
  );
}

/**
 * The verdict is a function of the clock, so it goes stale on its own: a pill
 * fetched at 18:58 is wrong at 19:01. Refetch on an interval and on focus so it
 * cannot sit green past the end of the calling window.
 */
export function useContactPolicy(
  customerId: string | undefined,
  opts: { channel?: ContactChannel; purpose?: ContactPurpose } = {},
) {
  const channel = opts.channel ?? "voice";
  const purpose = opts.purpose ?? "outreach";
  return useQuery({
    queryKey: ["contact-policy", customerId, channel, purpose],
    queryFn: ({ signal }) => fetchContactPolicy(customerId!, { channel, purpose, signal }),
    enabled: Boolean(customerId),
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });
}

// -----------------------------------------------------------------------------
// Mock emulation of backend/contact_policy.py :: _veto (outreach path).
//
// This is deliberately a port, not an approximation: dev and demo builds must
// show the same answer the veto would give, or the mock teaches everyone the
// wrong behaviour. Kept faithful to the original on the four points the old
// client-side check got wrong —
//   1. evaluated in the BORROWER's timezone (contact.timezone), not the agent's;
//   2. the RBI 08:00–19:00 voice window applies even with no stated preference;
//   3. allowed days are honoured;
//   4. the end hour is EXCLUSIVE (hour >= end blocks), and comparison is on the
//      hour alone — _parse_hours discards the minutes, so "10:30" starts at 10.
//
// Not emulated: cooling-off and the daily/weekly caps. Those are counted from
// contact_events, which the seed has no equivalent of; the mock reports
// outreachToday 0 against the default cap rather than inventing a count.
// -----------------------------------------------------------------------------

const RBI_VOICE_START = 8;
const RBI_VOICE_END = 19;
const DEFAULT_TZ = "Asia/Kolkata";
const DEFAULT_DAILY_CAP = 3;

/** contact_policy._DAY_NAME_TO_NUM — 0=Sun … 6=Sat. */
const DAY_NAME_TO_NUM: Record<string, number> = {
  sun: 0,
  mon: 1,
  tue: 2,
  wed: 3,
  thu: 4,
  fri: 5,
  sat: 6,
};

/** contact_policy._zone — tolerate the seed's "Asia/Kolkata (IST)" label. */
function zoneOf(raw: string | null | undefined): string {
  const label = (raw ?? "").replace(/\(.*\)/, "").trim() || DEFAULT_TZ;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: label });
    return label;
  } catch {
    return DEFAULT_TZ;
  }
}

/** contact_policy._parse_hours — start/end HOURS only, minutes discarded. */
function parseAllowedHours(raw: string | null | undefined): [number, number] | null {
  if (!raw?.trim()) return null;
  const m = /(\d{1,2}):(\d{2}).*?(\d{1,2}):(\d{2})/.exec(raw);
  return m ? [Number(m[1]), Number(m[3])] : null;
}

/** contact_policy._parse_days — "Mon–Sat", "mon,wed,fri", en/em dashes alike. */
function parseAllowedDays(raw: string | null | undefined): number[] | null {
  if (!raw?.trim()) return null;
  const text = raw.trim().toLowerCase().replace(/[–—]/g, "-");
  if (text.includes("-") && !text.includes(",")) {
    const parts = text.split("-", 2).map((p) => p.trim().slice(0, 3));
    const start = DAY_NAME_TO_NUM[parts[0]];
    const end = DAY_NAME_TO_NUM[parts[1]];
    if (start !== undefined && end !== undefined) {
      if (start <= end) {
        return Array.from({ length: end - start + 1 }, (_, i) => start + i);
      }
      // Wraps the week, e.g. "Fri–Mon".
      return [
        ...Array.from({ length: 7 - start }, (_, i) => start + i),
        ...Array.from({ length: end + 1 }, (_, i) => i),
      ];
    }
  }
  const days = text
    .split(/[,\s]+/)
    .map((token) => DAY_NAME_TO_NUM[token.slice(0, 3)])
    .filter((d): d is number => d !== undefined);
  return days.length ? days : null;
}

/** The borrower's local hour and weekday — the whole point of this module. */
function borrowerLocal(at: Date, timeZone: string): { hour: number; dayOfWeek: number } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour: "2-digit",
    hour12: false,
    weekday: "short",
  }).formatToParts(at);
  // hour12:false renders midnight as "24" in some ICU versions; normalise it.
  const hour = Number(parts.find((p) => p.type === "hour")?.value ?? "0") % 24;
  const weekday = (parts.find((p) => p.type === "weekday")?.value ?? "").toLowerCase().slice(0, 3);
  return { hour, dayOfWeek: DAY_NAME_TO_NUM[weekday] ?? 0 };
}

/** Seed consent → the blocking status contact_policy._channel_status would return. */
function channelStatus(consent: Consent[], channel: ContactChannel): string | null {
  const seedChannel = channel === "voice" ? "call" : channel;
  const record = consent.find((c) => c.channel === seedChannel);
  if (!record) return null;
  return record.optedIn ? "opted_in" : "opted_out";
}

/**
 * The veto ladder, in contact_policy._veto's order. Exported and time-injectable
 * so the boundary hours can be exercised without waiting for the clock.
 */
export function mockVeto(
  contact: Contact,
  consent: Consent[],
  channel: ContactChannel,
  purpose: ContactPurpose,
  at: Date,
): string | null {
  const status = channelStatus(consent, channel);
  if (status === "opted_out") return "channel_opted_out";
  if (status === "dnd") return "channel_dnd";
  if (status === "expired") return "channel_expired";

  if (purpose === "in_session") return null;
  if (purpose !== "outreach") return null; // statutory: hours and DND do not block

  if (contact.dnd) return "customer_dnd";

  const { hour, dayOfWeek } = borrowerLocal(at, zoneOf(contact.timezone));

  // Absent a published rule set, only voice is bounded by the statutory window.
  if (channel === "voice" && (hour < RBI_VOICE_START || hour >= RBI_VOICE_END)) {
    return "outside_calling_hours";
  }

  const hours = parseAllowedHours(contact.preferredWindow);
  if (hours && (hour < hours[0] || hour >= hours[1])) return "outside_allowed_window";

  const days = parseAllowedDays(contact.allowedDays);
  if (days && !days.includes(dayOfWeek)) return "outside_allowed_window";

  return null;
}

function mockEvaluateContactPolicy(
  customerId: string,
  opts: { channel: ContactChannel; purpose: ContactPurpose; at?: Date },
): ContactPolicy {
  const { channel, purpose } = opts;
  const base = {
    touchCounted: false,
    outreachToday: 0,
    dailyCap: DEFAULT_DAILY_CAP,
    coalesced: false,
    channel,
    purpose,
  };
  const customer = getCustomer(customerId);
  if (!customer) {
    // contact_policy fails closed on a customer it cannot read.
    return { ...base, allowed: false, reason: "no_customer" };
  }
  const reason = mockVeto(
    customer.contact,
    customer.consent,
    channel,
    purpose,
    opts.at ?? new Date(),
  );
  return { ...base, allowed: reason === null, reason };
}
