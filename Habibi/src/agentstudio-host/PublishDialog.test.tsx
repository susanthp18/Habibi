// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// Publishing a Voice Studio agent: the release gate blocks, a changelog note is
// required, and the last rehearsal is surfaced before real customers hear it.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReleasePreflight } from "@/api/voice-studio";
import { mountAt } from "@/test/mount";

const state: { gate: ReleasePreflight } = { gate: {} as ReleasePreflight };
const mutate = vi.fn();

vi.mock("@/api/voice-studio", () => ({
  useReleasePreflight: () => ({ data: state.gate, isPending: false, isError: false }),
  usePublishAgent: () => ({ mutate, isPending: false }),
}));

const { default: PublishDialog } = await import("./PublishDialog");

function gate(over: Partial<ReleasePreflight>): ReleasePreflight {
  return {
    ok: true,
    errors: [],
    channels: ["inbound"],
    draftVersion: 6,
    liveVersion: 5,
    liveVersionId: 50,
    lastCheck: { status: "done", passed: 6, failed: 0, createdAt: "2026-09-26T09:00:00Z" },
    ...over,
  };
}

function open() {
  mountAt(
    "/",
    <PublishDialog workflowId={7} open onOpenChange={() => {}} onPublished={() => {}} />,
  );
}

describe("Voice Studio publish dialog", () => {
  beforeEach(() => mutate.mockReset());

  it("says what replaces what and where it goes live", async () => {
    state.gate = gate({});
    open();
    expect(await screen.findByText(/Draft v6 replaces live v5/)).toBeInTheDocument();
    expect(screen.getByText(/answers inbound calls/)).toBeInTheDocument();
  });

  it("blocks publishing while the release checks fail", async () => {
    state.gate = gate({ ok: false, errors: ["verify: tool is not approved"] });
    open();
    expect(await screen.findByText("verify: tool is not approved")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("What changed"), { target: { value: "New greeting" } });
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
  });

  it("requires a note, then publishes with it", async () => {
    state.gate = gate({});
    open();
    const publish = await screen.findByRole("button", { name: "Publish" });
    expect(publish).toBeDisabled();
    fireEvent.change(screen.getByLabelText("What changed"), {
      target: { value: "  Ask for the callback time first  " },
    });
    fireEvent.click(publish);
    expect(mutate).toHaveBeenCalledWith(
      { note: "Ask for the callback time first" },
      expect.anything(),
    );
  });

  it("warns when the agent was never rehearsed", async () => {
    state.gate = gate({ lastCheck: null });
    open();
    expect(await screen.findByText("No rehearsal on record")).toBeInTheDocument();
  });
});
