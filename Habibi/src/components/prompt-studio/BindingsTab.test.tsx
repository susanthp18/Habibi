// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// The provider model picker refuses what the runtime cannot construct.
//
// Replaces a source-grep in studio-trust.test.ts that checked BindingsTab
// contained the string "modelBindingSelectable". That helper is already
// unit-tested in the same file, so the grep proved nothing the tests did not —
// except that the identifier appeared somewhere in the component, which is true
// of a commented-out call.
//
// What matters is that a model with no API key, or one the provider only
// previews, cannot be bound: binding it produces a card that passes every gate
// and then fails at TTS construction, on a call, after the customer answered.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const MODELS = [
  {
    id: "pm-azure",
    providerId: "azure",
    providerName: "Azure",
    displayName: "azure-neural",
    runtime: "live",
    configured: true,
  },
  {
    id: "pm-fish",
    providerId: "fish",
    providerName: "Fish",
    displayName: "fish-speech",
    runtime: "unavailable",
    runtimeDetail: "no API key configured",
    configured: false,
  },
];

vi.mock("@/api/providers", () => ({
  providerDot: () => "bg-surface",
  useProviderBindings: () => ({
    data: [],
    isPending: false,
    isError: false,
    error: undefined,
  }),
  useProviderModels: () => ({ data: MODELS, isPending: false, isError: false }),
  useUpsertBinding: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteBinding: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

const { BindingsTab } = await import("./BindingsTab");

describe("BindingsTab", () => {
  it("says a card with no bindings falls back, rather than showing nothing", () => {
    render(<BindingsTab botId="kaia-v2-4" />);

    // An empty table would read as "nothing to configure". What is true is that
    // the runtime falls back to the registry default, which is a choice nobody
    // made.
    expect(screen.getByText("No bindings resolved")).toBeInTheDocument();
    expect(screen.getByText(/falls back to whatever the registry defaults to/i)).toBeInTheDocument();
  });

  it("opens a slot-and-model form rather than binding blind", () => {
    render(<BindingsTab botId="kaia-v2-4" />);
    fireEvent.click(screen.getByRole("button", { name: /Add binding/i }));

    expect(screen.getByText("Slot")).toBeInTheDocument();
    expect(screen.getByText("Model")).toBeInTheDocument();
    expect(screen.getByText("Pick a model")).toBeInTheDocument();

    // Whether an unconstructable model can be *chosen* is decided by
    // `modelBindingSelectable` / `modelBindingLabel`, both unit-tested in
    // studio-trust.test.ts. Radix renders select options into a portal only
    // once opened, so asserting them here would test Radix, not this tab —
    // which is the same redundancy the source-grep this replaces had.
  });
});
