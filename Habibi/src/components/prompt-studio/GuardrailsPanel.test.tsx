// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// What the Guardrails tab promises a control does.
//
// Replaces a source-grep in studio-trust.test.ts that checked the file
// contained "not a live hard-block". Several of these switches are recorded
// after the bot has already replied, and one of them — the rate-quote flag —
// still lets the sentence reach a customer. An operator who reads the toggle as
// a hard block ships a card believing something is prevented that is only
// noticed, so the sentence has to be on screen and not merely in the file.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Guardrails } from "@/api/types/prompt-studio";

vi.mock("@/api/redaction", () => ({
  useRedactionRules: () => ({ data: [], isPending: false, isError: false }),
}));

// No RouterProvider in a unit render, and the panel links out to the Redaction
// Hub. A plain anchor keeps the link assertable without standing up a router.
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}));

const { GuardrailsPanel } = await import("./GuardrailsPanel");

const VALUE = {
  alwaysDiscloseRecording: true,
  escalateAbuse: true,
  maxTurns: 12,
  maxSeconds: 600,
  prohibited: [],
} as unknown as Guardrails;

describe("GuardrailsPanel", () => {
  it("says a rate-quote flag is noticed after the reply, not blocked before it", () => {
    render(<GuardrailsPanel value={VALUE} onChange={() => {}} />);

    // More than one control carries this hint; every one of them must.
    expect(screen.getAllByText(/not a live hard-block/i).length).toBeGreaterThan(0);
  });

  it("names the platform cap that overrides the turns slider on text", () => {
    render(<GuardrailsPanel value={VALUE} onChange={() => {}} />);

    // The slider runs to 40 and `bot_runtime` applies
    // `min(max_turns, _hard_max_turns())`, so an operator setting 30 gets the
    // platform's number on WhatsApp. The env var is named rather than its
    // value, which is configurable per deployment.
    expect(screen.getByText(/BOT_HARD_MAX_TURNS/)).toBeInTheDocument();
    expect(screen.getByText(/reduced to it, not honoured/i)).toBeInTheDocument();
  });
});
