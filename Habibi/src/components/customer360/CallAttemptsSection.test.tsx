// @vitest-environment jsdom
import "@/test/jsdom";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Customer } from "@/api/types/customer360";

const q = vi.hoisted(() => ({
  attempts: { data: undefined, isPending: false, isError: false } as Record<string, unknown>,
}));

vi.mock("@/api/outbound", () => ({
  useOutboundAttempts: () => q.attempts,
  ATTEMPT_STATE_LABEL: { suppressed: "blocked by policy", no_answer: "no answer" },
}));

const { CallAttemptsSection } = await import("./CallAttemptsSection");

const CUSTOMER = { id: "CUST-1" } as Customer;

const attempt = (over: Record<string, unknown>) => ({
  id: "CA-1",
  objective: "dpd_reminder",
  state: "no_answer",
  suppressed_reason: null,
  business: null,
  ring_sec: null,
  talk_sec: null,
  provider_error: null,
  reserved_at: "2026-09-17T06:00:00Z",
  ...over,
});

describe("CallAttemptsSection", () => {
  it("shows why a dial that never rang was refused", () => {
    // An interaction only exists once media connects, so this was the one
    // place a refused dial could have been seen, and nothing rendered it.
    q.attempts = {
      data: [attempt({ state: "suppressed", suppressed_reason: "outside_calling_hours" })],
      isPending: false,
      isError: false,
    };
    render(<CallAttemptsSection customer={CUSTOMER} />);

    expect(screen.getByText("blocked by policy")).toBeInTheDocument();
    expect(screen.getByText(/blocked: outside calling hours/)).toBeInTheDocument();
  });

  it("does not present an unreadable log as an empty one", () => {
    q.attempts = { data: undefined, isPending: false, isError: true, error: new Error("502") };
    render(<CallAttemptsSection customer={CUSTOMER} />);

    expect(screen.getByText(/could not load call attempts/i)).toBeInTheDocument();
    expect(screen.queryByText(/no call attempts/i)).toBeNull();
  });
});
