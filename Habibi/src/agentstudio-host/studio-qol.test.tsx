// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// Voice Studio quality-of-life: call latency summary and transcript export,
// Checks pass-rate trend, and prompt lint under the node editor.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  latencySummary,
  transcriptOf,
} from "@/agentstudio/components/workflow/conversation/ConversationSummary";
import type { CheckRun } from "@/api/voice-studio";

const lint = vi.hoisted(() => ({ data: undefined as unknown, isError: false }));

vi.mock("@/api/voice-studio", async (orig) => ({
  ...(await orig<typeof import("@/api/voice-studio")>()),
  usePromptLint: () => lint,
}));
vi.mock("@tanstack/react-router", () => ({ useParams: () => ({ workflowId: "7" }) }));

const { passRates } = await import("@/components/voice-studio/check-trend");
const { default: PromptLint } = await import("./PromptLint");

describe("conversation summary", () => {
  it("averages recorded response times and finds the slowest", () => {
    expect(
      latencySummary([
        { id: "1", kind: "message", role: "assistant", text: "hi", reasoningDurationMs: 600 },
        { id: "2", kind: "message", role: "user", text: "hello" },
        { id: "3", kind: "message", role: "assistant", text: "ok", reasoningDurationMs: 1000.4 },
      ]),
    ).toEqual({ count: 2, averageMs: 800, slowestMs: 1000 });
    expect(latencySummary([{ id: "1", kind: "message", role: "user", text: "x" }])).toBeNull();
  });

  it("exports who said what, tool calls and flow steps", () => {
    expect(
      transcriptOf([
        { id: "1", kind: "message", role: "user", text: "balance?" },
        { id: "2", kind: "tool-call", functionName: "account_position", status: "completed" },
        { id: "3", kind: "node-transition", nodeName: "Resolve" },
      ]).map((e) => e.speaker),
    ).toEqual(["customer", "tool", "flow"]);
  });
});

describe("checks pass-rate trend", () => {
  const run = (id: string, passed: number, failed: number, status = "done"): CheckRun => ({
    id,
    workflowId: 7,
    createdAt: "2026-09-26T09:00:00Z",
    createdBy: null,
    status: status as CheckRun["status"],
    passed,
    failed,
    results: [],
  });

  it("orders finished runs oldest first and skips running ones", () => {
    // API returns newest first.
    const points = passRates([
      run("c", 6, 0),
      run("r", 0, 0, "running"),
      run("b", 3, 3),
      run("a", 0, 6),
    ]);
    expect(points.map((p) => [p.id, p.pct])).toEqual([
      ["a", 0],
      ["b", 50],
      ["c", 100],
    ]);
  });
});

describe("prompt lint slot", () => {
  it("shows the per-turn cost and each finding", () => {
    lint.data = {
      tokens: 1234,
      usdPerTurn: 0.00031,
      findings: [
        {
          severity: "warn",
          code: "unsupplied_context",
          message: "initial_context.first_nme is not supplied",
          span: null,
        },
      ],
    };
    render(<PromptLint prompt="Hi {{initial_context.first_nme}}" isOpening={false} />);
    expect(
      screen.getByText(/1,234 tokens · about \$0\.310 per\s+1,000 model turns/),
    ).toBeInTheDocument();
    expect(screen.getByText("initial_context.first_nme is not supplied")).toBeInTheDocument();
  });

  it("stays quiet on an empty prompt", () => {
    const { container } = render(<PromptLint prompt="  " isOpening={false} />);
    expect(container).toBeEmptyDOMElement();
  });
});
