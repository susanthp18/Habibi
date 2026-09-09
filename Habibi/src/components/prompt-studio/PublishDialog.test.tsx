// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// The publish dialog, rendered.
//
// Every gate added this cycle ships an operator-visible surface and nothing
// tested that surface. That matters more than it sounds: a gate is only a
// control if its verdict reaches the person deciding to publish, and the ways
// this dialog can fail quietly are all invisible to a source pin — a `warn` that
// renders as nothing, a `fail` that leaves Confirm enabled, a stale report shown
// under a "running" banner.
//
// It also pins the two things the audit found here by reading the file, which is
// exactly the assertion style being retired: that the compiler banner no longer
// claims a hardcoded gate range, and that gate ids reach the screen.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CompileReport } from "@/api/agent-studio";

vi.mock("@/api/prompt-studio", () => ({
  useTtsVoiceCatalog: () => ({ data: [], isPending: false, isError: false }),
}));

import { PublishDialog } from "./PublishDialog";

const SIDE = {
  prompt: "You are a collections agent.",
  persona: { traits: {}, language: "English" },
  voice: {},
  guardrails: {},
} as never;

function report(gates: CompileReport["gates"]): CompileReport {
  return {
    bot_id: "kaia-v2-4",
    gates,
    effective_tools: [],
    idle_tools: [],
    idle_voice_tools: 0,
    voice_tool_cap: 12,
    skill_description_tokens: 0,
    mission_entries: {},
    card: {},
  } as unknown as CompileReport;
}

function show(extra: Record<string, unknown> = {}) {
  return render(
    <PublishDialog
      open
      onOpenChange={() => {}}
      onConfirm={() => {}}
      toLabel="v1.6"
      from={SIDE}
      to={SIDE}
      {...extra}
    />,
  );
}

describe("PublishDialog", () => {
  it("shows each gate's id, name and verdict", () => {
    show({
      compileReport: report([
        { gate: "G4", name: "tools", status: "pass", detail: "", issues: [] },
        { gate: "G-F7", name: "carry_is_fact_only", status: "warn", detail: "", issues: [] },
      ]),
    });

    // The id is what an operator quotes in a support thread, and G-F7 is one of
    // the ids that had two meanings until the registry landed.
    expect(screen.getByText("G4")).toBeInTheDocument();
    expect(screen.getByText("G-F7")).toBeInTheDocument();
    expect(screen.getByText(/carry_is_fact_only/)).toBeInTheDocument();
  });

  it("does not claim a fixed range of gates while compiling", () => {
    show({ compileBusy: true });

    // "Running compiler G0–G16…" was already wrong: it named none of the G-OB,
    // G-F or G-LINT gates, so it undercounted the checks by about a third. A
    // range maintained by hand is a range that goes stale.
    expect(screen.getByText(/Running the publish compiler/)).toBeInTheDocument();
    expect(screen.queryByText(/G0.*G16/)).toBeNull();
  });

  it("a warn is visible and does not block, a fail blocks", () => {
    // Confirm is gated by three things — the gates, a typed PUBLISH, and the
    // locale override. Satisfying the typed one isolates the gate's effect,
    // which is what this is actually about; asserting on the untyped button
    // would pass for the wrong reason.
    const confirmPublish = () =>
      fireEvent.change(screen.getByPlaceholderText("PUBLISH"), {
        target: { value: "PUBLISH" },
      });

    const warn = show({
      compileReport: report([
        { gate: "G-F7", name: "carry_is_fact_only", status: "warn", detail: "", issues: [] },
      ]),
    });
    expect(screen.getByText("warn")).toBeInTheDocument();
    confirmPublish();
    // Warn-first is the repo's stated way to introduce a gate; a warn that
    // silently blocked would make the next gate unadoptable.
    expect(screen.getByRole("button", { name: /^Publish/ })).toBeEnabled();
    warn.unmount();

    show({
      compileReport: report([
        { gate: "G4", name: "tools", status: "fail", detail: "unknown tool", issues: [] },
      ]),
    });
    expect(screen.getByText("fail")).toBeInTheDocument();
    confirmPublish();
    expect(screen.getByRole("button", { name: /^Publish/ })).toBeDisabled();
  });

  it("says so when the compiler could not be reached", () => {
    show({ compileError: "network error" });

    // The dangerous reading is "no gates failed". The operator is confirming
    // without evidence, and the dialog has to say which of the two it is.
    expect(screen.getByText(/could not be reached/i)).toBeInTheDocument();
    expect(screen.getByText(/without seeing them/i)).toBeInTheDocument();
  });
});
