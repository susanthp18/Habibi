// -----------------------------------------------------------------------------
// Thread handoff state.
//
// `needsClaim` gates two things that must agree: it disables the composer, and
// it is the render condition for the Take-over button. When they disagreed the
// inbox produced a dead end — a composer that invited a reply the server was
// guaranteed to reject, and no visible way to make the reply legal.
// -----------------------------------------------------------------------------

import { describe, expect, it } from "vitest";

import { getThreadHandoffState } from "./meta";
import type { Thread, ThreadStatus } from "@/data/inbox-seed";

function thread(status: ThreadStatus, isMine: boolean): Thread {
  return { id: "CV-1", status, isMine, channel: "whatsapp" } as unknown as Thread;
}

describe("getThreadHandoffState", () => {
  it("offers the claim on a thread another agent is holding", () => {
    // The bug: `assigned` + `!isMine` was the one combination excluded, so the
    // composer enabled itself and the Take-over button — its only remedy —
    // was not rendered. The send came back `take_over_required`, telling the
    // operator to press a button that was not on screen.
    const state = getThreadHandoffState(thread("assigned", false));
    expect(state.needsClaim).toBe(true);
    expect(state.heldByTeammate).toBe(true);
  });

  it.each<ThreadStatus>(["bot", "needs_human", "escalated", "assigned"])(
    "requires a claim on a %s thread that is not mine",
    (status) => {
      expect(getThreadHandoffState(thread(status, false)).needsClaim).toBe(true);
    },
  );

  it.each<ThreadStatus>(["bot", "needs_human", "escalated", "assigned"])(
    "requires no claim once the thread is mine (%s)",
    (status) => {
      expect(getThreadHandoffState(thread(status, true)).needsClaim).toBe(false);
    },
  );

  it("does not call my own thread a teammate's", () => {
    expect(getThreadHandoffState(thread("assigned", true)).heldByTeammate).toBe(false);
  });

  it("still reports the bot as handling only when it is", () => {
    expect(getThreadHandoffState(thread("bot", false)).botHandling).toBe(true);
    expect(getThreadHandoffState(thread("assigned", false)).botHandling).toBe(false);
    expect(getThreadHandoffState(thread("bot", true)).botHandling).toBe(false);
  });

  it("offers return-to-bot only on my own claimed thread, and only when wired", () => {
    expect(getThreadHandoffState(thread("assigned", true), true).canReturnToBot).toBe(true);
    expect(getThreadHandoffState(thread("assigned", true), false).canReturnToBot).toBe(false);
    expect(getThreadHandoffState(thread("assigned", false), true).canReturnToBot).toBe(false);
    expect(getThreadHandoffState(thread("bot", true), true).canReturnToBot).toBe(false);
  });
});
