// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// The sandbox header's claim about what a rehearsal does.
//
// Replaces a source-grep in studio-contract.test.ts that asserted the file did
// not contain "Both write real CRM rows" and did contain "no production side
// effects". That assertion passes on a string in a comment, on dead markup, and
// on a branch no reader reaches — none of which is the property anyone cares
// about, which is whether an operator is *shown* an accurate claim before they
// rehearse against a card.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SandboxHeader } from "./SandboxHeader";

function show(extra: Record<string, unknown> = {}) {
  return render(
    <SandboxHeader
      mode="text"
      onMode={() => {}}
      promptVersionId="v1"
      promptVersions={[{ id: "v1", label: "v1", status: "published" }] as never}
      onPromptVersion={() => {}}
      kbSnapshotId="kb1"
      kbSnapshots={[] as never}
      onKbSnapshot={() => {}}
      scenarioId="s1"
      scenarios={[] as never}
      onScenario={() => {}}
      turnsUsed={0}
      turnsMax={12}
      onReset={() => {}}
      onExport={() => {}}
      onPromote={() => {}}
      {...extra}
    />,
  );
}

describe("SandboxHeader", () => {
  it("does not tell the operator a rehearsal writes CRM rows", () => {
    show();

    // The sentence that was there, and the reason this test exists: a text
    // rehearsal simulates its tools, so promising real CRM writes invites
    // someone to rehearse a collections call believing the borrower's record
    // will show it.
    expect(screen.queryByText(/write real CRM rows/i)).toBeNull();
    expect(screen.getByText(/no production side effects/i)).toBeInTheDocument();
  });

  it("marks a draft version as a draft", () => {
    show({
      promptVersions: [{ id: "v1", label: "v1", status: "draft" }],
    });

    // Which version is under test changes what a green run means.
    expect(screen.getByText("Testing draft")).toBeInTheDocument();
  });
});
