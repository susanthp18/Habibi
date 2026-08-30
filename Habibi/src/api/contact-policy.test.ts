// -----------------------------------------------------------------------------
// The calling-window veto is a compliance answer, so its boundaries are pinned
// here rather than left to whatever the clock happens to say. Every case injects
// `at` — the fifth parameter mockVeto exists to accept.
//
// The UTC instants are chosen so the BORROWER's local hour lands exactly on a
// boundary: 13:29Z is 18:59 in Asia/Kolkata and 13:30Z is 19:00 sharp. Writing
// them as UTC is deliberate — a test that says "19:00" in local time cannot
// distinguish the agent's clock from the borrower's, which is the bug this
// module was written to kill.
// -----------------------------------------------------------------------------

import { describe, expect, it } from "vitest";

import type { Consent, Contact } from "@/data/customer360-seed";
import { mockVeto, type ContactChannel, type ContactPurpose } from "./contact-policy";

const OPTED_IN: Consent[] = [
  { channel: "call", optedIn: true, source: "self-serve", capturedAt: "2026-01-01T00:00:00Z" },
];
const OPTED_OUT: Consent[] = [
  { channel: "call", optedIn: false, source: "self-serve", capturedAt: "2026-01-01T00:00:00Z" },
];

/** A borrower with no stated window — the RBI default is all that bounds them. */
function borrower(overrides: Partial<Contact> = {}): Contact {
  return {
    phonePrimary: "+919000000001",
    email: "borrower@example.com",
    address: "Bengaluru",
    timezone: "Asia/Kolkata",
    language: "en",
    preferredWindow: "",
    dnd: false,
    ...overrides,
  };
}

function veto(
  contact: Contact,
  at: string,
  opts: {
    consent?: Consent[];
    channel?: ContactChannel;
    purpose?: ContactPurpose;
  } = {},
): string | null {
  return mockVeto(
    contact,
    opts.consent ?? OPTED_IN,
    opts.channel ?? "voice",
    opts.purpose ?? "outreach",
    new Date(at),
  );
}

describe("calling window", () => {
  it("treats the window end hour as exclusive", () => {
    const contact = borrower({ preferredWindow: "08:00–19:00 IST" });
    // 18:59 in Asia/Kolkata.
    expect(veto(contact, "2026-03-10T13:29:00Z")).toBeNull();
    // 19:00 sharp. Inclusive-end arithmetic showed this green against a
    // dialler that was already refusing the call.
    expect(veto(contact, "2026-03-10T13:30:00Z")).toBe("outside_calling_hours");
  });

  it("treats the window start hour as inclusive", () => {
    const contact = borrower({ preferredWindow: "08:00–19:00 IST" });
    expect(veto(contact, "2026-03-10T02:29:00Z")).toBe("outside_calling_hours"); // 07:59 IST
    expect(veto(contact, "2026-03-10T02:30:00Z")).toBeNull(); // 08:00 IST
  });

  it("applies the RBI default bounds when no window is stated", () => {
    const contact = borrower({ preferredWindow: "" });
    expect(veto(contact, "2026-03-10T02:29:00Z")).toBe("outside_calling_hours"); // 07:59 IST
    expect(veto(contact, "2026-03-10T02:30:00Z")).toBeNull(); // 08:00 IST
    expect(veto(contact, "2026-03-10T13:30:00Z")).toBe("outside_calling_hours"); // 19:00 IST
  });

  it("evaluates the window in the borrower's timezone, not the agent's", () => {
    // One instant, two borrowers. 14:00Z is 19:30 in Kolkata and 14:00 in London.
    const at = "2026-03-10T14:00:00Z";
    expect(veto(borrower({ timezone: "Asia/Kolkata" }), at)).toBe("outside_calling_hours");
    expect(veto(borrower({ timezone: "Europe/London" }), at)).toBeNull();
  });

  it("falls back to Asia/Kolkata for an unparseable zone, and tolerates a label", () => {
    const at = "2026-03-10T14:00:00Z"; // 19:30 IST
    expect(veto(borrower({ timezone: "Asia/Kolkata (IST)" }), at)).toBe("outside_calling_hours");
    expect(veto(borrower({ timezone: "Middle/Earth" }), at)).toBe("outside_calling_hours");
  });

  it("discards the minutes of a stated window, matching _parse_hours", () => {
    const contact = borrower({ preferredWindow: "10:30–19:00 IST" });
    // 10:00 IST. The stated window starts at 10:30, but the veto compares whole
    // hours only, so this is allowed — and the mock has to agree with the veto.
    expect(veto(contact, "2026-03-10T04:30:00Z")).toBeNull();
    // 09:00 IST is inside the RBI bound but outside the narrower stated one.
    expect(veto(contact, "2026-03-10T03:30:00Z")).toBe("outside_allowed_window");
  });

  it("does not bound non-voice channels by the statutory window", () => {
    const contact = borrower();
    expect(veto(contact, "2026-03-10T13:30:00Z", { channel: "whatsapp", consent: [] })).toBeNull();
  });
});

describe("allowed days", () => {
  const sunday = "2026-03-08T06:00:00Z"; // Sun 11:00 IST
  const wednesday = "2026-03-11T06:00:00Z"; // Wed 11:00 IST
  const friday = "2026-03-13T06:00:00Z"; // Fri 11:00 IST

  it("honours a dashed range", () => {
    const contact = borrower({ allowedDays: "Mon–Sat" });
    expect(veto(contact, wednesday)).toBeNull();
    expect(veto(contact, sunday)).toBe("outside_allowed_window");
  });

  it("honours a range that wraps the week", () => {
    const contact = borrower({ allowedDays: "Fri–Mon" });
    expect(veto(contact, friday)).toBeNull();
    expect(veto(contact, sunday)).toBeNull();
    expect(veto(contact, wednesday)).toBe("outside_allowed_window");
  });

  it("honours a comma list", () => {
    const contact = borrower({ allowedDays: "mon,wed,fri" });
    expect(veto(contact, wednesday)).toBeNull();
    expect(veto(contact, sunday)).toBe("outside_allowed_window");
  });

  it("ignores an empty allowedDays rather than blocking every day", () => {
    expect(veto(borrower({ allowedDays: "" }), sunday)).toBeNull();
  });
});

describe("veto ladder order", () => {
  const insideWindow = "2026-03-10T06:00:00Z"; // 11:30 IST, a Tuesday

  it("blocks an opted-out channel even inside the window", () => {
    expect(veto(borrower(), insideWindow, { consent: OPTED_OUT })).toBe("channel_opted_out");
  });

  it("maps the voice channel onto the seed's 'call' consent record", () => {
    const whatsappOptOut: Consent[] = [
      { channel: "whatsapp", optedIn: false, source: "self-serve", capturedAt: "2026-01-01" },
    ];
    // A WhatsApp opt-out must not veto a voice call.
    expect(veto(borrower(), insideWindow, { consent: whatsappOptOut })).toBeNull();
  });

  it("blocks a DND borrower before the hours are consulted", () => {
    expect(veto(borrower({ dnd: true }), insideWindow)).toBe("customer_dnd");
  });

  it("lets statutory contact through the hours check", () => {
    const at = "2026-03-10T13:30:00Z"; // 19:00 IST — outside the window
    expect(veto(borrower(), at)).toBe("outside_calling_hours");
    expect(veto(borrower(), at, { purpose: "statutory" })).toBeNull();
  });

  it("still applies the channel opt-out to statutory contact", () => {
    expect(veto(borrower(), insideWindow, { consent: OPTED_OUT, purpose: "statutory" })).toBe(
      "channel_opted_out",
    );
  });
});
