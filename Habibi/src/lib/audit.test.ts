import { describe, expect, it } from "vitest";
import { DISPOSITIONS, filterCalls } from "./audit";
import type { CallRecord } from "@/api/types/audit";

function call(disposition: CallRecord["disposition"]): CallRecord {
  return {
    id: "CL-1",
    startedAt: new Date().toISOString(),
    duration: 10,
    channel: "voice",
    direction: "inbound",
    handledBy: { kind: "bot", bot: "collections" },
    customerId: "CU-1",
    customerName: "Test",
    phoneMasked: "+91 ••••••••00",
    accountId: null,
    disposition,
    summary: null,
    tags: [],
    flags: [],
    avgSentiment: 0,
    sentimentSeries: [],
    disclosures: [],
    transcript: [],
    redactionApplied: false,
    hash: null,
    ragHits: 0,
    latencyMs: null,
    routing: [],
  };
}

describe("audit disposition filter", () => {
  it("includes the runtime vocab the closer writes", () => {
    expect(DISPOSITIONS).toContain("ptp_captured");
    expect(DISPOSITIONS).toContain("escalated");
    expect(DISPOSITIONS).not.toContain("PTP Captured");
  });

  it("selects a call by the stored disposition, not a display label", () => {
    const rows = filterCalls([call("ptp_captured")], {
      q: "",
      dateRange: "all",
      channel: "all",
      handler: "all",
      agent: "all",
      disposition: "ptp_captured",
      sentiment: "all",
      flaggedOnly: false,
    });
    expect(rows).toHaveLength(1);
  });
});
