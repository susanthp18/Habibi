import { describe, expect, it } from "vitest";

import { dueLabel, liveSla, movesWorkspace } from "@/api/workspace";

import { loanFor, parseDeepLinkSearch, workItemDestination } from "./workspace-nav";

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

  it("carries the loan a record is for, only with its customer", () => {
    expect(
      parseDeepLinkSearch({ new: true, customerId: "c-1", accountId: "acc-2" }).accountId,
    ).toBe("acc-2");
    expect(parseDeepLinkSearch({ new: true, accountId: "acc-2" }).accountId).toBeUndefined();
  });

  it("files against the linked loan, not the customer's first, and only for that customer", () => {
    const linked = { id: "c-1", accountId: "acc-1" };
    expect(loanFor(linked, "c-1", "acc-2")).toBe("acc-2");
    expect(loanFor({ id: "c-9", accountId: "acc-9" }, "c-1", "acc-2")).toBe("acc-9");
    expect(loanFor(linked, "c-1", undefined)).toBe("acc-1");
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

describe("liveSla", () => {
  const now = Date.parse("2026-10-01T10:00:00Z");
  const row = (dueAt: string | null, sla: "ok" | "warn" | "breach" = "ok", slaLabel = "Open") => ({
    dueAt,
    sla,
    slaLabel,
  });

  it("raises the colour as the clock crosses the server's thresholds", () => {
    expect(liveSla(row("2026-10-01T13:00:00Z"), now)).toEqual({ level: "ok", label: "In 3h" });
    expect(liveSla(row("2026-10-01T11:30:00Z"), now).level).toBe("warn");
    expect(liveSla(row("2026-10-01T09:59:00Z", "warn"), now)).toEqual({
      level: "breach",
      label: "Overdue 1m",
    });
  });

  it("never lowers a status-driven level, and keeps the server's words for undated work", () => {
    expect(liveSla(row("2026-10-03T10:00:00Z", "breach"), now).level).toBe("breach");
    // A bounce awaiting payment has no deadline: green "Awaiting pay", never "Overdue".
    expect(liveSla(row(null, "ok", "Awaiting pay"), now)).toEqual({
      level: "ok",
      label: "Awaiting pay",
    });
  });
});

describe("movesWorkspace", () => {
  it("refreshes the workspace after any write that is not a pure computation", () => {
    expect(movesWorkspace("/callbacks/CB-1")).toBe(true);
    expect(movesWorkspace("/document-requests/D-1/delivery-attempts")).toBe(true);
    // The executor can file a follow-up: a path the old allowlist missed.
    expect(movesWorkspace("/treatment/decisions/TD-1/enact")).toBe(true);
    expect(movesWorkspace("/conversations/C-1/assign")).toBe(true);
    expect(movesWorkspace("/voice-studio/prompt/lint")).toBe(false);
    expect(movesWorkspace("/voice-studio/routing/check")).toBe(false);
    expect(movesWorkspace("/studio-api/_ws-ticket")).toBe(false);
    expect(movesWorkspace("/treatment/decide")).toBe(false);
  });
});
