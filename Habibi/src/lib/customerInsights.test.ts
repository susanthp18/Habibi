// -----------------------------------------------------------------------------
// WP-048 (second half): InteractionResponse.summary is str | None. The type
// used to say string, so tsc certified `.slice` on a value that is null on
// the wire (TS-03). deriveCustomerInsights already wraps with str(); this
// pins that a payload the server actually sends does not throw.
// -----------------------------------------------------------------------------

import { describe, expect, it } from "vitest";

import type { Customer } from "@/api/types/customer360";
import { deriveCustomerInsights } from "./customerInsights";

function wireNullCustomer(): Customer {
  return {
    id: "cust-null",
    name: "Null Wire",
    accountId: "ACC-1",
    risk: "low",
    outstanding: 1200,
    minimumDue: null,
    lastContact: null,
    assignedTo: "Unassigned",
    contact: {
      phonePrimary: "+919000000001",
      email: "",
      address: "",
      timezone: "Asia/Kolkata",
      language: "English",
      preferredWindow: "10:00-19:00 IST",
      dnd: false,
    },
    account: {
      product: "Credit Card",
      openedOn: null,
      apr: null,
      sanctionedAmount: null,
      bucket: null,
      dpd: 14,
      riskScore: null,
    },
    consent: [{ channel: "call", optedIn: true, source: "self-serve", capturedAt: null }],
    ledger: [
      {
        id: "l1",
        date: "2026-01-01",
        description: "",
        type: "charge",
        amount: 100,
      },
    ],
    emi: [
      {
        id: "e1",
        index: 1,
        dueDate: "2026-01-01",
        amount: 100,
        status: "upcoming",
        balanceCarried: null,
      },
    ],
    interactions: [
      {
        id: "i1",
        channel: "voice",
        handler: { kind: "bot", name: "Kaia" },
        startedAt: null,
        duration: "",
        disposition: null,
        sentiment: "neutral",
        sentimentDelta: "flat",
        summary: null,
        intents: {},
      },
    ],
    promises: [],
    disputes: [
      {
        id: "D-1",
        type: "fee_waiver",
        amount: null,
        transcriptSnippet: "",
        status: "new",
        sla: "ok",
        slaLabel: "Open",
        slaMinutes: 0,
        filedAt: "2026-01-01T00:00:00Z",
      },
    ],
    documents: [],
    notes: [],
  };
}

describe("deriveCustomerInsights against a null wire payload", () => {
  it("does not throw when summary, disposition, startedAt, and money fields are null", () => {
    const insights = deriveCustomerInsights(wireNullCustomer());
    expect(insights.customerId).toBe("cust-null");
    expect(insights.summary.length).toBeGreaterThan(0);
    expect(insights.summary[0]?.text).toContain("unknown");
    expect(insights.summary[0]?.text).toContain("min due ₹0");
    const lastTouch = insights.summary.find((b) => b.id === "ins-last-ix");
    expect(lastTouch?.text).toContain("Last voice touch");
    expect(insights.metrics.daysSinceContact).toBeNull();
    expect(insights.metrics.openDisputeAmount).toBe(0);
  });
});
