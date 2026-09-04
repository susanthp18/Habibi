import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { consentPatchBody } from "./consent";
import type { AllowedWindow, ConsentRecord } from "@/api/types/consent";
import { allowedWindowsEqual } from "@/data/consent-seed";

const here = dirname(fileURLToPath(import.meta.url));

const WEEKDAYS: AllowedWindow = { days: [1, 2, 3, 4, 5], startHour: 10, endHour: 19 };

function rec(window: AllowedWindow): ConsentRecord {
  return {
    id: "CR-1",
    customerId: "C-1",
    customerName: "A",
    accountId: "A-1",
    phone: "+919000000001",
    email: "a@example.test",
    timezone: "Asia/Kolkata",
    segment: "Retail",
    channels: [],
    allowedWindow: window,
    consentExpiresAt: "2027-01-01T00:00:00Z",
    onDndRegistry: false,
    optOutLog: [],
    audit: [],
  };
}

describe("consentPatchBody", () => {
  const channels = [
    {
      channel: "sms" as const,
      status: "opted_out" as const,
      capturedAt: "2026-01-01T00:00:00Z",
      source: "Agent" as const,
      frequencyCapPerWeek: 3,
      usedThisWeek: 0,
    },
  ];

  it("omits allowedWindow when the operator only toggled a channel", () => {
    const body = consentPatchBody(rec(WEEKDAYS), { channels, allowedWindow: WEEKDAYS }, "");
    expect(body).not.toHaveProperty("allowedWindow");
    expect(body.channels).toEqual(channels);
  });

  it("omits allowedWindow when the drawer already left it off", () => {
    const body = consentPatchBody(rec(WEEKDAYS), { channels }, "note");
    expect(body).not.toHaveProperty("allowedWindow");
  });

  it("includes allowedWindow when the operator changed the hours", () => {
    const next = { ...WEEKDAYS, startHour: 9, endHour: 18 };
    const body = consentPatchBody(rec(WEEKDAYS), { channels, allowedWindow: next }, "");
    expect(body.allowedWindow).toEqual(next);
  });
});

describe("allowedWindowsEqual", () => {
  it("treats day-order as irrelevant", () => {
    expect(
      allowedWindowsEqual({ days: [5, 1, 2, 3, 4], startHour: 10, endHour: 19 }, WEEKDAYS),
    ).toBe(true);
  });
});

describe("ConsentDrawer save", () => {
  it("only attaches allowedWindow when the operator changed it", () => {
    const src = readFileSync(
      join(here, "..", "components", "consent", "ConsentDrawer.tsx"),
      "utf8",
    );
    expect(src).toContain("allowedWindowsEqual");
    expect(src).not.toMatch(/allowedWindow:\s*window/);
  });
});
