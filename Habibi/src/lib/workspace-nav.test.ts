import { describe, expect, it } from "vitest";

import { dueLabel } from "@/api/workspace";

import { parseDeepLinkSearch, workItemDestination } from "./workspace-nav";

describe("parseDeepLinkSearch", () => {
  it("reads a new-callback deep link with the customer already chosen", () => {
    expect(parseDeepLinkSearch({ new: true, customerId: "anita-desai" })).toEqual({
      id: undefined,
      new: true,
      customerId: "anita-desai",
      plan: undefined,
    });
  });

  it("drops empty customer ids", () => {
    expect(parseDeepLinkSearch({ customerId: "" }).customerId).toBeUndefined();
  });

  it("opens a payment plan without also opening PTP", () => {
    expect(parseDeepLinkSearch({ plan: true, customerId: "anita-desai" })).toEqual({
      id: undefined,
      new: undefined,
      customerId: "anita-desai",
      plan: true,
    });
  });
});

describe("workItemDestination", () => {
  it("opens the promise a promise follow-up chases, not the generic list", () => {
    expect(workItemDestination({ id: "FU-1", entityType: "followup", relatedId: "PRM-9" })).toEqual(
      { to: "/promises", search: { id: "PRM-9" } },
    );
  });

  it("opens Customer 360 for a bounce or an unlinked follow-up", () => {
    const c360 = { to: "/customers/$customerId", params: { customerId: "C-1" } };
    expect(workItemDestination({ id: "PE-1", entityType: "bounce", customerId: "C-1" })).toEqual(
      c360,
    );
    expect(workItemDestination({ id: "FU-2", entityType: "followup", customerId: "C-1" })).toEqual(
      c360,
    );
  });
});

describe("dueLabel", () => {
  const now = Date.parse("2026-10-01T10:00:00Z");

  it("counts down and up in days, hours and minutes", () => {
    expect(dueLabel("2026-10-01T10:45:00Z", now)).toBe("In 45m");
    expect(dueLabel("2026-09-28T06:00:00Z", now)).toBe("Overdue 3d 4h");
  });
});
