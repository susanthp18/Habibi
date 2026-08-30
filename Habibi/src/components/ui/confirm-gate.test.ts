import { describe, expect, it } from "vitest";

import { createConfirmGate } from "./confirm-gate";

describe("createConfirmGate", () => {
  it("resolves true only when the action is explicitly confirmed", async () => {
    const gate = createConfirmGate();
    const answer = gate.ask();
    gate.settle(true);
    await expect(answer).resolves.toBe(true);
  });

  it("resolves false on cancel", async () => {
    const gate = createConfirmGate();
    const answer = gate.ask();
    gate.settle(false);
    await expect(answer).resolves.toBe(false);
  });

  it("never leaves a question unanswered when a second one arrives", async () => {
    // A stranded promise is an `await` that never returns: the handler holding
    // it freezes with no error and nothing observable from outside.
    const gate = createConfirmGate();
    const first = gate.ask();
    const second = gate.ask();
    gate.settle(true);
    await expect(first).resolves.toBe(false);
    await expect(second).resolves.toBe(true);
  });

  it("answers once, whichever way the dismissal is delivered twice", async () => {
    // Radix can fire both the action's onClick and a close for one dismissal.
    const gate = createConfirmGate();
    const answer = gate.ask();
    gate.settle(true);
    gate.settle(false);
    await expect(answer).resolves.toBe(true);
  });

  it("reports whether a question is outstanding", () => {
    const gate = createConfirmGate();
    expect(gate.pending).toBe(false);
    void gate.ask();
    expect(gate.pending).toBe(true);
    gate.settle(false);
    expect(gate.pending).toBe(false);
  });

  it("ignores an answer when nothing was asked", () => {
    const gate = createConfirmGate();
    expect(() => gate.settle(true)).not.toThrow();
  });
});
