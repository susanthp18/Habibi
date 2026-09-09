// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// The rehearsal inspector's tool trace.
//
// Replaces a source-grep in studio-contract.test.ts that asserted this file
// contained the word "simulated". It did — in the empty-state sentence — so the
// assertion passed regardless of what a tool call rendered, and would have kept
// passing if the per-call markup had claimed a CRM write.
//
// A deep link is the part worth pinning: it is the one thing here that can send
// an operator out of the rehearsal and into a real record.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { LiveToolCall } from "@/components/sandbox/voice/liveEvents";

import { ToolsTab } from "./ToolsTab";

function call(over: Partial<LiveToolCall> = {}): LiveToolCall {
  return {
    id: "tc-1",
    name: "get_account_position",
    status: "done",
    startedAt: 1_000,
    endedAt: 1_250,
    ...over,
  };
}

describe("rehearsal inspector · ToolsTab", () => {
  it("says a text rehearsal's tools are simulated when there are none yet", () => {
    render(<ToolsTab calls={[]} />);
    expect(screen.getByText(/Text rehearsal lists simulated tools/)).toBeInTheDocument();
  });

  it("renders each call's name and duration, newest first", () => {
    render(
      <ToolsTab
        calls={[call(), call({ id: "tc-2", name: "create_promise_to_pay", startedAt: 2_000, endedAt: 2_100 })]}
      />,
    );

    expect(screen.getByText("2 tool calls this session")).toBeInTheDocument();
    expect(screen.getByText("get_account_position")).toBeInTheDocument();
    expect(screen.getByText("250ms")).toBeInTheDocument();

    // Newest first — during a live call the interesting one is what just
    // happened, and the reversal is easy to lose in a refactor.
    const names = screen.getAllByText(/get_account_position|create_promise_to_pay/);
    expect(names[0]).toHaveTextContent("create_promise_to_pay");
  });

  it("only offers a deep link the safety check accepts", () => {
    const { unmount } = render(
      <ToolsTab
        calls={[call({ entity: "Promise", entityId: "PTP-1", deepLink: "/customers/C-1" })]}
      />,
    );
    expect(screen.getByRole("link", { name: /Open/ })).toHaveAttribute("href", "/customers/C-1");
    unmount();

    render(
      <ToolsTab
        calls={[call({ entity: "Promise", entityId: "PTP-1", deepLink: "javascript:alert(1)" })]}
      />,
    );
    // The entity still renders; the way out of the app does not.
    expect(screen.getByText("PTP-1")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open/ })).toBeNull();
  });
});
