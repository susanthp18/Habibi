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
import type { InboxChannel, ThreadStatus } from "@/api/types/inbox";

function thread(
  status: ThreadStatus,
  isMine: boolean,
  channel: InboxChannel = "whatsapp",
  assignedUserId: string | null = isMine ? "me" : status === "assigned" ? "colleague" : null,
) {
  return { status, isMine, channel, assignedUserId };
}

const agent = { canWrite: true, canReassign: false };
const supervisor = { canWrite: true, canReassign: true };
const viewer = { canWrite: false, canReassign: false };

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

  it("offers return-to-bot only on my own WhatsApp thread", () => {
    expect(getThreadHandoffState(thread("assigned", true), agent).canReturnToBot).toBe(true);
    expect(getThreadHandoffState(thread("assigned", true), viewer).canReturnToBot).toBe(false);
    expect(getThreadHandoffState(thread("assigned", false), agent).canReturnToBot).toBe(false);
    expect(getThreadHandoffState(thread("bot", true), agent).canReturnToBot).toBe(false);
    // No bot answers SMS: a thread "returned" to one would wait forever.
    expect(getThreadHandoffState(thread("assigned", true, "sms"), agent).canReturnToBot).toBe(
      false,
    );
  });

  it("offers the takeover only to someone allowed to make it", () => {
    // An agent pressing "Take over" on a colleague's thread got a 403 that
    // named an internal permission. Reassigning a held thread is a supervisor's.
    expect(getThreadHandoffState(thread("needs_human", false), agent).canClaim).toBe(true);
    expect(getThreadHandoffState(thread("bot", false), agent).canClaim).toBe(true);
    expect(getThreadHandoffState(thread("assigned", false), agent).canClaim).toBe(false);
    expect(getThreadHandoffState(thread("assigned", false), supervisor).canClaim).toBe(true);
    expect(getThreadHandoffState(thread("needs_human", false), viewer).canClaim).toBe(false);
  });

  it("counts an escalation a colleague holds as theirs", () => {
    // Held is who has it: an escalation keeps its assignee, and the agent
    // offered "Take over" on it pressed into a 403.
    const escalated = thread("needs_human", false, "whatsapp", "colleague");
    expect(getThreadHandoffState(escalated, agent).heldByTeammate).toBe(true);
    expect(getThreadHandoffState(escalated, agent).canClaim).toBe(false);
    expect(getThreadHandoffState(escalated, supervisor).canClaim).toBe(true);
  });
});
