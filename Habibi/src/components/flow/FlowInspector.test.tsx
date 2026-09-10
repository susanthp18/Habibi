// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// A failed vocabulary read is not a card with no missions.
//
// Replaces a source-grep in studio-trust.test.ts that checked FlowInspector
// contained the string "vocab.isError". The file contains it either way; what
// the grep could not see is which of the three sentences a reader is shown, and
// the dangerous one reads as a fact about the card: "No outbound missions
// available" tells an author their card declares none, when the truth is that
// the request failed and nobody knows.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FlowNode } from "@/api/flow";

const vocab = vi.hoisted(() => ({
  state: { data: undefined, isPending: false, isError: false } as Record<string, unknown>,
}));

vi.mock("@/api/outbound", () => ({
  useOutboundVocabulary: () => vocab.state,
}));

const { NodeInspector } = await import("./FlowInspector");

const NODE = {
  id: "n-1",
  type: "step",
  position: { x: 0, y: 0 },
  data: {
    key: "greet_disclose",
    label: "Greet",
    tools: [],
    entryFor: [],
    extractVariables: [],
    transitions: [],
  },
} as unknown as FlowNode;

function show(state: Record<string, unknown>) {
  vocab.state = { data: undefined, isPending: false, isError: false, ...state };
  return render(
    <NodeInspector
      node={NODE}
      tools={[]}
      reservedKeys={{}}
      issues={[]}
      readOnly={false}
      onChange={() => {}}
      onDelete={() => {}}
    />,
  );
}

describe("NodeInspector · outbound mission entries", () => {
  it("says the read failed rather than claiming the card has no missions", () => {
    show({ isError: true });

    expect(screen.getByText(/this is not a card with none/i)).toBeInTheDocument();
    expect(screen.queryByText(/No outbound missions available/)).toBeNull();
  });

  it("distinguishes loading from genuinely none", () => {
    const loading = show({ isPending: true });
    expect(screen.getByText(/Loading missions/)).toBeInTheDocument();
    expect(screen.queryByText(/No outbound missions available/)).toBeNull();
    loading.unmount();

    show({ data: { objectives: [] } });
    expect(screen.getByText(/No outbound missions available/)).toBeInTheDocument();
  });

  it("does not offer inbound as an outbound mission", () => {
    show({ data: { objectives: ["inbound", "ptp_followup"] } });

    // `isStart` owns the inbound door; offering it twice is two ways to
    // disagree about which step answers a call.
    expect(screen.getByText(/ptp_followup/)).toBeInTheDocument();
    expect(screen.queryByText(/^inbound$/)).toBeNull();
  });
});
