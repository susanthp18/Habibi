// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// The Ship tab's Effective contract panel, rendered.
//
// This panel answers "what will production actually run", and it has three
// states that look alike on a source read and completely different to an
// operator: the contract could not be read, it has not been compiled yet, and
// it is still loading. Only the first is a problem, and the dangerous rendering
// is the one that shows a failed read as the second — "No compiled artefact
// yet" is a fact about the card, "could not load" is a fact about the request,
// and an operator who confuses them publishes without having seen the contract.
//
// A source pin cannot tell these apart: all three strings are in the file
// whatever the branch does. What differs is which one a reader is shown.
//
// The four data hooks are stubbed rather than served, following ToolsTab.test:
// this repository has no request-mocking library and does not need one to
// answer "given this query state, what does the panel render".
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const contract = vi.hoisted(() => ({
  state: { data: undefined, isPending: false, isError: false, error: undefined } as Record<
    string,
    unknown
  >,
  experiments: { data: [], isPending: false, isError: false } as Record<string, unknown>,
}));

vi.mock("@/api/agent-studio", () => ({
  useDeploymentExperiments: () => contract.experiments,
  useEffectiveContract: () => contract.state,
  useRollbackExperiment: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock("@/api/prompt-studio", () => ({
  useRollbackBotDeployment: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

const { ShipTab } = await import("./ShipTab");

function show(state: Record<string, unknown>, experiments: Record<string, unknown> = {}) {
  contract.state = { data: undefined, isPending: false, isError: false, error: undefined, ...state };
  contract.experiments = { data: [], isPending: false, isError: false, ...experiments };
  return render(
    <ShipTab
      botId="kaia-v2-4"
      value={{ trafficPct: 100, autoRollback: [] }}
      onChange={() => {}}
    />,
  );
}

describe("ShipTab · Effective contract", () => {
  it("says a failed read failed, and does not call it an absent artefact", () => {
    show({ isError: true, error: new Error("network error") });

    expect(screen.getByText("could not load")).toBeInTheDocument();
    expect(screen.getByText(/network error/)).toBeInTheDocument();
    // The degradation lie this panel could tell: a failed request rendered as
    // "this card has not been compiled", which reads as a fact about the card.
    expect(screen.queryByText(/No compiled artefact yet/)).toBeNull();
  });

  it("distinguishes still-loading from nothing-compiled", () => {
    const loading = show({ isPending: true });
    expect(screen.getByText("loading…")).toBeInTheDocument();
    expect(screen.queryByText(/No compiled artefact yet/)).toBeNull();
    loading.unmount();

    show({});
    // Settled and genuinely empty — now the absence claim is the true one.
    expect(screen.getByText(/No compiled artefact yet/)).toBeInTheDocument();
    expect(screen.queryByText("could not load")).toBeNull();
  });

  it("renders the compiled artefact's hash when there is one", () => {
    show({ data: { compiled: { bundle_hash: "abc123def456", skills: [], human_gates: [] } } });

    expect(screen.getByText("abc123def456")).toBeInTheDocument();
    expect(screen.queryByText(/No compiled artefact yet/)).toBeNull();
    expect(screen.queryByText("could not load")).toBeNull();
  });
});

describe("ShipTab · experiments", () => {
  it("a failed experiments read is not a claim that none are running", () => {
    // Replaces a source-grep for the string "experiments.isError". The whole
    // point is which sentence a reader is shown, and the file contains both
    // either way.
    show({}, { isError: true });
    expect(
      screen.getByText(/not a statement that none are running/i),
    ).toBeInTheDocument();
  });

  it("shows a running canary with its split and rollback triggers", () => {
    show(
      {},
      {
        data: [
          { id: "exp-1", status: "running", trafficPct: 25, autoRollback: ["slo_miss"] },
        ],
      },
    );
    expect(screen.getByText(/25% canary/)).toBeInTheDocument();
    expect(screen.getByText(/slo_miss/)).toBeInTheDocument();
  });

  it("offers no shadow control, because the card cannot hold one", () => {
    // `experiment.shadow` was retired from the schema, so this is the absence
    // of a control rather than a disabled one. The grep this replaces asserted
    // the file did not contain "value.shadow", which went red for the very
    // change that made it true.
    show({});
    expect(screen.queryByText(/shadow/i)).toBeNull();
  });
});
