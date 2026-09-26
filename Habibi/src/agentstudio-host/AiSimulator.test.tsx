// @vitest-environment jsdom
// The AI customer tab: starts a graded rehearsal and shows that run's conversation.
import "@/test/jsdom";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CheckRun } from "@/api/voice-studio";

const state: { runs: CheckRun[]; permissions: string[] } = {
  runs: [],
  permissions: ["perm-eval-run"],
};
const mutate = vi.fn();

vi.mock("@/api/voice-studio", () => ({
  useSimulateCustomer: () => ({ mutate, isPending: false }),
  useCheckRuns: () => ({ data: state.runs }),
}));
vi.mock("@/api/me", () => ({
  useMe: () => ({ data: { permissions: state.permissions } }),
  can: (me: { permissions: string[] }, p: string) => me.permissions.includes(p),
}));

const { default: AiSimulator } = await import("./AiSimulator");

const simRun: CheckRun = {
  id: "VSC-1",
  workflowId: 7,
  createdAt: "2026-09-26T09:00:00Z",
  createdBy: null,
  status: "done",
  passed: 0,
  failed: 1,
  results: [
    {
      scenarioId: "ai-customer",
      scenarioName: "AI customer: lost their job",
      workflowRunId: 55,
      flags: ["prohibited-phrase"],
      passed: false,
      turns: [
        {
          customer: "I lost my job.",
          agent: "We will take legal action.",
          flags: ["prohibited-phrase"],
        },
      ],
    },
  ],
};

describe("AI customer tab", () => {
  it("starts a run with the described customer", () => {
    state.runs = [];
    render(<AiSimulator workflowId={7} disabledReason={null} />);
    fireEvent.change(screen.getByLabelText("Who is the customer?"), {
      target: { value: "  A polite customer who wants to settle today.  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run AI customer" }));
    expect(mutate).toHaveBeenCalledWith(
      "A polite customer who wants to settle today.",
      expect.anything(),
    );
  });

  it("shows the last AI-customer conversation with its flags", () => {
    state.runs = [simRun];
    render(<AiSimulator workflowId={7} disabledReason={null} />);
    expect(screen.getByText(/Fail · AI customer: lost their job/)).toBeInTheDocument();
    expect(screen.getByText(/We will take legal action/)).toBeInTheDocument();
  });

  it("cannot be started without the eval permission", () => {
    state.permissions = [];
    state.runs = [];
    render(<AiSimulator workflowId={7} disabledReason={null} />);
    expect(screen.getByRole("button", { name: "Run AI customer" })).toBeDisabled();
  });
});
